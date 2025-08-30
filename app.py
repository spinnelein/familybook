import os
import sqlite3
import uuid
import requests
from flask import Flask, jsonify, request, redirect, url_for, render_template, send_from_directory, flash, g, abort
from google_photos import get_authenticated_service, create_picker_session, poll_picker_session, get_picked_media_items
import time

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'static/uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max upload size
app.config['DATABASE'] = 'familybook.db'
app.secret_key = 'your-secret-key'

ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'mov', 'avi', 'webm'}

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def allowed_file(filename, allowed_exts):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_exts

def extract_images_from_posts():
    """Extract images from post content and populate images table"""
    import re
    import os
    from datetime import datetime
    
    with app.app_context():
        db = get_db()
        
        # Get all posts
        posts = db.execute('SELECT id, content, created FROM posts').fetchall()
        
        for post in posts:
            if not post['content']:
                continue
                
            # Find all img tags in the HTML content
            img_matches = re.findall(r'<img[^>]+src=["\']([^"\']+)["\'][^>]*>', post['content'])
            
            for img_url in img_matches:
                # Only include images from our uploads folder
                if '/uploads/' in img_url:
                    filename = img_url.split('/uploads/')[-1]
                    
                    # Check if this image is already in the images table
                    existing = db.execute(
                        'SELECT id FROM images WHERE post_id = ? AND filename = ?',
                        (post['id'], filename)
                    ).fetchone()
                    
                    if not existing:
                        # Try to get file modification time as upload_date
                        upload_date = post['created']  # Default to post creation date
                        try:
                            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                            if os.path.exists(file_path):
                                # Use file modification time
                                mtime = os.path.getmtime(file_path)
                                upload_date = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
                        except:
                            pass  # Use default date
                        
                        # Insert into images table
                        db.execute('''
                            INSERT INTO images (post_id, filename, url, upload_date, extracted_date)
                            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                        ''', (post['id'], filename, img_url, upload_date))
        
        db.commit()

def init_db():
    with app.app_context():
        db = get_db()
        db.execute('''CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            image_filename TEXT,
            video_filename TEXT,
            author_id INTEGER,
            created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (author_id) REFERENCES users (id)
        )''')
        
        # Add author_id to existing posts table if it doesn't exist
        try:
            db.execute('ALTER TABLE posts ADD COLUMN author_id INTEGER')
        except sqlite3.OperationalError:
            # Column already exists
            pass
        
        # Add users table with admin flag
        db.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            magic_token TEXT UNIQUE NOT NULL,
            is_admin INTEGER DEFAULT 0,
            last_login TIMESTAMP,
            created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        # Add last_login to existing users table if it doesn't exist
        try:
            db.execute('ALTER TABLE users ADD COLUMN last_login TIMESTAMP')
        except sqlite3.OperationalError:
            # Column already exists
            pass
        
        # Add comments table
        db.execute('''CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            parent_comment_id INTEGER,
            created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (post_id) REFERENCES posts (id),
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (parent_comment_id) REFERENCES comments (id)
        )''')
        
        # Add parent_comment_id to existing comments table if it doesn't exist
        try:
            db.execute('ALTER TABLE comments ADD COLUMN parent_comment_id INTEGER')
        except sqlite3.OperationalError:
            # Column already exists
            pass
        
        # Add reactions table for hearts
        db.execute('''CREATE TABLE IF NOT EXISTS reactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            reaction_type TEXT NOT NULL DEFAULT 'heart',
            created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (post_id) REFERENCES posts (id),
            FOREIGN KEY (user_id) REFERENCES users (id),
            UNIQUE(post_id, user_id, reaction_type)
        )''')
        
        # Add images table for extracted images
        db.execute('''CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            url TEXT NOT NULL,
            upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            extracted_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (post_id) REFERENCES posts (id)
        )''')
        
        # Add admin flag to existing users table if it doesn't exist
        try:
            db.execute('ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0')
        except sqlite3.OperationalError:
            # Column already exists
            pass
        
        db.commit()
        
        # Extract images from existing posts and populate images table
        extract_images_from_posts()

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/create-post', methods=['GET', 'POST'])
@app.route('/create-post/<magic_token>', methods=['GET', 'POST'])
def create_post(magic_token=None):
    # Clear any stale flash messages that aren't relevant to post creation
    from flask import session
    if '_flashes' in session:
        # Get existing messages
        existing_messages = session['_flashes']
        # Filter out comment-related messages that shouldn't appear on create post page
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
        
        # Update last login time
        db.execute('UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?', (user['id'],))
        db.commit()
    
    if request.method == 'POST':
        title = request.form['title']
        content = request.form['content']

        db = get_db()
        author_id = user['id'] if user else None
        db.execute(
            "INSERT INTO posts (title, content, author_id) VALUES (?, ?, ?)",
            (title, content, author_id)
        )
        db.commit()
        flash("Post created!", "success")
        if magic_token:
            return redirect(url_for('create_post', magic_token=magic_token))
        return redirect(url_for('create_post'))    
    return render_template('create_post.html', user=user)

