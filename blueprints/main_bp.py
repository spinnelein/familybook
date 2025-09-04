from flask import Blueprint, render_template, request, jsonify, abort, session, flash, g, render_template_string
from db.database import get_db
from db.queries import (
    log_activity, get_setting
)
from services.email_service import send_notification_email
from services.media_service import (
    handle_single_media_upload, handle_multiple_image_upload,
    handle_multiple_media_upload, serve_uploaded_file,
    handle_google_photos_download, cleanup_orphaned_media
)
from utils.timezone_utils import get_pacific_now
from utils.url_utils import redirect, url_for_with_prefix as url_for
import sqlite3
import traceback

# Create the Blueprint
main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def home():
    """Home page route"""
    return render_template('home.html')

@main_bp.route('/create-post', methods=['GET', 'POST'])
@main_bp.route('/create-post/<magic_token>', methods=['GET', 'POST'])
def create_post_route(magic_token=None):
    """Create a new post"""
    # Clear any stale flash messages that aren't relevant to post creation
    if '_flashes' in session:
        existing_messages = session['_flashes']
        filtered_messages = [msg for msg in existing_messages 
                           if not any(word in msg[1].lower() for word in ['reply', 'comment'])]
        if len(filtered_messages) != len(existing_messages):
            session['_flashes'] = filtered_messages
    
    # Check if user is admin when magic_token is provided
    user = None
    if magic_token:
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE magic_token = ?', (magic_token,)).fetchone()
        if not user:
            abort(403)
        if not user['is_admin']:
            abort(403)  # Only admins can create posts
        
        # Update last login time with Pacific Time
        db.execute('UPDATE users SET last_login = ? WHERE id = ?', (get_pacific_now(), user['id']))
        db.commit()
    
    if request.method == 'POST':
        title = request.form['title']
        content = request.form['content']
        tags = request.form.get('tags', '').strip()

        db = get_db()
        author_id = user['id'] if user else None
        
        # Insert post with tags and Pacific Time
        cursor = db.execute(
            "INSERT INTO posts (title, content, author_id, tags, created) VALUES (?, ?, ?, ?, ?)",
            (title, content, author_id, tags, get_pacific_now())
        )
        post_id = cursor.lastrowid
        db.commit()
        
        # Log post creation activity
        if user:
            log_activity('post_create', user['id'], user['name'], post_id, title)
        
        # Send email notifications using templates
        if get_setting('notifications_enabled', 'false').lower() == 'true':
            # Determine if this is a major event
            is_major = tags and 'major' in tags.lower()
            template_name = 'major_event' if is_major else 'new_post'
            
            # Get all users who should receive notifications
            db = get_db()
            users = db.execute('SELECT id FROM users WHERE email != ""').fetchall()
            
            # Send notifications to each user based on their preferences
            for user_row in users:
                try:
                    send_notification_email(template_name, user_row['id'], 
                                          post_title=title,
                                          post_author=user['name'] if user else 'Unknown',
                                          post_content=content[:500] + ('...' if len(content) > 500 else ''),
                                          post_tags=tags)
                except Exception as e:
                    print(f"Failed to send notification to user {user_row['id']}: {e}")
                    continue
        
        # Clean up orphaned media files
        cleanup_orphaned_media()
        
        flash("Post created!", "success")
        if magic_token:
            return redirect(url_for('main.create_post_route', magic_token=magic_token))
        return redirect(url_for('main.create_post_route'))
    
    # Get available filter tags for the tags input field
    db = get_db()
    filter_tags = db.execute('SELECT name FROM filter_tags ORDER BY name').fetchall()
    available_tags = [tag['name'] for tag in filter_tags]
    
    return render_template('create_post.html', user=user, available_tags=available_tags)

@main_bp.route('/upload-media', methods=['POST'])
def upload_media():
    """Handle direct file uploads from TinyMCE"""
    result = handle_single_media_upload()
    
    if 'status' in result:
        return jsonify(result), result['status']
    
    return jsonify(result)

@main_bp.route('/upload-multiple-images', methods=['POST'])
def upload_multiple_images():
    """Handle multiple image uploads"""
    # Debug logging
    print("Files received:", request.files)
    print("Form data:", request.form)
    
    result = handle_multiple_image_upload()
    
    if 'status' in result:
        return jsonify(result), result['status']
    
    return jsonify(result)

