"""
Database connection management and initialization functions.

This module handles:
- Database connection management (get_db, close_db)
- Database initialization (init_db)
- OAuth initialization (init_oauth_on_import)
"""

import os
import sqlite3
from flask import g, current_app


def get_db():
    """Get database connection from Flask's application context."""
    if 'db' not in g:
        g.db = sqlite3.connect(current_app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(exception):
    """Close database connection."""
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    """Initialize database with all required tables and default data."""
    from utils.timezone_utils import get_pacific_now
    from services.media_service import extract_images_from_posts
    
    with current_app.app_context():
        db = get_db()
        
        # Create posts table
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
        
        # Add email notification preferences to users table
        try:
            db.execute('ALTER TABLE users ADD COLUMN email_notifications TEXT DEFAULT "all"')  # "all", "major", "none"
        except sqlite3.OperationalError:
            # Column already exists
            pass
        
        # Add tags column to posts table
        try:
            db.execute('ALTER TABLE posts ADD COLUMN tags TEXT')  # JSON string for multiple tags
        except sqlite3.OperationalError:
            # Column already exists
            pass
        
        # Add settings table for SMTP configuration
        db.execute('''CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE NOT NULL,
            value TEXT,
            description TEXT,
            created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        # Add email templates table
        db.execute('''CREATE TABLE IF NOT EXISTS email_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_name TEXT UNIQUE NOT NULL,
            display_name TEXT NOT NULL,
            description TEXT,
            subject_template TEXT NOT NULL,
            html_template TEXT NOT NULL,
            plain_template TEXT NOT NULL,
            variables TEXT,
            is_active INTEGER DEFAULT 1,
            created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        # Add user notification preferences table for granular control
        db.execute('''CREATE TABLE IF NOT EXISTS user_notification_preferences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            account_created INTEGER DEFAULT 1,
            new_post INTEGER DEFAULT 1,
            major_event INTEGER DEFAULT 1,
            comment_reply INTEGER DEFAULT 1,
            magic_link_reminder INTEGER DEFAULT 1,
            created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            UNIQUE(user_id)
        )''')
        
        # Insert default SMTP settings if they don't exist
        default_settings = [
            ('smtp_server', '', 'SMTP server hostname (e.g., smtp.gmail.com)'),
            ('smtp_port', '587', 'SMTP server port (587 for TLS, 465 for SSL)'),
            ('smtp_username', '', 'SMTP username/email address'),
            ('smtp_password', '', 'SMTP password or app password'),
            ('smtp_use_tls', 'true', 'Use TLS encryption (true/false)'),
            ('email_from_name', 'Slugranch Familybook', 'Display name for sent emails'),
            ('email_from_address', '', 'From email address'),
            ('notifications_enabled', 'false', 'Enable email notifications (true/false)'),
            ('family_name', 'Slugranch', 'Family name used in email templates'),
            ('oauth_client_id', '', 'Google OAuth Client ID'),
            ('oauth_client_secret', '', 'Google OAuth Client Secret'),
            ('oauth_redirect_uri', '', 'OAuth redirect URI (e.g., http://localhost:5000/admin/oauth/callback)')
        ]
        
        for key, default_value, description in default_settings:
            existing = db.execute('SELECT id FROM settings WHERE key = ?', (key,)).fetchone()
            if not existing:
                db.execute('INSERT INTO settings (key, value, description) VALUES (?, ?, ?)',
                          (key, default_value, description))
        
        # Insert default email templates if they don't exist
        default_templates = [
            ('account_created', 'Welcome to Familybook', 'Welcome email sent when a new user account is created',
             'Welcome to {{family_name}} Familybook!',
             '''<html><body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; text-align: center; color: white;">
                    <h1 style="margin: 0;">🏠 {{family_name}} Familybook</h1>
                    <p style="margin: 5px 0 0 0;">Welcome to the Family!</p>
                </div>
                <div style="padding: 20px; background: #f9f9f9;">
                    <h2 style="color: #333; margin-top: 0;">Hi {{user_name}}!</h2>
                    <p style="color: #666; line-height: 1.6;">You've been invited to join the {{family_name}} family photo book! This is a private space where we share memories, photos, and stay connected.</p>
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="{{magic_link}}" style="background: #667eea; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block;">📖 Enter Familybook</a>
                    </div>
                    <div style="background: white; padding: 15px; border-left: 4px solid #667eea; margin: 20px 0; border-radius: 3px;">
                        <p style="margin: 0; color: #333; font-size: 14px;"><strong>🔗 Your Personal Link:</strong></p>
                        <p style="margin: 5px 0 0 0; color: #666; font-size: 14px;">{{magic_link}}</p>
                        <p style="margin: 10px 0 0 0; color: #666; font-size: 12px; font-style: italic;">Save this link somewhere safe - it's your key to the family memories!</p>
                    </div>
                    <p style="color: #666; font-size: 14px;">Bookmark this link - it's your personal gateway to stay connected with the family!</p>
                </div>
                <div style="padding: 20px; text-align: center; background: #e9ecef; color: #666; font-size: 12px;">
                    <p style="margin: 0;">© {{current_year}} {{family_name}} Familybook</p>
                </div>
            </body></html>''',
             '''Welcome to {{family_name}} Familybook!

Hi {{user_name}}!

You've been invited to join the {{family_name}} family photo book! This is a private space where we share memories, photos, and stay connected.

Your Personal Link: {{magic_link}}

Bookmark this link - it's your personal gateway to stay connected with the family!

© {{current_year}} {{family_name}} Familybook''',
             '{"user_name": "User\'s name", "magic_link": "User\'s magic link URL", "family_name": "Family name from settings", "current_year": "Current year"}'),

            ('new_post', 'New Post in Familybook', 'Notification sent when a new post is created',
             'New post: {{post_title}}',
             '''<html><body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background: linear-gradient(135deg, #28a745 0%, #20c997 100%); padding: 20px; text-align: center; color: white;">
                    <h1 style="margin: 0;">📝 New Post in {{family_name}} Familybook</h1>
                    <p style="margin: 5px 0 0 0;">{{post_title}}</p>
                </div>
                <div style="padding: 20px; background: #f9f9f9;">
                    <p style="color: #666; line-height: 1.6;">{{author_name}} just shared a new memory in the family book!</p>
                    <div style="background: white; padding: 15px; border-radius: 5px; margin: 20px 0; border: 1px solid #dee2e6;">
                        <h3 style="margin: 0 0 10px 0; color: #333;">{{post_title}}</h3>
                        <div style="color: #666; line-height: 1.6;">{{post_content}}</div>
                    </div>
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="{{magic_link}}" style="background: #28a745; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block;">📖 Read Full Post</a>
                    </div>
                </div>
                <div style="padding: 20px; text-align: center; background: #e9ecef; color: #666; font-size: 12px;">
                    <p style="margin: 0;">© {{current_year}} {{family_name}} Familybook</p>
                </div>
            </body></html>''',
             '''New post: {{post_title}}

{{author_name}} just shared a new memory in the family book!

{{post_title}}
{{post_content}}

Read the full post: {{magic_link}}

© {{current_year}} {{family_name}} Familybook''',
             '{"post_title": "Title of the new post", "post_content": "Post content preview", "author_name": "Name of post author", "magic_link": "User\'s magic link URL", "family_name": "Family name from settings", "current_year": "Current year"}'),

            ('comment_reply', 'Someone replied to your comment', 'Notification sent when someone replies to a user\'s comment',
             'Reply to your comment on "{{post_title}}"',
             '''<html><body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background: linear-gradient(135deg, #fd7e14 0%, #e83e8c 100%); padding: 20px; text-align: center; color: white;">
                    <h1 style="margin: 0;">💬 Reply to Your Comment</h1>
                    <p style="margin: 5px 0 0 0;">{{family_name}} Familybook</p>
                </div>
                <div style="padding: 20px; background: #f9f9f9;">
                    <p style="color: #666; line-height: 1.6;">{{reply_author}} replied to your comment on "{{post_title}}"</p>
                    <div style="background: white; padding: 15px; border-radius: 5px; margin: 20px 0; border: 1px solid #dee2e6;">
                        <p style="margin: 0 0 10px 0; color: #666; font-size: 14px;"><strong>Your comment:</strong></p>
                        <div style="background: #f8f9fa; padding: 10px; border-left: 3px solid #fd7e14; margin-bottom: 15px;">{{original_comment}}</div>
                        <p style="margin: 0 0 10px 0; color: #666; font-size: 14px;"><strong>{{reply_author}} replied:</strong></p>
                        <div style="background: #fff3cd; padding: 10px; border-left: 3px solid #e83e8c;">{{reply_content}}</div>
                    </div>
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="{{magic_link}}" style="background: #fd7e14; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block;">💬 View Conversation</a>
                    </div>
                </div>
                <div style="padding: 20px; text-align: center; background: #e9ecef; color: #666; font-size: 12px;">
                    <p style="margin: 0;">© {{current_year}} {{family_name}} Familybook</p>
                </div>
            </body></html>''',
             '''Reply to your comment on "{{post_title}}"

{{reply_author}} replied to your comment on "{{post_title}}"

Your comment:
{{original_comment}}

{{reply_author}} replied:
{{reply_content}}

View the conversation: {{magic_link}}

© {{current_year}} {{family_name}} Familybook''',
             '{"post_title": "Title of the post", "reply_author": "Name of person who replied", "reply_content": "Content of the reply", "original_comment": "User\'s original comment", "magic_link": "User\'s magic link URL", "family_name": "Family name from settings", "current_year": "Current year"}')
        ]
        
        for template_name, display_name, description, subject, html, plain, variables in default_templates:
            existing = db.execute('SELECT id FROM email_templates WHERE template_name = ?', (template_name,)).fetchone()
            if not existing:
                db.execute('''INSERT INTO email_templates 
                             (template_name, display_name, description, subject_template, html_template, plain_template, variables)
                             VALUES (?, ?, ?, ?, ?, ?, ?)''',
                          (template_name, display_name, description, subject, html, plain, variables))
        
        # Insert default filter tags if they don't exist
        default_tags = [
            ('photos', 'Photos', '#2196F3'),
            ('videos', 'Videos', '#FF5722'),
            ('memories', 'Memories', '#9C27B0'),
            ('family', 'Family', '#4CAF50'),
            ('events', 'Events', '#FF9800'),
            ('milestones', 'Milestones', '#F44336'),
            ('travel', 'Travel', '#00BCD4'),
            ('celebrations', 'Celebrations', '#FFEB3B'),
            ('updates', 'Updates', '#607D8B')
        ]
        
        for tag_name, display_name, color in default_tags:
            existing = db.execute('SELECT id FROM filter_tags WHERE name = ?', (tag_name,)).fetchone()
            if not existing:
                try:
                    db.execute('INSERT INTO filter_tags (name, display_name, color) VALUES (?, ?, ?)',
                              (tag_name, display_name, color))
                except sqlite3.OperationalError:
                    # Filter tags table doesn't exist yet, skip for now
                    pass
        
        # Create activity log table for audit trail
        db.execute('''CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            user_name TEXT,
            action_type TEXT NOT NULL,
            post_id INTEGER,
            post_title TEXT,
            comment_text TEXT,
            ip_address TEXT,
            user_agent TEXT,
            created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (post_id) REFERENCES posts (id)
        )''')
        
        # Create email logs table for tracking sent emails
        db.execute('''CREATE TABLE IF NOT EXISTS email_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipient_email TEXT NOT NULL,
            template_name TEXT,
            subject TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            error_message TEXT,
            user_id INTEGER,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )''')
        
        # Create filter tags table
        db.execute('''CREATE TABLE IF NOT EXISTS filter_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            display_name TEXT NOT NULL,
            color TEXT NOT NULL DEFAULT '#007bff',
            created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        # Migrate magic_link_reminders preference to new system (remove deprecated column)
        try:
            # First check if the old column exists
            cursor = db.execute("PRAGMA table_info(user_notification_preferences)")
            columns = [row[1] for row in cursor.fetchall()]
            
            if 'magic_link_reminder' in columns:
                # Remove the deprecated magic_link_reminder column
                db.execute('''CREATE TABLE user_notification_preferences_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    account_created INTEGER DEFAULT 1,
                    new_post INTEGER DEFAULT 1,
                    major_event INTEGER DEFAULT 1,
                    comment_reply INTEGER DEFAULT 1,
                    created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    UNIQUE(user_id)
                )''')
                
                # Copy data without the deprecated column
                db.execute('''INSERT INTO user_notification_preferences_new 
                             (id, user_id, account_created, new_post, major_event, comment_reply, created, updated)
                             SELECT id, user_id, account_created, new_post, major_event, comment_reply, created, updated
                             FROM user_notification_preferences''')
                
                # Drop old table and rename new one
                db.execute('DROP TABLE user_notification_preferences')
                db.execute('ALTER TABLE user_notification_preferences_new RENAME TO user_notification_preferences')
        except sqlite3.OperationalError:
            # Table doesn't exist or migration already done
            pass
        
        # Remove deprecated settings
        deprecated_settings = ['welcome_emails_enabled', 'magic_link_reminders_enabled']
        for setting_key in deprecated_settings:
            existing = db.execute('SELECT key FROM settings WHERE key = ?', (setting_key,)).fetchone()
            if existing:
                db.execute('DELETE FROM settings WHERE key = ?', (setting_key,))
        
        db.commit()
        
        # Extract images from existing posts and populate images table
        extract_images_from_posts()


def init_oauth_on_import(app=None):
    """Initialize OAuth when the module is imported (for WSGI)."""
    try:
        if app is None:
            app = current_app
            
        with app.app_context():
            # Import here to avoid circular imports
            from .queries import get_setting
            
            client_id = get_setting('oauth_client_id')
            client_secret = get_setting('oauth_client_secret')
            
            # Get oauth from app extensions
            oauth = getattr(app, 'oauth', None)
            if oauth is None:
                return
                
            if client_id and client_secret and not hasattr(oauth, 'google'):
                oauth.register(
                    name='google',
                    client_id=client_id,
                    client_secret=client_secret,
                    client_kwargs={'scope': 'openid email profile https://www.googleapis.com/auth/gmail.send'},
                    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration'
                )
                print("OAuth client registered on module import")
    except Exception as e:
        # Silently fail during import - OAuth will be set up later if needed
        pass