@app.route('/upload-media', methods=['POST'])
def upload_media():
    """Handle direct file uploads from TinyMCE"""
    file = request.files.get('file')
    if not file:
        return jsonify(error='No file'), 400
    
    ext = file.filename.rsplit('.', 1)[-1].lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return jsonify(error='Invalid file type'), 400
    
    filename = f"img_{uuid.uuid4().hex}.{ext}"
    path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(path)
    url = url_for('uploaded_file', filename=filename, _external=True)
    return jsonify(location=url)

@app.route('/upload-multiple-images', methods=['POST'])
def upload_multiple_images():
    """Handle multiple image uploads"""
    try:
        # Debug: Print what we received
        print("Files received:", request.files)
        print("Form data:", request.form)
        
        files = request.files.getlist('images')
        if not files or all(f.filename == '' for f in files):
            return jsonify({'error': 'No files provided'}), 400
        
        uploaded_images = []
        
        for file in files:
            if file and file.filename and file.filename != '':
                print(f"Processing file: {file.filename}")
                
                # Check file extension
                if '.' not in file.filename:
                    print(f"Skipping file with no extension: {file.filename}")
                    continue
                    
                ext = file.filename.rsplit('.', 1)[-1].lower()
                if ext not in ALLOWED_IMAGE_EXTENSIONS:
                    print(f"Skipping invalid extension: {ext}")
                    continue
                
                try:
                    # Generate unique filename
                    unique_filename = f"img_{uuid.uuid4().hex}.{ext}"
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                    
                    # Save the file
                    file.save(file_path)
                    print(f"Saved file: {file_path}")
                    
                    # Generate URL
                    file_url = url_for('uploaded_file', filename=unique_filename, _external=True)
                    
                    uploaded_images.append({
                        'filename': unique_filename,
                        'original_name': file.filename,
                        'url': file_url
                    })
                    
                except Exception as file_error:
                    print(f"Error saving file {file.filename}: {str(file_error)}")
                    continue
        
        print(f"Successfully uploaded {len(uploaded_images)} images")
        
        return jsonify({
            'success': True,
            'images': uploaded_images,
            'count': len(uploaded_images)
        })
        
    except Exception as e:
        print(f"Upload error: {str(e)}")
        import traceback
        traceback.print_exc()
        
        return jsonify({'error': f'Upload failed: {str(e)}'}), 500