@main_bp.route('/upload-multiple-media', methods=['POST'])
def upload_multiple_media():
    """Handle multiple image and video uploads"""
    # Debug logging
    print("Files received:", request.files)
    print("Form data:", request.form)
    
    result = handle_multiple_media_upload()
    
    if 'status' in result:
        return jsonify(result), result['status']
    
    return jsonify(result)

@main_bp.route('/uploads/<filename>')
def uploaded_file(filename):
    """Serve uploaded files"""
    return serve_uploaded_file(filename)

@main_bp.route('/posts/<magic_token>')
@main_bp.route('/posts/<magic_token>/<year_month>')
@main_bp.route('/posts/<magic_token>/show/<show_type>')
@main_bp.route('/posts/<magic_token>/tag/<tag_filter>')
def posts(magic_token, year_month=None, show_type=None, tag_filter=None):
    """View posts with magic link authentication"""
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE magic_token = ?', (magic_token,)).fetchone()
    if not user:
        abort(403)
    
    # Log visit activity
    log_activity('visit', user['id'], user['name'])
    
    # Get user's last login time before updating it
    last_login = user['last_login'] if user['last_login'] else '1970-01-01 00:00:00'
    
    # Update last login time
    db.execute('UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?', (user['id'],))
    db.commit()
    
    # Get posts based on filter type
    if year_month:
        # Show posts for specific month (format: YYYY-MM)
        try:
            year, month = year_month.split('-')
            posts = db.execute('''
                SELECT p.*, u.name as author_name 
                FROM posts p 
                LEFT JOIN users u ON p.author_id = u.id
                WHERE strftime('%Y-%m', p.created) = ? 
                ORDER BY p.id DESC
            ''', (year_month,)).fetchall()
            current_view = f"month-{year_month}"
        except ValueError:
            abort(404)
    elif tag_filter:
        # Show posts filtered by tag
        posts = db.execute('''
            SELECT p.*, u.name as author_name 
            FROM posts p 
            LEFT JOIN users u ON p.author_id = u.id
            WHERE p.tags IS NOT NULL AND p.tags != '' 
            AND (p.tags = ? OR p.tags LIKE ? OR p.tags LIKE ? OR p.tags LIKE ?)
            ORDER BY p.id DESC
        ''', (tag_filter, f'{tag_filter},%', f'%,{tag_filter},%', f'%,{tag_filter}')).fetchall()
        current_view = f"tag-{tag_filter}"
    elif show_type == 'all':
        # Show all posts
        posts = db.execute('''
            SELECT p.*, u.name as author_name 
            FROM posts p 
            LEFT JOIN users u ON p.author_id = u.id
            ORDER BY p.id DESC
        ''').fetchall()
        current_view = "all"
    elif show_type == 'new':
        # Show only new posts since last login
        posts = db.execute('''
            SELECT p.*, u.name as author_name 
            FROM posts p 
            LEFT JOIN users u ON p.author_id = u.id
            WHERE p.created > ? 
            ORDER BY p.id DESC
        ''', (last_login,)).fetchall()
        current_view = "new"
    else:
        # Default: Show only new posts since last login
        new_posts = db.execute('''
            SELECT p.*, u.name as author_name 
            FROM posts p 
            LEFT JOIN users u ON p.author_id = u.id
            WHERE p.created > ? 
            ORDER BY p.id DESC
        ''', (last_login,)).fetchall()
        
        if new_posts:
            # If there are new posts, show them
            posts = new_posts
            current_view = "new"
        else:
            # If no new posts, show all posts by default
            posts = db.execute('''
                SELECT p.*, u.name as author_name 
                FROM posts p 
                LEFT JOIN users u ON p.author_id = u.id
                ORDER BY p.id DESC
            ''').fetchall()
            current_view = "all"
    
    # Get available months that have posts
    available_months = db.execute('''
        SELECT DISTINCT strftime('%Y-%m', created) as month,
               strftime('%Y', created) as year,
               strftime('%m', created) as month_num,
               COUNT(*) as post_count
        FROM posts 
        GROUP BY strftime('%Y-%m', created) 
        ORDER BY month DESC
    ''').fetchall()
    
    # Get comments for posts based on user permissions
    comments_by_post = {}
    if user:
        for post in posts:
            if user['is_admin']:
                # Admins see all comments
                post_comments = db.execute('''
                    SELECT c.*, u.name as user_name, u.is_admin as user_is_admin
                    FROM comments c 
                    JOIN users u ON c.user_id = u.id 
                    WHERE c.post_id = ? 
                    ORDER BY c.created ASC, c.parent_comment_id ASC
                ''', (post['id'],)).fetchall()
            else:
                # Regular users see only their own comments and admin replies to their comments
                post_comments = db.execute('''
                    SELECT c.*, u.name as user_name, u.is_admin as user_is_admin
                    FROM comments c 
                    JOIN users u ON c.user_id = u.id 
                    WHERE c.post_id = ? AND (
                        c.user_id = ? OR 
                        (u.is_admin = 1 AND c.parent_comment_id IN (
                            SELECT id FROM comments WHERE user_id = ? AND post_id = ?
                        ))
                    )
                    ORDER BY c.created ASC, c.parent_comment_id ASC
                ''', (post['id'], user['id'], user['id'], post['id'])).fetchall()
            comments_by_post[post['id']] = post_comments
    
    # Get reaction data for all posts
    reactions_by_post = {}
    user_reactions = {}
    heart_users_by_post = {}
    for post in posts:
        # Get heart count for this post
        heart_count = db.execute('''
            SELECT COUNT(*) as count 
            FROM reactions 
            WHERE post_id = ? AND reaction_type = ?
        ''', (post['id'], 'heart')).fetchone()['count']
        reactions_by_post[post['id']] = heart_count
        
        # Get list of users who liked this post
        heart_users = db.execute('''
            SELECT u.name 
            FROM reactions r 
            JOIN users u ON r.user_id = u.id 
            WHERE r.post_id = ? AND r.reaction_type = ? 
            ORDER BY r.created DESC
        ''', (post['id'], 'heart')).fetchall()
        heart_users_by_post[post['id']] = [row['name'] for row in heart_users]
        
        # Check if current user has hearted this post
        if user:
            user_heart = db.execute('''
                SELECT id FROM reactions 
                WHERE post_id = ? AND user_id = ? AND reaction_type = ?
            ''', (post['id'], user['id'], 'heart')).fetchone()
            user_reactions[post['id']] = bool(user_heart)
        else:
            user_reactions[post['id']] = False
    
    # Get filter tags for the sidebar
    filter_tags = db.execute('SELECT * FROM filter_tags ORDER BY name').fetchall()
    
    return render_template('posts.html', posts=posts, user=user, 
                         available_months=available_months, current_month=year_month,
                         comments_by_post=comments_by_post, reactions_by_post=reactions_by_post,
                         user_reactions=user_reactions, heart_users_by_post=heart_users_by_post,
                         last_login=last_login, current_view=current_view, 
                         filter_tags=filter_tags, current_tag=tag_filter)

