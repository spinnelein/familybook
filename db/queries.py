"""
Database query operations for the Familybook application.

This module contains all functions that perform SELECT, INSERT, UPDATE, DELETE
operations on the SQLite database.
"""

import sqlite3
from flask import request, current_app
from .database import get_db
from utils.timezone_utils import get_pacific_now


# Settings Operations
def get_setting(key, default=None):
    """Get a setting value from the database"""
    with current_app.app_context():
        db = get_db()
        result = db.execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
        return result['value'] if result else default


def update_setting(key, value):
    """Update a setting value in the database"""
    with current_app.app_context():
        db = get_db()
        db.execute('UPDATE settings SET value = ?, updated = CURRENT_TIMESTAMP WHERE key = ?', (value, key))
        db.commit()


# Activity Logging
def log_activity(action_type, user_id=None, user_name=None, post_id=None, post_title=None, comment_text=None):
    """Log user activity to the activity_log table"""
    try:
        # Get user info from magic token if not provided
        if not user_id and not user_name:
            magic_token = request.args.get('magic_token')
            if magic_token:
                db = get_db()
                user = db.execute('SELECT id, name FROM users WHERE magic_token = ?', (magic_token,)).fetchone()
                if user:
                    user_id = user['id']
                    user_name = user['name']
        
        # Get IP and user agent
        ip_address = request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR', 'Unknown'))
        user_agent = request.environ.get('HTTP_USER_AGENT', '')[:500]  # Limit length
        
        # Insert activity log with Pacific Time
        db = get_db()
        db.execute('''INSERT INTO activity_log 
                     (user_id, user_name, action_type, post_id, post_title, comment_text, ip_address, user_agent, created)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                   (user_id, user_name, action_type, post_id, post_title, comment_text, ip_address, user_agent, get_pacific_now()))
        db.commit()
        
    except Exception as e:
        print(f"Error logging activity: {e}")


# Email Logging
def log_email(recipient_email, template_name=None, subject=None, status='pending', error_message=None, user_id=None):
    """Log email sending attempts to the database"""
    try:
        db = get_db()
        db.execute('''INSERT INTO email_logs 
                     (recipient_email, template_name, subject, status, error_message, user_id, sent_at)
                     VALUES (?, ?, ?, ?, ?, ?, ?)''',
                  (recipient_email, template_name, subject, status, error_message, user_id, get_pacific_now()))
        db.commit()
        return db.lastrowid
    except Exception as e:
        print(f"Failed to log email: {e}")
        return None


def update_email_log(log_id, status, error_message=None):
    """Update the status of an email log entry"""
    try:
        db = get_db()
        db.execute('UPDATE email_logs SET status = ?, error_message = ? WHERE id = ?',
                  (status, error_message, log_id))
        db.commit()
    except Exception as e:
        print(f"Failed to update email log: {e}")


# User Operations
def get_user_by_magic_token(magic_token):
    """Get user by magic token"""
    db = get_db()
    return db.execute('SELECT * FROM users WHERE magic_token = ?', (magic_token,)).fetchone()


def get_user_by_id(user_id):
    """Get user by ID"""
    db = get_db()
    return db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()


def get_all_users():
    """Get all users"""
    db = get_db()
    return db.execute('SELECT * FROM users').fetchall()


def get_users_with_emails():
    """Get all users that have email addresses"""
    db = get_db()
    return db.execute('SELECT id FROM users WHERE email != ""').fetchall()


def create_user(name, email, magic_token, email_notifications='all'):
    """Create a new user and return the user ID"""
    db = get_db()
    cursor = db.execute('INSERT INTO users (name, email, magic_token, email_notifications) VALUES (?, ?, ?, ?)', 
                       (name, email, magic_token, email_notifications))
    user_id = cursor.lastrowid
    db.commit()
    return user_id


def delete_user(user_id):
    """Delete a user by ID"""
    db = get_db()
    db.execute('DELETE FROM users WHERE id = ?', (user_id,))
    db.commit()


def toggle_user_admin(user_id):
    """Toggle user admin status and return new status"""
    db = get_db()
    user = db.execute('SELECT is_admin FROM users WHERE id = ?', (user_id,)).fetchone()
    if not user:
        return None
    
    new_admin_status = 1 if not user['is_admin'] else 0
    db.execute('UPDATE users SET is_admin = ? WHERE id = ?', (new_admin_status, user_id))
    db.commit()
    return bool(new_admin_status)


def update_user_email_notifications(user_id, email_notifications):
    """Update user email notification preferences"""
    db = get_db()
    db.execute('UPDATE users SET email_notifications = ? WHERE id = ?', (email_notifications, user_id))
    db.commit()


def update_user_last_login(user_id, login_time=None):
    """Update user's last login time"""
    if login_time is None:
        login_time = get_pacific_now()
    db = get_db()
    db.execute('UPDATE users SET last_login = ? WHERE id = ?', (login_time, user_id))
    db.commit()


# Post Operations
def create_post(title, content, author_id, tags=None):
    """Create a new post and return the post ID"""
    db = get_db()
    cursor = db.execute(
        "INSERT INTO posts (title, content, author_id, tags, created) VALUES (?, ?, ?, ?, ?)",
        (title, content, author_id, tags, get_pacific_now())
    )
    post_id = cursor.lastrowid
    db.commit()
    return post_id


def get_posts_by_date_range(year_month):
    """Get posts for a specific month (format: YYYY-MM)"""
    db = get_db()
    return db.execute('''
        SELECT p.*, u.name as author_name 
        FROM posts p 
        LEFT JOIN users u ON p.author_id = u.id 
        WHERE strftime('%Y-%m', p.created) = ?
        ORDER BY p.created DESC
    ''', (year_month,)).fetchall()


def get_posts_by_tag(tag_filter):
    """Get posts filtered by tag"""
    db = get_db()
    return db.execute('''
        SELECT p.*, u.name as author_name 
        FROM posts p 
        LEFT JOIN users u ON p.author_id = u.id 
        WHERE p.tags = ? OR p.tags LIKE ? OR p.tags LIKE ? OR p.tags LIKE ?
        ORDER BY p.created DESC
    ''', (tag_filter, f'{tag_filter},%', f'%,{tag_filter},%', f'%,{tag_filter}')).fetchall()


def get_all_posts():
    """Get all posts with author information"""
    db = get_db()
    return db.execute('''
        SELECT p.*, u.name as author_name 
        FROM posts p 
        LEFT JOIN users u ON p.author_id = u.id 
        ORDER BY p.created DESC
    ''').fetchall()


def get_post_by_id(post_id):
    """Get a specific post by ID"""
    db = get_db()
    return db.execute('SELECT title FROM posts WHERE id = ?', (post_id,)).fetchone()


def delete_post(post_id):
    """Delete a post and all related data"""
    db = get_db()
    # Delete related data first
    db.execute('DELETE FROM images WHERE post_id = ?', (post_id,))
    db.execute('DELETE FROM comments WHERE post_id = ?', (post_id,))
    db.execute('DELETE FROM reactions WHERE post_id = ?', (post_id,))
    # Delete the post
    db.execute('DELETE FROM posts WHERE id = ?', (post_id,))
    db.commit()


# Comment Operations
def create_comment(post_id, user_id, content, parent_comment_id=None):
    """Create a new comment"""
    db = get_db()
    db.execute('INSERT INTO comments (post_id, user_id, content, parent_comment_id) VALUES (?, ?, ?, ?)',
               (post_id, user_id, content, parent_comment_id))
    db.commit()


def get_comments_for_post(post_id):
    """Get all comments for a specific post"""
    db = get_db()
    return db.execute('''
        SELECT c.*, u.name as user_name 
        FROM comments c 
        JOIN users u ON c.user_id = u.id 
        WHERE c.post_id = ? 
        ORDER BY c.created ASC
    ''', (post_id,)).fetchall()


# Reaction Operations
def get_reaction_count(post_id, reaction_type='heart'):
    """Get reaction count for a post"""
    db = get_db()
    result = db.execute(
        'SELECT COUNT(*) as count FROM reactions WHERE post_id = ? AND reaction_type = ?',
        (post_id, reaction_type)
    ).fetchone()
    return result['count'] if result else 0


def check_user_reaction(post_id, user_id, reaction_type='heart'):
    """Check if user has reacted to a post"""
    db = get_db()
    result = db.execute(
        'SELECT id FROM reactions WHERE post_id = ? AND user_id = ? AND reaction_type = ?',
        (post_id, user_id, reaction_type)
    ).fetchone()
    return result is not None


def toggle_reaction(post_id, user_id, reaction_type='heart'):
    """Toggle user reaction on a post. Returns (reaction_count, user_hearted)"""
    db = get_db()
    
    # Check if user already hearted this post
    existing = db.execute(
        'SELECT id FROM reactions WHERE post_id = ? AND user_id = ? AND reaction_type = ?',
        (post_id, user_id, reaction_type)
    ).fetchone()
    
    hearted = False
    if existing:
        # Remove the reaction
        db.execute('DELETE FROM reactions WHERE id = ?', (existing['id'],))
    else:
        # Add the reaction
        db.execute(
            'INSERT INTO reactions (post_id, user_id, reaction_type) VALUES (?, ?, ?)',
            (post_id, user_id, reaction_type)
        )
        hearted = True
    
    db.commit()
    
    # Get updated count
    count = db.execute(
        'SELECT COUNT(*) as count FROM reactions WHERE post_id = ? AND reaction_type = ?',
        (post_id, reaction_type)
    ).fetchone()['count']
    
    return count, hearted


# Filter Tags Operations
def get_all_filter_tags():
    """Get all filter tags"""
    db = get_db()
    return db.execute('SELECT * FROM filter_tags ORDER BY name').fetchall()


def get_filter_tag_names():
    """Get just the names of filter tags"""
    db = get_db()
    return db.execute('SELECT name FROM filter_tags ORDER BY name').fetchall()


def create_filter_tag(name, display_name, color):
    """Create a new filter tag"""
    db = get_db()
    db.execute('INSERT INTO filter_tags (name, display_name, color) VALUES (?, ?, ?)',
              (name, display_name, color))
    db.commit()


def delete_filter_tag(tag_id):
    """Delete a filter tag"""
    db = get_db()
    db.execute('DELETE FROM filter_tags WHERE id = ?', (tag_id,))
    db.commit()


# Settings and Configuration Operations  
def get_all_settings():
    """Get all settings as a dictionary"""
    db = get_db()
    settings_rows = db.execute('SELECT key, value, description FROM settings').fetchall()
    return {row['key']: {'value': row['value'], 'description': row['description']} for row in settings_rows}


def get_admin_oauth_token():
    """Get the admin OAuth token from session"""
    from flask import session
    admin_user_id = session.get('admin_user_id')
    if not admin_user_id:
        return None
    
    db = get_db()
    admin_user = db.execute('SELECT * FROM users WHERE id = ? AND is_admin = 1', (admin_user_id,)).fetchone()
    
    if not admin_user:
        session.pop('admin_user_id', None)
        return None
    
    return session.get('admin_oauth_token')


# Email Template Operations
def get_email_template(template_name):
    """Get email template by name"""
    db = get_db()
    return db.execute('SELECT * FROM email_templates WHERE template_name = ? AND is_active = 1',
                     (template_name,)).fetchone()


def get_all_email_templates():
    """Get all email templates"""
    db = get_db()
    return db.execute('SELECT * FROM email_templates ORDER BY template_name').fetchall()


def get_email_template_by_id(template_id):
    """Get email template by ID"""
    db = get_db()
    return db.execute('SELECT * FROM email_templates WHERE id = ?', (template_id,)).fetchone()


def update_email_template(template_id, display_name, description, subject_template, 
                         html_template, plain_template, variables, is_active):
    """Update an email template"""
    db = get_db()
    db.execute('''UPDATE email_templates 
                 SET display_name = ?, description = ?, subject_template = ?, 
                     html_template = ?, plain_template = ?, variables = ?, 
                     is_active = ?, updated = CURRENT_TIMESTAMP 
                 WHERE id = ?''',
              (display_name, description, subject_template, html_template, 
               plain_template, variables, is_active, template_id))
    db.commit()


def create_default_email_templates(templates_data):
    """Create multiple email templates from template data"""
    db = get_db()
    created_count = 0
    
    for template in templates_data:
        existing = db.execute('SELECT id FROM email_templates WHERE template_name = ?',
                             (template['template_name'],)).fetchone()
        if not existing:
            db.execute('''INSERT INTO email_templates 
                         (template_name, display_name, description, subject_template, 
                          html_template, plain_template, variables)
                         VALUES (?, ?, ?, ?, ?, ?, ?)''',
                      (template['template_name'], template['display_name'], 
                       template['description'], template['subject_template'],
                       template['html_template'], template['plain_template'], 
                       template['variables']))
            created_count += 1
    
    db.commit()
    return created_count


# User Notification Preferences
def get_user_notification_preferences(user_id):
    """Get user notification preferences"""
    db = get_db()
    try:
        prefs = db.execute('SELECT * FROM user_notification_preferences WHERE user_id = ?', 
                          (user_id,)).fetchone()
        return prefs
    except sqlite3.OperationalError:
        # Table might not exist, try to create it
        try:
            db.execute('''CREATE TABLE IF NOT EXISTS user_notification_preferences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                account_created INTEGER DEFAULT 1,
                new_post INTEGER DEFAULT 1,
                major_event INTEGER DEFAULT 1,
                comment_reply INTEGER DEFAULT 1,
                updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )''')
            db.commit()
            return None
        except Exception as create_error:
            print(f"Error creating table: {create_error}")
            raise


def create_default_user_notification_preferences(user_id):
    """Create default notification preferences for a user"""
    db = get_db()
    db.execute('''INSERT INTO user_notification_preferences 
                 (user_id, account_created, new_post, major_event, comment_reply)
                 VALUES (?, 1, 1, 1, 1)''', (user_id,))
    db.commit()
    return db.execute('SELECT * FROM user_notification_preferences WHERE user_id = ?', 
                     (user_id,)).fetchone()


def update_user_notification_preferences(user_id, new_post, major_event, comment_reply):
    """Update user notification preferences"""
    db = get_db()
    db.execute('''UPDATE user_notification_preferences 
                 SET new_post = ?, major_event = ?, comment_reply = ?
                 WHERE user_id = ?''',
               (new_post, major_event, comment_reply, user_id))
    db.commit()


# Image Operations
def get_individual_images(limit=50, sort_order='newest'):
    """Get individual images from the images table"""
    db = get_db()
    
    if sort_order == 'oldest':
        order_clause = 'ORDER BY i.extracted_date ASC'
    else:
        order_clause = 'ORDER BY i.extracted_date DESC'
    
    query = f'''
        SELECT i.*, p.title as post_title, p.created as post_date, u.name as author_name
        FROM images i 
        JOIN posts p ON i.post_id = p.id 
        LEFT JOIN users u ON p.author_id = u.id 
        {order_clause}
        LIMIT ?
    '''
    
    return db.execute(query, (limit,)).fetchall()


def update_settings_batch(settings_data):
    """Update multiple settings at once"""
    db = get_db()
    for setting_key, value in settings_data.items():
        # Handle boolean settings
        if setting_key in ['smtp_use_tls', 'notifications_enabled']:
            value = 'true' if value else 'false'
        
        db.execute('UPDATE settings SET value = ?, updated = CURRENT_TIMESTAMP WHERE key = ?',
                  (value, setting_key))
    
    db.commit()


# Activity Log Operations
def get_activity_logs(limit=100):
    """Get activity logs"""
    db = get_db()
    return db.execute('''
        SELECT al.*, p.title as post_title 
        FROM activity_log al 
        LEFT JOIN posts p ON al.post_id = p.id 
        ORDER BY al.created DESC 
        LIMIT ?
    ''', (limit,)).fetchall()


# Email Log Operations  
def get_email_logs(limit=100):
    """Get email logs"""
    db = get_db()
    return db.execute('''
        SELECT el.*, u.name as user_name 
        FROM email_logs el 
        LEFT JOIN users u ON el.user_id = u.id 
        ORDER BY el.sent_at DESC 
        LIMIT ?
    ''', (limit,)).fetchall()


def get_email_logs_stats():
    """Get email log statistics"""
    db = get_db()
    
    total_emails = db.execute('SELECT COUNT(*) as count FROM email_logs').fetchone()
    
    successful_emails = db.execute(
        'SELECT COUNT(*) as count FROM email_logs WHERE status = ?', ('sent',)
    ).fetchone()
    
    failed_emails = db.execute('''
        SELECT COUNT(*) as count FROM email_logs 
        WHERE status IN ('failed', 'error')
    ''').fetchone()
    
    return {
        'total': total_emails['count'] if total_emails else 0,
        'successful': successful_emails['count'] if successful_emails else 0,
        'failed': failed_emails['count'] if failed_emails else 0
    }


# About Us Operations
def get_about_us_content():
    """Get the about us content"""
    import sqlite3
    conn = sqlite3.connect('familybook.db')
    cursor = conn.cursor()
    
    # Create about_us table if it doesn't exist
    cursor.execute('''CREATE TABLE IF NOT EXISTS about_us 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      content TEXT NOT NULL, 
                      updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    cursor.execute('SELECT content FROM about_us ORDER BY id DESC LIMIT 1')
    result = cursor.fetchone()
    conn.close()
    
    return result[0] if result else """
    <h2>Welcome to Our Family Book</h2>
    <p>This is where we share our memories, photos, and stay connected as a family.</p>
    <p>Use the admin panel to customize this page and add your own family story.</p>
    """


def update_about_us_content(content):
    """Update the about us content"""
    import sqlite3
    conn = sqlite3.connect('familybook.db')
    cursor = conn.cursor()
    
    # Create table if it doesn't exist
    cursor.execute('''CREATE TABLE IF NOT EXISTS about_us 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      content TEXT NOT NULL, 
                      updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    cursor.execute('INSERT INTO about_us (content) VALUES (?)', (content,))
    conn.commit()
    conn.close()