@app.route('/upload-multiple-media', methods=['POST'])
def upload_multiple_media():
    """Handle multiple image and video uploads"""
    try:
        print("Files received:", request.files)
        print("Form data:", request.form)
        
        files = request.files.getlist('media')
        if not files or all(f.filename == '' for f in files):
            return jsonify({'error': 'No files provided'}), 400
        
        uploaded_media = []
        
        for file in files:
            if file and file.filename and file.filename != '':
                print(f"Processing file: {file.filename}")
                
                # Check file extension
                if '.' not in file.filename:
                    print(f"Skipping file with no extension: {file.filename}")
                    continue
                    
                ext = file.filename.rsplit('.', 1)[-1].lower()
                
                # Check if it's an allowed image or video
                is_image = ext in ALLOWED_IMAGE_EXTENSIONS
                is_video = ext in ALLOWED_VIDEO_EXTENSIONS
                
                if not (is_image or is_video):
                    print(f"Skipping invalid extension: {ext}")
                    continue
                
                try:
                    # Generate unique filename
                    if is_image:
                        unique_filename = f"img_{uuid.uuid4().hex}.{ext}"
                        media_type = 'image'
                    else:
                        unique_filename = f"vid_{uuid.uuid4().hex}.{ext}"
                        media_type = 'video'
                    
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                    
                    # Save the file
                    file.save(file_path)
                    print(f"Saved {media_type}: {file_path}")
                    
                    # Generate URL
                    file_url = url_for('uploaded_file', filename=unique_filename, _external=True)
                    
                    uploaded_media.append({
                        'filename': unique_filename,
                        'original_name': file.filename,
                        'url': file_url,
                        'type': media_type,
                        'extension': ext
                    })
                    
                except Exception as file_error:
                    print(f"Error saving file {file.filename}: {str(file_error)}")
                    continue
        
        print(f"Successfully uploaded {len(uploaded_media)} media files")
        
        return jsonify({
            'success': True,
            'media': uploaded_media,
            'count': len(uploaded_media)
        })
        
    except Exception as e:
        print(f"Upload error: {str(e)}")
        import traceback
        traceback.print_exc()
        
        return jsonify({'error': f'Upload failed: {str(e)}'}), 500

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# User management page
@app.route('/admin/users', methods=['GET', 'POST'])
def manage_users():
    db = get_db()
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        is_admin = 1 if request.form.get('is_admin') else 0
        magic_token = uuid.uuid4().hex
        try:
            db.execute('INSERT INTO users (name, email, magic_token, is_admin) VALUES (?, ?, ?, ?)', (name, email, magic_token, is_admin))
            db.commit()
            flash('User added!', 'success')
        except sqlite3.IntegrityError:
            flash('Email already exists!', 'danger')
        return redirect(url_for('manage_users'))

    users = db.execute('SELECT * FROM users').fetchall()
    return render_template('manage_users.html', users=users)

# Remove user
@app.route('/admin/users/remove/<int:user_id>', methods=['POST'])
def remove_user(user_id):
    db = get_db()
    db.execute('DELETE FROM users WHERE id = ?', (user_id,))
    db.commit()
    flash('User removed.', 'info')
    return redirect(url_for('manage_users'))

# Toggle admin status
@app.route('/admin/users/toggle-admin/<int:user_id>', methods=['POST'])
def toggle_admin_status(user_id):
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    new_admin_status = 1 if not user['is_admin'] else 0
    db.execute('UPDATE users SET is_admin = ? WHERE id = ?', (new_admin_status, user_id))
    db.commit()
    
    return jsonify({
        'success': True,
        'is_admin': bool(new_admin_status),
        'user_name': user['name']
    })

# Posts feed with magic link
@app.route('/posts/<magic_token>')
@app.route('/posts/<magic_token>/<year_month>')
@app.route('/posts/<magic_token>/show/<show_type>')
def posts(magic_token, year_month=None, show_type=None):
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE magic_token = ?', (magic_token,)).fetchone()
    if not user:
        abort(403)
    
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
    
    return render_template('posts.html', posts=posts, user=user, 
                         available_months=available_months, current_month=year_month,
                         comments_by_post=comments_by_post, reactions_by_post=reactions_by_post,
                         user_reactions=user_reactions, heart_users_by_post=heart_users_by_post,
                         last_login=last_login, current_view=current_view)