@main_bp.route('/posts')
def posts_no_token():
    """Redirect to home when accessing posts without a magic token"""
    return redirect(url_for('main.home'))

@main_bp.route('/add-comment/<magic_token>', methods=['POST'])
def add_comment(magic_token):
    """Add a comment to a post"""
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE magic_token = ?', (magic_token,)).fetchone()
    if not user:
        abort(403)
    
    post_id = request.form.get('post_id')
    content = request.form.get('content')
    parent_comment_id = request.form.get('parent_comment_id')
    
    if not post_id or not content:
        flash('Missing post ID or comment content', 'danger')
        return redirect(url_for('main.posts', magic_token=magic_token))
    
    # If this is a reply, verify permissions and parent comment
    if parent_comment_id:
        # Verify the parent comment exists and belongs to this post
        parent_comment = db.execute(
            'SELECT c.*, u.is_admin as parent_is_admin FROM comments c JOIN users u ON c.user_id = u.id WHERE c.id = ? AND c.post_id = ?', 
            (parent_comment_id, post_id)
        ).fetchone()
        if not parent_comment:
            flash('Invalid parent comment', 'danger')
            return redirect(url_for('main.posts', magic_token=magic_token))
        
        # Check reply permissions
        if not user['is_admin']:
            # Find the root comment of this thread
            root_comment_id = parent_comment_id
            if parent_comment['parent_comment_id']:
                root_comment_id = parent_comment['parent_comment_id']
            
            # Check if user is involved in this thread
            user_involved = db.execute('''
                SELECT COUNT(*) as count FROM comments 
                WHERE post_id = ? AND user_id = ? AND (
                    id = ? OR parent_comment_id = ?
                )
            ''', (post_id, user['id'], root_comment_id, root_comment_id)).fetchone()['count']
            
            if user_involved == 0:
                abort(403)
    
    # Add the comment
    db.execute('INSERT INTO comments (post_id, user_id, content, parent_comment_id) VALUES (?, ?, ?, ?)',
               (post_id, user['id'], content, parent_comment_id))
    db.commit()
    
    # Log comment activity
    post = db.execute('SELECT title FROM posts WHERE id = ?', (post_id,)).fetchone()
    if post:
        action_type = 'comment_reply' if parent_comment_id else 'comment'
        log_activity(action_type, user['id'], user['name'], post_id, post['title'], content[:200])
    
    # Send reply notification email if this is a reply
    if parent_comment_id and get_setting('notifications_enabled', 'false').lower() == 'true':
        try:
            # Get the parent comment and its author
            parent_comment = db.execute('''
                SELECT c.*, u.id as author_id, u.name as author_name, p.title as post_title
                FROM comments c 
                JOIN users u ON c.user_id = u.id 
                JOIN posts p ON c.post_id = p.id
                WHERE c.id = ?
            ''', (parent_comment_id,)).fetchone()
            
            if parent_comment and parent_comment['author_id'] != user['id']:
                # Don't send notification if replying to yourself
                send_notification_email('comment_reply', parent_comment['author_id'],
                                       post_title=parent_comment['post_title'],
                                       original_comment=parent_comment['content'][:200] + ('...' if len(parent_comment['content']) > 200 else ''),
                                       reply_author=user['name'],
                                       reply_content=content[:200] + ('...' if len(content) > 200 else ''))
        except Exception as e:
            print(f"Failed to send comment reply notification: {e}")
    
    if parent_comment_id:
        flash('Reply added successfully!', 'success')
    else:
        flash('Comment added successfully!', 'success')
    
    return redirect(url_for('main.posts', magic_token=magic_token))

@main_bp.route('/delete-post/<magic_token>/<int:post_id>', methods=['POST'])
def delete_post(magic_token, post_id):
    """Delete a post (admin only)"""
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE magic_token = ?', (magic_token,)).fetchone()
    if not user or not user['is_admin']:
        abort(403)
    
    # Delete the post and related data
    post = db.execute('SELECT * FROM posts WHERE id = ?', (post_id,)).fetchone()
    if post:
        # Delete comments and reactions associated with the post
        db.execute('DELETE FROM comments WHERE post_id = ?', (post_id,))
        db.execute('DELETE FROM reactions WHERE post_id = ?', (post_id,))
        
        # Delete the post
        db.execute('DELETE FROM posts WHERE id = ?', (post_id,))
        db.commit()
    else:
        flash('Post not found!', 'danger')
    
    return redirect(url_for('main.posts', magic_token=magic_token))

@main_bp.route('/toggle-heart/<magic_token>', methods=['POST'])
def toggle_heart(magic_token):
    """Toggle heart/like reaction for a post"""
    print(f"toggle_heart called with magic_token: {magic_token}")
    try:
        # Verify user
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE magic_token = ?', (magic_token,)).fetchone()
        if not user:
            print(f"No user found for magic_token: {magic_token}")
            return jsonify({'error': 'Invalid user token'}), 403
        
        # Get post ID
        post_id = request.form.get('post_id')
        print(f"Received post_id: {post_id}")
        if not post_id:
            print("Missing post_id in form data")
            return jsonify({'error': 'Missing post ID'}), 400
        
        # Check if post exists
        post = db.execute('SELECT * FROM posts WHERE id = ?', (post_id,)).fetchone()
        if not post:
            return jsonify({'error': 'Post not found'}), 404
        
        # Check if user already hearted this post
        existing_reaction = db.execute(
            'SELECT * FROM reactions WHERE user_id = ? AND post_id = ? AND reaction_type = ?',
            (user['id'], post_id, 'heart')
        ).fetchone()
        
        if existing_reaction:
            # Remove heart
            db.execute(
                'DELETE FROM reactions WHERE user_id = ? AND post_id = ? AND reaction_type = ?',
                (user['id'], post_id, 'heart')
            )
            hearted = False
            # Log unlike activity
            log_activity('unlike', user['id'], user['name'], post_id, post['title'])
        else:
            # Add heart with Pacific Time
            db.execute(
                'INSERT INTO reactions (user_id, post_id, reaction_type, created) VALUES (?, ?, ?, ?)',
                (user['id'], post_id, 'heart', get_pacific_now())
            )
            hearted = True
            # Log like activity
            log_activity('like', user['id'], user['name'], post_id, post['title'])
        
        db.commit()
        
        # Get updated count
        count = db.execute(
            'SELECT COUNT(*) as count FROM reactions WHERE post_id = ? AND reaction_type = ?',
            (post_id, 'heart')
        ).fetchone()['count']
        
        return jsonify({
            'success': True,
            'hearted': hearted,
            'count': count
        })
        
    except Exception as e:
        print(f"Error toggling heart: {e}")
        return jsonify({'error': 'Server error'}), 500