@app.route('/add-comment/<magic_token>', methods=['POST'])
def add_comment(magic_token):
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE magic_token = ?', (magic_token,)).fetchone()
    if not user:
        abort(403)
    
    post_id = request.form.get('post_id')
    content = request.form.get('content')
    parent_comment_id = request.form.get('parent_comment_id')
    
    if not post_id or not content:
        flash('Missing post ID or comment content', 'danger')
        return redirect(url_for('posts', magic_token=magic_token))
    
    # If this is a reply, verify permissions and parent comment
    if parent_comment_id:
        # Verify the parent comment exists and belongs to this post
        parent_comment = db.execute(
            'SELECT c.*, u.is_admin as parent_is_admin FROM comments c JOIN users u ON c.user_id = u.id WHERE c.id = ? AND c.post_id = ?', 
            (parent_comment_id, post_id)
        ).fetchone()
        if not parent_comment:
            flash('Invalid parent comment', 'danger')
            return redirect(url_for('posts', magic_token=magic_token))
        
        # Check reply permissions: 
        # - Admins can reply to any comment
        # - Users can reply to admin comments if the thread involves them
        if not user['is_admin']:
            # Find the root comment of this thread
            root_comment_id = parent_comment_id
            if parent_comment['parent_comment_id']:
                root_comment_id = parent_comment['parent_comment_id']
            
            # Check if user is involved in this thread (owns root comment or has replied)
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
    
    if parent_comment_id:
        flash('Reply added successfully!', 'success')
    else:
        flash('Comment added successfully!', 'success')
    
    # Redirect to the specific posts page to ensure flash messages appear there
    return redirect(url_for('posts', magic_token=magic_token))

@app.route('/delete-post/<magic_token>/<int:post_id>', methods=['POST'])
def delete_post(magic_token, post_id):
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
        
        flash('Post deleted successfully!', 'success')
    else:
        flash('Post not found!', 'danger')
    
    return redirect(url_for('posts', magic_token=magic_token))

@app.route('/photos/<magic_token>')
@app.route('/photos/<magic_token>/<sort_order>')
@app.route('/photos/<magic_token>/<sort_order>/<int:offset>')
def photo_stream(magic_token, sort_order='recent', offset=0):
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

@app.route('/toggle-heart/<magic_token>', methods=['POST'])
def toggle_heart(magic_token):
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE magic_token = ?', (magic_token,)).fetchone()
    if not user:
        abort(403)
    
    post_id = request.form.get('post_id')
    if not post_id:
        return jsonify({'error': 'Missing post ID'}), 400
    
    # Check if user already hearted this post
    existing_reaction = db.execute(
        'SELECT * FROM reactions WHERE post_id = ? AND user_id = ? AND reaction_type = ?',
        (post_id, user['id'], 'heart')
    ).fetchone()
    
    if existing_reaction:
        # Remove heart
        db.execute('DELETE FROM reactions WHERE id = ?', (existing_reaction['id'],))
        hearted = False
    else:
        # Add heart
        db.execute('INSERT INTO reactions (post_id, user_id, reaction_type) VALUES (?, ?, ?)',
                   (post_id, user['id'], 'heart'))
        hearted = True
    
    db.commit()
    
    # Get updated count
    heart_count = db.execute(
        'SELECT COUNT(*) as count FROM reactions WHERE post_id = ? AND reaction_type = ?',
        (post_id, 'heart')
    ).fetchone()['count']
    
    return jsonify({
        'hearted': hearted,
        'count': heart_count
    })

# Remove the old /posts endpoint if it exists, or make it forbidden
@app.route('/posts')
def posts_no_token():
    abort(403)

# Google Photos Picker API (2024) - Server-side implementation
@app.route('/api/google-photos/create-session', methods=['POST'])
def create_picker_session_endpoint():
    """Create a Google Photos Picker session"""
    try:
        # Use the updated create_picker_session function
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
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/google-photos/poll-session/<session_id>', methods=['GET'])
def poll_picker_session_endpoint(session_id):
    """Poll a Google Photos Picker session for completion"""
    try:
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
                
                # Extract the picked media items (API returns 'mediaItems' not 'pickedMediaItems')
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
            # Still in progress - mediaItemsSet is False
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