@main_bp.route('/user-settings/<magic_token>')
def user_settings(magic_token):
    """Display user email preference settings"""
    try:
        print(f"User settings accessed with magic_token: {magic_token}")
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE magic_token = ?', (magic_token,)).fetchone()
        if not user:
            print(f"No user found with magic_token: {magic_token}")
            abort(403)
        
        print(f"Found user: {user['name']} (ID: {user['id']})")
        
        # Check if user_notification_preferences table exists
        try:
            prefs = db.execute('SELECT * FROM user_notification_preferences WHERE user_id = ?', 
                              (user['id'],)).fetchone()
            print(f"User preferences found: {prefs is not None}")
        except Exception as table_error:
            print(f"Error accessing user_notification_preferences table: {table_error}")
            # Table might not exist, create it
            try:
                db.execute('''CREATE TABLE IF NOT EXISTS user_notification_preferences (
                    user_id INTEGER PRIMARY KEY,
                    account_created INTEGER DEFAULT 1,
                    new_post INTEGER DEFAULT 1,
                    major_event INTEGER DEFAULT 1,
                    comment_reply INTEGER DEFAULT 1,
                    updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )''')
                db.commit()
                print("Created user_notification_preferences table")
                prefs = None
            except Exception as create_error:
                print(f"Error creating table: {create_error}")
                raise
        
        # If no preferences exist, create defaults
        if not prefs:
            print("Creating default preferences for user")
            db.execute('''INSERT INTO user_notification_preferences 
                         (user_id, account_created, new_post, major_event, comment_reply)
                         VALUES (?, 1, 1, 1, 1)''', (user['id'],))
            db.commit()
            prefs = db.execute('SELECT * FROM user_notification_preferences WHERE user_id = ?', 
                              (user['id'],)).fetchone()
            print("Default preferences created")
        
        print("Rendering user_settings.html template")
        return render_template('user_settings.html', user=user, prefs=prefs)
        
    except Exception as e:
        print(f"Error loading user settings: {str(e)}")
        traceback.print_exc()
        return f"Error loading user settings: {str(e)}", 500

@main_bp.route('/update-user-settings/<magic_token>', methods=['POST'])
def update_user_settings(magic_token):
    """Update user email preference settings"""
    try:
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE magic_token = ?', (magic_token,)).fetchone()
        if not user:
            abort(403)
        
        # Get form data - handle both radio button and legacy checkbox formats
        notification_level = request.form.get('notification_level')
        comment_reply = 1 if request.form.get('comment_reply') else 0
        
        # Convert radio button choice to individual preferences
        if notification_level == 'all':
            new_post = 1
            major_event = 1
        elif notification_level == 'major_only':
            new_post = 0
            major_event = 1
        elif notification_level == 'none':
            new_post = 0
            major_event = 0
        else:
            # Legacy fallback for old checkbox format
            new_post = 1 if request.form.get('new_post') else 0
            major_event = 1 if request.form.get('major_event') else 0
        
        # Update preferences
        db.execute('''UPDATE user_notification_preferences 
                     SET new_post = ?, major_event = ?, comment_reply = ?
                     WHERE user_id = ?''',
                   (new_post, major_event, comment_reply, user['id']))
        db.commit()
        
        flash('Your email preferences have been updated successfully!', 'success')
        return redirect(url_for('main.user_settings', magic_token=magic_token))
        
    except Exception as e:
        print(f"Error updating user settings: {str(e)}")
        flash('Error updating preferences. Please try again.', 'danger')
        return redirect(url_for('main.user_settings', magic_token=magic_token))

@main_bp.route('/photos/<magic_token>')
@main_bp.route('/photos/<magic_token>/<sort_order>')
@main_bp.route('/photos/<magic_token>/<sort_order>/<int:offset>')
def photo_stream(magic_token, sort_order='recent', offset=0):
    """Display photo stream"""
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE magic_token = ?', (magic_token,)).fetchone()
    if not user:
        abort(403)
    
    # Update last login time
    db.execute('UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?', (user['id'],))
    db.commit()
    
    # Get individual images from the images table
    limit = 50
    
    if sort_order == 'oldest':
        images = db.execute('''
            SELECT i.*, p.title as post_title, u.name as author_name, p.created as post_created
            FROM images i 
            JOIN posts p ON i.post_id = p.id 
            LEFT JOIN users u ON p.author_id = u.id
            ORDER BY i.upload_date ASC
            LIMIT ? OFFSET ?
        ''', (limit, offset)).fetchall()
    else:  # recent
        images = db.execute('''
            SELECT i.*, p.title as post_title, u.name as author_name, p.created as post_created
            FROM images i 
            JOIN posts p ON i.post_id = p.id 
            LEFT JOIN users u ON p.author_id = u.id
            ORDER BY i.upload_date DESC
            LIMIT ? OFFSET ?
        ''', (limit, offset)).fetchall()
    
    # Check if there are more images
    total_images = db.execute('SELECT COUNT(*) as count FROM images').fetchone()['count']
    has_more = (offset + limit) < total_images
    
    return render_template('photo_stream.html', 
                         images=images, 
                         user=user, 
                         sort_order=sort_order, 
                         offset=offset,
                         has_more=has_more,
                         total_images=total_images)