@app.route('/api/google-photos/download-selected', methods=['POST'])
def download_selected_photos():
    """Download and process selected photos from Google Photos Picker"""
    try:
        data = request.get_json()
        selected_items = data.get('selectedItems', [])
        
        if not selected_items:
            return jsonify({'success': False, 'error': 'No photos provided'}), 400
        
        imported_media = []
        total_original_size = 0
        total_processed_size = 0
        
        for item in selected_items:
            try:
                # Handle PickedMediaItem structure from Picker API
                media_file = item.get('mediaFile', {})
                base_url = media_file.get('baseUrl')
                filename = media_file.get('filename', f'google_photo_{uuid.uuid4().hex[:8]}.jpg')
                mime_type = media_file.get('mimeType', 'image/jpeg')
                
                if not base_url:
                    continue
                
                # Download the media file with authorization
                # The Picker API baseUrls need authorization headers
                from google_photos import get_authenticated_service
                try:
                    service = get_authenticated_service()
                    if hasattr(service, '_http') and hasattr(service._http, 'credentials'):
                        creds = service._http.credentials
                        headers = {'Authorization': f'Bearer {creds.token}'}
                    else:
                        # Fallback - try without auth first
                        headers = {}
                except:
                    headers = {}
                
                download_url = f"{base_url}=d"  # Download original quality
                response = requests.get(download_url, headers=headers)
                
                if response.status_code == 200:
                    total_original_size += len(response.content)
                    
                    # Determine file extension and type
                    if mime_type.startswith('image/'):
                        if 'jpeg' in mime_type or 'jpg' in mime_type:
                            ext = 'jpg'
                        elif 'png' in mime_type:
                            ext = 'png'
                        elif 'gif' in mime_type:
                            ext = 'gif'
                        elif 'webp' in mime_type:
                            ext = 'webp'
                        else:
                            ext = 'jpg'
                        
                        prefix = 'img'
                        media_type = 'image'
                    elif mime_type.startswith('video/'):
                        if 'mp4' in mime_type:
                            ext = 'mp4'
                        elif 'mov' in mime_type:
                            ext = 'mov'
                        elif 'webm' in mime_type:
                            ext = 'webm'
                        else:
                            ext = 'mp4'
                        
                        prefix = 'vid'
                        media_type = 'video'
                    else:
                        ext = 'jpg'
                        prefix = 'img'
                        media_type = 'image'
                    
                    # Generate unique filename
                    unique_filename = f"{prefix}_{uuid.uuid4().hex}.{ext}"
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                    
                    # Process and save the file
                    processed_content = response.content
                    
                    # For images, try to optimize with Pillow if available
                    if media_type == 'image' and ext in ['jpg', 'jpeg', 'png', 'webp']:
                        try:
                            from PIL import Image
                            import io
                            
                            image = Image.open(io.BytesIO(response.content))
                            
                            # Convert to RGB if necessary
                            if image.mode in ('RGBA', 'LA', 'P') and ext.lower() in ['jpg', 'jpeg']:
                                image = image.convert('RGB')
                            
                            # Resize if too large
                            max_dimension = 2048
                            if max(image.size) > max_dimension:
                                image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
                            
                            # Save with optimization
                            output = io.BytesIO()
                            if ext.lower() in ['jpg', 'jpeg']:
                                image.save(output, format='JPEG', quality=85, optimize=True)
                            elif ext.lower() == 'png':
                                image.save(output, format='PNG', optimize=True)
                            elif ext.lower() == 'webp':
                                image.save(output, format='WebP', quality=85, optimize=True)
                            else:
                                image.save(output, format='JPEG', quality=85, optimize=True)
                            
                            processed_content = output.getvalue()
                            
                        except ImportError:
                            # PIL not available, use original
                            pass
                        except Exception as resize_error:
                            print(f"Error optimizing image: {resize_error}")
                            # Use original if optimization fails
                            pass
                    
                    total_processed_size += len(processed_content)
                    
                    # Save the file
                    with open(file_path, 'wb') as f:
                        f.write(processed_content)
                    
                    # Generate URL
                    file_url = url_for('uploaded_file', filename=unique_filename, _external=True)
                    
                    imported_media.append({
                        'filename': unique_filename,
                        'original_name': filename,
                        'url': file_url,
                        'type': media_type,
                        'extension': ext,
                        'google_photo_id': item.get('id', media_file.get('id', 'unknown'))
                    })
                    
                    print(f"Successfully imported {media_type}: {unique_filename}")
                    
            except Exception as item_error:
                print(f"Error processing item: {str(item_error)}")
                continue
        
        return jsonify({
            'success': True,
            'media': imported_media,
            'count': len(imported_media),
            'totalOriginalSize': total_original_size,
            'totalProcessedSize': total_processed_size
        })
        
    except Exception as e:
        print(f"Error downloading selected photos: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/test-polling')
def test_polling():
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

if __name__ == "__main__":
    init_db()
    app.run(debug=True)