@main_bp.route('/about-us')
@main_bp.route('/about_us')
def about_us():
    """Display the About Us page"""
    try:
        # Get the about us content from database
        conn = sqlite3.connect('familybook.db')
        cursor = conn.cursor()
        
        # Create table if it doesn't exist
        cursor.execute('''CREATE TABLE IF NOT EXISTS about_us 
                         (id INTEGER PRIMARY KEY, content TEXT, updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        # Get the latest content
        cursor.execute('SELECT content FROM about_us ORDER BY id DESC LIMIT 1')
        result = cursor.fetchone()
        conn.close()
        
        content = result[0] if result else '<h2>Welcome to Our Family</h2><p>Share your family story here...</p>'
        
        return render_template('about_us.html', content=content)
    except Exception as e:
        print(f"Error loading about us page: {str(e)}")
        return "Error loading page", 500

# Google Photos API Routes
@main_bp.route('/api/google-photos/create-session', methods=['POST'])
def create_picker_session_endpoint():
    """Create a Google Photos Picker session"""
    try:
        from google_photos import is_authenticated
        
        # Check if authenticated
        if not is_authenticated():
            auth_url = url_for('main.google_photos_auth', _external=True)
            return jsonify({
                'success': False,
                'error': 'Google Photos authentication required',
                'auth_required': True,
                'auth_url': auth_url
            }), 401
        
        # Use the updated create_picker_session function
        from google_photos import create_picker_session
        picker_session = create_picker_session()
        
        session_id = picker_session.get('id')
        picker_uri = picker_session.get('pickerUri')
        
        if not session_id or not picker_uri:
            return jsonify({
                'success': False,
                'error': 'Failed to create picker session - missing id or URI'
            }), 500
        
        return jsonify({
            'success': True,
            'sessionId': session_id,
            'pickerUri': picker_uri
        })
        
    except Exception as e:
        print(f"Error creating picker session: {str(e)}")
        
        # If authentication is required, return appropriate response
        if "Authentication required" in str(e):
            auth_url = url_for('main.google_photos_auth', _external=True)
            return jsonify({
                'success': False,
                'error': 'Google Photos authentication required',
                'auth_required': True,
                'auth_url': auth_url
            }), 401
        
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@main_bp.route('/api/google-photos/poll-session/<session_id>', methods=['GET'])
def poll_picker_session_endpoint(session_id):
    """Poll a Google Photos Picker session for completion"""
    try:
        from google_photos import poll_picker_session, get_picked_media_items
        
        # Use the updated poll_picker_session function
        session = poll_picker_session(session_id)
        
        # Check if media items have been selected
        media_items_picked = session.get('mediaItemsSet', False)
        
        if media_items_picked:
            # Session completed, get the actual picked media items using the correct API
            try:
                picked_items_response = get_picked_media_items(session_id)
                
                if picked_items_response.get('not_ready'):
                    # User hasn't finished selecting yet, continue polling
                    return jsonify({
                        'success': True,
                        'completed': False,
                        'state': 'PICKING_IN_PROGRESS'
                    })
                
                # Extract the picked media items
                picked_items = picked_items_response.get('mediaItems', [])
                
                return jsonify({
                    'success': True,
                    'completed': True,
                    'selectedItems': picked_items,
                    'count': len(picked_items)
                })
                
            except Exception as items_error:
                print(f"Error getting picked items: {items_error}")
                return jsonify({
                    'success': False,
                    'error': f'Error retrieving selected items: {str(items_error)}'
                }), 500
        
        else:
            # Still in progress
            return jsonify({
                'success': True,
                'completed': False,
                'state': 'PICKING_IN_PROGRESS'
            })
            
    except Exception as e:
        print(f"Error polling session {session_id}: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@main_bp.route('/api/google-photos/download-selected', methods=['POST'])
def download_selected_media():
    """Download and process selected media from Google Photos Picker"""
    return handle_google_photos_download()

@main_bp.route('/google-photos/auth')
def google_photos_auth():
    """Initiate Google Photos OAuth flow"""
    try:
        # Build the redirect URI
        redirect_uri = url_for('main.google_photos_callback', _external=True)
        
        # Get the authorization URL
        from google_photos import get_auth_url
        auth_url, state = get_auth_url(redirect_uri)
        
        # Store state in session for security
        session['oauth_state'] = state
        
        # Redirect user to Google's OAuth consent screen
        return redirect(auth_url)
    except Exception as e:
        return f"Error initiating OAuth: {str(e)}", 500

@main_bp.route('/google-photos/callback')
def google_photos_callback():
    """Handle Google Photos OAuth callback"""
    try:
        # Get the state and code from the callback
        state = request.args.get('state')
        code = request.args.get('code')
        error = request.args.get('error')
        
        if error:
            return f"OAuth error: {error}", 400
        
        # Verify state matches
        if state != session.get('oauth_state'):
            return "Invalid OAuth state", 400
        
        # Build the redirect URI (must match exactly)
        redirect_uri = url_for('main.google_photos_callback', _external=True)
        
        # Handle the OAuth callback
        from google_photos import handle_oauth_callback
        creds = handle_oauth_callback(request.url, redirect_uri)
        
        # Clear the state from session
        session.pop('oauth_state', None)
        
        # Redirect to a success page or back to the create post page
        return redirect(url_for('main.create_post_route'))
    except Exception as e:
        return f"Error handling OAuth callback: {str(e)}", 500

# Test polling route (for debugging)
@main_bp.route('/test-polling')
def test_polling():
    """Test page for Google Photos polling"""
    return '''
    <!DOCTYPE html>
    <html><head><title>Test Polling</title></head><body>
    <h1>Test Google Photos Polling</h1>
    <button onclick="testPolling()">Test Poll Session</button>
    <div id="results"></div>
    <script>
        async function testPolling() {
            const sessionId = 'e94bd304-1ab4-440f-a4bc-54094baae781';
            try {
                console.log('Testing polling...');
                const response = await fetch(`/api/google-photos/poll-session/${sessionId}`);
                const pollData = await response.json();
                console.log('Poll response:', pollData);
                document.getElementById('results').innerHTML = '<pre>' + JSON.stringify(pollData, null, 2) + '</pre>';
                
                if (pollData.selectedItems && pollData.selectedItems.length > 0) {
                    console.log('Testing download...');
                    const downloadResponse = await fetch('/api/google-photos/download-selected', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ selectedItems: pollData.selectedItems })
                    });
                    const downloadData = await downloadResponse.json();
                    console.log('Download response:', downloadData);
                    document.getElementById('results').innerHTML += '<h3>Download:</h3><pre>' + JSON.stringify(downloadData, null, 2) + '</pre>';
                }
            } catch (error) {
                console.error('Error:', error);
                document.getElementById('results').innerHTML = 'Error: ' + error.message;
            }
        }
    </script>
    </body></html>
    '''