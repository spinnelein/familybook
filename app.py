import os
import sqlite3
import uuid
import requests
from flask import Flask, jsonify, request, redirect as flask_redirect, url_for, render_template, render_template_string, send_from_directory, flash, g, abort, session
from google_photos import get_authenticated_service, create_picker_session, poll_picker_session, get_picked_media_items
import time
import smtplib
import json
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from authlib.integrations.flask_client import OAuth
import email.utils

app = Flask(__name__)

# Configure uploads folder - can be overridden with environment variable for Synology mounting
app.config['UPLOAD_FOLDER'] = os.environ.get('FAMILYBOOK_UPLOADS_PATH', 'static/uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max upload size
app.config['DATABASE'] = os.environ.get('FAMILYBOOK_DATABASE_PATH', 'familybook.db')
app.secret_key = os.environ.get('FAMILYBOOK_SECRET_KEY', 'your-secret-key-change-this-in-production')

# URL configuration for subdirectory deployment
# Auto-detect URL prefix from nginx X-Script-Name header or environment variable
def get_url_prefix():
    # First try environment variable
    env_prefix = os.environ.get('FAMILYBOOK_URL_PREFIX', '')
    if env_prefix:
        return env_prefix
    
    # Try to detect from nginx proxy headers during request context
    try:
        from flask import has_request_context, request
        if has_request_context():
            script_name = request.environ.get('HTTP_X_SCRIPT_NAME') or request.environ.get('SCRIPT_NAME', '')
            if script_name and script_name != '/':
                return script_name
    except:
        pass
    
    return ''

# Set initial URL prefix (may be updated per request)
app.config['URL_PREFIX'] = get_url_prefix()
app.config['APPLICATION_ROOT'] = app.config['URL_PREFIX']

# Always set up custom session interface for dynamic URL prefix handling
from flask.sessions import SecureCookieSessionInterface

class CustomSessionInterface(SecureCookieSessionInterface):
    def get_cookie_path(self, app):
        # Dynamically get the current URL_PREFIX (may change per request)
        current_prefix = app.config.get('URL_PREFIX', '')
        return current_prefix if current_prefix else '/'

app.session_interface = CustomSessionInterface()

# If we have a URL prefix, we need to handle it properly
if app.config['URL_PREFIX']:
    from werkzeug.middleware.dispatcher import DispatcherMiddleware
    from werkzeug.wrappers import Response
    
    # Create a simple app for the root
    def simple(env, resp):
        resp(b'200 OK', [(b'Content-Type', b'text/plain')])
        return [b'Not Found']
    
    # Mount the Flask app at the prefix
    app.wsgi_app = DispatcherMiddleware(simple, {
        app.config['URL_PREFIX']: app.wsgi_app
    })

# Add middleware to detect URL prefix from nginx headers
@app.before_request
def detect_url_prefix():
    """Detect URL prefix from nginx X-Script-Name header and update app config"""
    from flask import request
    print(f"REQUEST: {request.method} {request.path}")
    print(f"ENVIRON HTTP_X_SCRIPT_NAME: {request.environ.get('HTTP_X_SCRIPT_NAME', 'NOT_SET')}")
    print(f"ENVIRON SCRIPT_NAME: {request.environ.get('SCRIPT_NAME', 'NOT_SET')}")
    
    script_name = request.environ.get('HTTP_X_SCRIPT_NAME') or request.environ.get('SCRIPT_NAME', '')
    if script_name and script_name != '/' and script_name != app.config.get('URL_PREFIX', ''):
        print(f"UPDATING URL_PREFIX from {app.config.get('URL_PREFIX', 'NOT_SET')} to {script_name}")
        app.config['URL_PREFIX'] = script_name
        app.config['APPLICATION_ROOT'] = script_name

# OAuth setup
oauth = OAuth(app)

# Custom url_for that handles URL prefix
def url_for_with_prefix(endpoint, **values):
    """Generate URLs that work with subdirectory deployment"""
    from flask import url_for as flask_url_for
    # Generate the URL normally
    url = flask_url_for(endpoint, **values)
    # If we have a URL prefix and the URL doesn't already include it, prepend it
    if app.config['URL_PREFIX'] and not url.startswith(app.config['URL_PREFIX']):
        url = app.config['URL_PREFIX'] + url
    return url

# Custom redirect that handles URL prefix
def redirect(location, code=302):
    """Redirect that works with subdirectory deployment"""
    # If the location is a relative URL starting with /, prepend the prefix
    if location.startswith('/') and app.config['URL_PREFIX'] and not location.startswith(app.config['URL_PREFIX']):
        location = app.config['URL_PREFIX'] + location
    return flask_redirect(location, code)

# Override Flask's url_for in templates
@app.context_processor
def override_url_for():
    return dict(url_for=url_for_with_prefix)

# Helper function to generate static URLs
def static_url(filename):
    """Generate URLs for static files that work with subdirectory deployment"""
    if app.config['URL_PREFIX']:
        return app.config['URL_PREFIX'] + '/static/' + filename
    return '/static/' + filename

# Helper function to generate upload URLs
def upload_url(filename):
    """Generate URLs for uploaded files that work with subdirectory deployment"""
    if app.config['URL_PREFIX']:
        return app.config['URL_PREFIX'] + '/uploads/' + filename
    return '/uploads/' + filename

# Add helpers to template context
@app.context_processor
def utility_processor():
    return dict(static_url=static_url, upload_url=upload_url)

# Function to process content and fix URLs
def fix_content_urls(content):
    """Fix image and file URLs in post content for subdirectory deployment"""
    if not content or not app.config['URL_PREFIX']:
        return content
    
    import re
    # Fix image sources - handle both /uploads/ and /static/uploads/
    content = re.sub(
        r'src=["\']/?(?:static/)?uploads/',
        f'src="{app.config["URL_PREFIX"]}/uploads/',
        content
    )
    # Fix any other static references
    content = re.sub(
        r'(?:href|src)=["\']/?static/',
        f'src="{app.config["URL_PREFIX"]}/static/',
        content
    )
    return content

# Add content processor to template context
@app.context_processor
def content_processor():
    return dict(fix_content_urls=fix_content_urls)

# Initialize OAuth when module is imported (for WSGI deployments)
def init_oauth_on_import():
    """Initialize OAuth when the module is imported (for WSGI)"""
    try:
        with app.app_context():
            client_id = get_setting('oauth_client_id')
            client_secret = get_setting('oauth_client_secret')
            
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

# Call the initialization
init_oauth_on_import()

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
                    <p>Welcome to our family photo and story sharing site! You can now view and interact with family posts.</p>
                    <p><strong>Your personal magic link to access posts:</strong></p>
                    <div style="background: white; padding: 15px; border-radius: 8px; margin: 15px 0; text-align: center;">
                        <a href="{{magic_link}}" style="color: #3b82f6; text-decoration: none; font-weight: bold; padding: 10px 20px; background: #eff6ff; border-radius: 6px; display: inline-block;">🔗 Access Family Posts</a>
                    </div>
                    <p style="color: #666; font-size: 14px;">Bookmark this link - it's your personal gateway to stay connected with the family!</p>
                </div></body></html>''',
             '''{{family_name}} Familybook - Welcome!

Hi {{user_name}}!

Welcome to our family photo and story sharing site! You can now view and interact with family posts.

Your personal magic link to access posts:
{{magic_link}}

Bookmark this link - it's your personal gateway to stay connected with the family!''',
             'user_name,family_name,magic_link'),
            
            ('new_post', 'New Family Post', 'Notification sent when a new post is created',
             'New Post: {{post_title}}',
             '''<html><body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; text-align: center; color: white;">
                    <h1 style="margin: 0;">🏠 {{family_name}} Familybook</h1>
                    <p style="margin: 5px 0 0 0;">New Post</p>
                </div>
                <div style="padding: 20px; background: #f9f9f9;">
                    <h2 style="color: #333; margin-top: 0;">{{post_title}}</h2>
                    {{#post_author}}<p style="color: #666; font-style: italic;">By {{post_author}}</p>{{/post_author}}
                    {{#post_tags}}<p style="color: #666; font-style: italic;">Tagged: {{post_tags}}</p>{{/post_tags}}
                    <div style="background: white; padding: 15px; border-radius: 8px; margin: 15px 0;">
                        {{post_content}}
                    </div>
                    <div style="text-align: center; margin-top: 30px;">
                        <a href="{{magic_link}}" style="color: white; background: #3b82f6; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: bold; display: inline-block;">📖 Read Full Post</a>
                    </div>
                    <p style="color: #666; font-size: 14px; text-align: center; margin-top: 20px;">
                        Visit the familybook to see the full post and join the conversation!<br>
                        Your magic link: {{magic_link}}
                    </p>
                </div></body></html>''',
             '''{{family_name}} Familybook - New Post

{{post_title}}
{{#post_author}}By {{post_author}}{{/post_author}}
{{#post_tags}}Tagged: {{post_tags}}{{/post_tags}}

{{post_content}}

Visit the familybook to see the full post and join the conversation!
Your magic link: {{magic_link}}''',
             'user_name,family_name,magic_link,post_title,post_author,post_content,post_tags'),
            
            ('major_event', 'Major Family Update', 'Notification for major events or important family news',
             '🚨 Major Update: {{post_title}}',
             '''<html><body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); padding: 20px; text-align: center; color: white;">
                    <h1 style="margin: 0;">🏠 {{family_name}} Familybook</h1>
                    <p style="margin: 5px 0 0 0;">🚨 Major Family Update</p>
                </div>
                <div style="padding: 20px; background: #f9f9f9;">
                    <h2 style="color: #333; margin-top: 0;">{{post_title}}</h2>
                    {{#post_author}}<p style="color: #666; font-style: italic;">By {{post_author}}</p>{{/post_author}}
                    <div style="background: #fef3c7; border-left: 4px solid #f59e0b; padding: 15px; border-radius: 8px; margin: 15px 0;">
                        <p style="margin: 0; color: #92400e; font-weight: bold;">This is marked as a major family update that everyone should see!</p>
                    </div>
                    <div style="background: white; padding: 15px; border-radius: 8px; margin: 15px 0;">
                        {{post_content}}
                    </div>
                    <div style="text-align: center; margin-top: 30px;">
                        <a href="{{magic_link}}" style="color: white; background: #f59e0b; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: bold; display: inline-block;">📖 Read Full Post</a>
                    </div>
                    <p style="color: #666; font-size: 14px; text-align: center; margin-top: 20px;">
                        Your magic link: {{magic_link}}
                    </p>
                </div></body></html>''',
             '''{{family_name}} Familybook - Major Update

🚨 MAJOR FAMILY UPDATE

{{post_title}}
{{#post_author}}By {{post_author}}{{/post_author}}

This is marked as a major family update that everyone should see!

{{post_content}}

Visit the familybook to see the full post and join the conversation!
Your magic link: {{magic_link}}''',
             'user_name,family_name,magic_link,post_title,post_author,post_content,post_tags'),
            
            ('comment_reply', 'Reply to Your Comment', 'Notification when someone replies to your comment',
             'Reply to your comment on "{{post_title}}"',
             '''<html><body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background: linear-gradient(135deg, #10b981 0%, #059669 100%); padding: 20px; text-align: center; color: white;">
                    <h1 style="margin: 0;">🏠 {{family_name}} Familybook</h1>
                    <p style="margin: 5px 0 0 0;">💬 New Reply</p>
                </div>
                <div style="padding: 20px; background: #f9f9f9;">
                    <h2 style="color: #333; margin-top: 0;">Someone replied to your comment!</h2>
                    <p>On the post: <strong>{{post_title}}</strong></p>
                    <div style="background: #f0f0f0; border-left: 4px solid #10b981; padding: 15px; border-radius: 8px; margin: 15px 0;">
                        <p style="margin: 0 0 10px 0; color: #666; font-size: 12px;"><strong>Your comment:</strong></p>
                        <p style="margin: 0;">{{original_comment}}</p>
                    </div>
                    <div style="background: white; padding: 15px; border-radius: 8px; margin: 15px 0;">
                        <p style="margin: 0 0 10px 0; color: #666; font-size: 12px;"><strong>{{reply_author}} replied:</strong></p>
                        <p style="margin: 0;">{{reply_content}}</p>
                    </div>
                    <div style="text-align: center; margin-top: 30px;">
                        <a href="{{magic_link}}" style="color: white; background: #10b981; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: bold; display: inline-block;">💬 View Conversation</a>
                    </div>
                    <p style="color: #666; font-size: 14px; text-align: center; margin-top: 20px;">
                        Your magic link: {{magic_link}}
                    </p>
                </div></body></html>''',
             '''{{family_name}} Familybook - New Reply

Someone replied to your comment!

On the post: {{post_title}}

Your comment:
{{original_comment}}

{{reply_author}} replied:
{{reply_content}}

View the conversation: {{magic_link}}''',
             'user_name,family_name,magic_link,post_title,original_comment,reply_author,reply_content')
        ]
        
        for template_name, display_name, description, subject, html, plain, variables in default_templates:
            existing = db.execute('SELECT id FROM email_templates WHERE template_name = ?', (template_name,)).fetchone()
            if not existing:
                db.execute('''INSERT INTO email_templates 
                             (template_name, display_name, description, subject_template, html_template, plain_template, variables) 
                             VALUES (?, ?, ?, ?, ?, ?, ?)''',
                          (template_name, display_name, description, subject, html, plain, variables))
        
        # Add filter_tags table for tag management
        db.execute('''CREATE TABLE IF NOT EXISTS filter_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            display_name TEXT NOT NULL,
            color TEXT DEFAULT '#3b82f6',
            created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        # Insert default filter tags if they don't exist
        default_tags = [
            ('photos', 'Photos', '#10b981'),
            ('news', 'News', '#3b82f6'), 
            ('recipes', 'Recipes', '#f59e0b'),
            ('poetry', 'Poetry', '#8b5cf6')
        ]
        
        for tag_name, display_name, color in default_tags:
            existing = db.execute('SELECT id FROM filter_tags WHERE name = ?', (tag_name,)).fetchone()
            if not existing:
                db.execute('INSERT INTO filter_tags (name, display_name, color) VALUES (?, ?, ?)',
                          (tag_name, display_name, color))
        
        db.commit()
        
        # Extract images from existing posts and populate images table
        extract_images_from_posts()

def setup_oauth():
    """Configure OAuth client with database settings"""
    try:
        # Check if already registered to avoid duplicate registration
        if hasattr(oauth, 'google'):
            print("OAuth client already registered")
            return True
            
        client_id = get_setting('oauth_client_id')
        client_secret = get_setting('oauth_client_secret') 
        redirect_uri = get_setting('oauth_redirect_uri')
        
        print(f"OAuth setup - Client ID: {client_id[:20]}..." if client_id else "OAuth setup - Client ID: None")
        print(f"OAuth setup - Client Secret: {'Set' if client_secret else 'None'}")
        print(f"OAuth setup - Redirect URI: {redirect_uri}")
        
        if client_id and client_secret:
            print("Registering OAuth client...")
            oauth.register(
                name='google',
                client_id=client_id,
                client_secret=client_secret,
                client_kwargs={
                    'scope': 'openid email profile https://www.googleapis.com/auth/gmail.send'
                },
                server_metadata_url='https://accounts.google.com/.well-known/openid-configuration'
            )
            print("OAuth client registered successfully")
            return True
        else:
            print(f"OAuth setup failed - Missing credentials: client_id={bool(client_id)}, client_secret={bool(client_secret)}")
            return False
    except Exception as e:
        print(f"OAuth setup error: {e}")
        import traceback
        traceback.print_exc()
        return False

def get_setting(key, default=None):
    """Get a setting value from the database"""
    with app.app_context():
        db = get_db()
        result = db.execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
        return result['value'] if result else default

def update_setting(key, value):
    """Update a setting value in the database"""
    with app.app_context():
        db = get_db()
        db.execute('UPDATE settings SET value = ?, updated = CURRENT_TIMESTAMP WHERE key = ?', (value, key))
        db.commit()

def is_oauth_configured():
    """Check if OAuth is configured"""
    oauth_client_id = get_setting('oauth_client_id', '')
    oauth_client_secret = get_setting('oauth_client_secret', '')
    return bool(oauth_client_id and oauth_client_secret)

def requires_admin_auth():
    """Check if admin authentication is required (only if OAuth is configured)"""
    if not is_oauth_configured():
        return False  # Open access when OAuth not configured
    
    # Debug session data
    print(f"Session data: {dict(session)}")
    print(f"URL_PREFIX: {app.config.get('URL_PREFIX', 'NOT_SET')}")
    print(f"admin_user_id in session: {'admin_user_id' in session}")
    
    return 'admin_user_id' not in session

def redirect_to_admin_login():
    """Helper function to redirect to admin login while preserving subpath"""
    from flask import request
    script_name = request.environ.get('SCRIPT_NAME', '')
    return redirect(f'{script_name}/admin/login')

def cleanup_orphaned_media():
    """Remove uploaded media files that aren't referenced in any posts"""
    try:
        import re
        import glob
        
        with app.app_context():
            db = get_db()
            
            # Get all uploaded files
            upload_dir = app.config['UPLOAD_FOLDER']
            all_files = set()
            for pattern in ['*.jpg', '*.jpeg', '*.png', '*.gif', '*.webp', '*.mp4', '*.mov', '*.avi', '*.mkv']:
                all_files.update([os.path.basename(f) for f in glob.glob(os.path.join(upload_dir, pattern))])
            
            # Get all files referenced in post content
            used_files = set()
            posts = db.execute('SELECT content FROM posts WHERE content IS NOT NULL').fetchall()
            
            for post in posts:
                if post['content']:
                    # Find all src attributes in img tags
                    img_matches = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', post['content'])
                    for match in img_matches:
                        if '/uploads/' in match:
                            filename = match.split('/uploads/')[-1]
                            used_files.add(filename)
                    
                    # Find all src attributes in video tags
                    video_matches = re.findall(r'<video[^>]+src=["\']([^"\']+)["\']', post['content'])
                    for match in video_matches:
                        if '/uploads/' in match:
                            filename = match.split('/uploads/')[-1]
                            used_files.add(filename)
                    
                    # Find all src attributes in source tags (HTML5 video sources)
                    source_matches = re.findall(r'<source[^>]+src=["\']([^"\']+)["\']', post['content'])
                    for match in source_matches:
                        if '/uploads/' in match:
                            filename = match.split('/uploads/')[-1]
                            used_files.add(filename)
            
            # Get files from images table (legacy system)
            image_files = db.execute('SELECT filename FROM images WHERE filename IS NOT NULL').fetchall()
            for row in image_files:
                if row['filename']:
                    used_files.add(row['filename'])
            
            # Debug logging
            print(f"Cleanup scan: Found {len(all_files)} total files, {len(used_files)} files in use")
            print(f"Files in use: {sorted(used_files)}")
            
            # Find orphaned files
            orphaned_files = all_files - used_files
            
            if orphaned_files:
                print(f"Orphaned files to delete: {sorted(orphaned_files)}")
            else:
                print("No orphaned files found")
            
            # Delete orphaned files
            deleted_count = 0
            for filename in orphaned_files:
                try:
                    file_path = os.path.join(upload_dir, filename)
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        deleted_count += 1
                        print(f"Deleted orphaned file: {filename}")
                except Exception as e:
                    print(f"Error deleting {filename}: {str(e)}")
            
            print(f"Cleanup complete: {deleted_count} orphaned files removed")
            return deleted_count
            
    except Exception as e:
        print(f"Error during media cleanup: {str(e)}")
        return 0

def get_admin_oauth_token():
    """Get OAuth token for the currently logged-in admin user"""
    admin_user_id = session.get('admin_user_id')
    if not admin_user_id:
        return None
    
    # For now, we'll need to store OAuth tokens in the database
    # This is a simplified approach - in production you'd want better token management
    db = get_db()
    admin_user = db.execute('SELECT * FROM users WHERE id = ? AND is_admin = 1', (admin_user_id,)).fetchone()
    
    if admin_user:
        # Return the email of the logged-in admin for now
        # In a full implementation, you'd store and refresh OAuth tokens
        return admin_user['email']
    return None

def send_gmail_oauth_email(to_email, subject, html_body, plain_body):
    """Send email using Gmail API with OAuth2 authentication"""
    try:
        # This would require storing OAuth tokens and using Gmail API
        # For now, let's implement a hybrid approach using SMTP with OAuth2
        
        admin_email = get_admin_oauth_token()
        if not admin_email:
            print("No admin OAuth token available for email sending")
            return False
            
        # Use Gmail SMTP with XOAUTH2 (requires implementing XOAUTH2 auth)
        # For now, let's fall back to the traditional method but with proper error handling
        return send_traditional_smtp_email(to_email, subject, html_body, plain_body)
        
    except Exception as e:
        print(f"OAuth2 Gmail API email failed: {e}")
        return False

def render_email_template(template_name, **context):
    """Render an email template with the given context"""
    try:
        db = get_db()
        template = db.execute('''SELECT * FROM email_templates 
                                WHERE template_name = ? AND is_active = 1''', 
                             (template_name,)).fetchone()
        
        if not template:
            print(f"No active template found for: {template_name}")
            return None, None, None
        
        # Add common context variables
        context['family_name'] = get_setting('family_name', 'Familybook')
        
        # Render templates
        subject = render_template_string(template['subject_template'], **context)
        html_body = render_template_string(template['html_template'], **context)
        plain_body = render_template_string(template['plain_template'], **context)
        
        return subject, html_body, plain_body
    
    except Exception as e:
        print(f"Error rendering email template '{template_name}': {e}")
        return None, None, None

def send_templated_email(template_name, to_email, **context):
    """Send an email using a template"""
    try:
        subject, html_body, plain_body = render_email_template(template_name, **context)
        
        if not subject:
            print(f"Failed to render template '{template_name}'")
            return False
        
        return send_traditional_smtp_email(to_email, subject, html_body, plain_body)
    
    except Exception as e:
        print(f"Error sending templated email '{template_name}' to {to_email}: {e}")
        return False

def send_notification_email(template_name, user_id, **context):
    """Send a notification email to a user based on their preferences"""
    try:
        db = get_db()
        
        # Get user info
        user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
        if not user or not user['email']:
            return False
        
        # Get user's notification preferences
        prefs = db.execute('SELECT * FROM user_notification_preferences WHERE user_id = ?', 
                          (user_id,)).fetchone()
        
        # Check if user wants this type of notification
        if prefs:
            notification_enabled = False
            if template_name == 'account_created' and prefs['account_created']:
                notification_enabled = True
            elif template_name == 'new_post' and prefs['new_post']:
                notification_enabled = True
            elif template_name == 'major_event' and prefs['major_event']:
                notification_enabled = True
            elif template_name == 'comment_reply' and prefs['comment_reply']:
                notification_enabled = True
            
            if not notification_enabled:
                print(f"User {user['email']} has disabled '{template_name}' notifications")
                return False
        
        # Add user context
        context['user_name'] = user['name']
        context['magic_link'] = url_for('posts', magic_token=user['magic_token'], _external=True)
        
        return send_templated_email(template_name, user['email'], **context)
    
    except Exception as e:
        print(f"Error sending notification email to user {user_id}: {e}")
        return False

def send_traditional_smtp_email(to_email, subject, html_body, plain_body):
    """Send email using traditional SMTP (fallback method)"""
    try:
        # Get SMTP settings
        smtp_server = get_setting('smtp_server', '')
        smtp_port = int(get_setting('smtp_port', '587'))
        smtp_username = get_setting('smtp_username', '')
        smtp_password = get_setting('smtp_password', '')
        smtp_use_tls = get_setting('smtp_use_tls', 'true').lower() == 'true'
        email_from_name = get_setting('email_from_name', 'Slugranch Familybook')
        email_from_address = get_setting('email_from_address', '')
        
        # Validate required settings (username/password optional for local servers)
        if not all([smtp_server, email_from_address]):
            print("Email sending skipped: Missing SMTP server or from address")
            return False
        
        # Create email
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"{email_from_name} <{email_from_address}>"
        msg['To'] = to_email
        msg['Date'] = email.utils.formatdate()
        
        # Add both plain text and HTML versions
        msg.attach(MIMEText(plain_body, 'plain'))
        msg.attach(MIMEText(html_body, 'html'))
        
        # Send email
        server = smtplib.SMTP(smtp_server, smtp_port)
        if smtp_use_tls:
            server.starttls()
        
        # Only authenticate if username and password are provided
        if smtp_username and smtp_password:
            server.login(smtp_username, smtp_password)
        
        server.send_message(msg)
        server.quit()
        
        print(f"Email sent successfully to {to_email}")
        return True
        
    except Exception as e:
        print(f"SMTP email sending failed: {e}")
        return False

# Legacy email notification function - replaced by templated system
# This function is kept for backward compatibility but should no longer be used
def send_email_notifications(post_id, title, content, tags):
    """DEPRECATED: Use send_notification_email with templates instead"""
    print("Warning: send_email_notifications is deprecated. Use templated email system instead.")

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
        tags = request.form.get('tags', '').strip()  # Get tags from form

        db = get_db()
        author_id = user['id'] if user else None
        
        # Insert post with tags
        cursor = db.execute(
            "INSERT INTO posts (title, content, author_id, tags) VALUES (?, ?, ?, ?)",
            (title, content, author_id, tags)
        )
        post_id = cursor.lastrowid
        db.commit()
        
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
            return redirect(url_for('create_post', magic_token=magic_token))
        return redirect(url_for('create_post'))
    
    # Get available filter tags for the tags input field
    db = get_db()
    filter_tags = db.execute('SELECT name FROM filter_tags ORDER BY name').fetchall()
    available_tags = [tag['name'] for tag in filter_tags]
    
    return render_template('create_post.html', user=user, available_tags=available_tags)

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

# Admin login page
@app.route('/admin/login')
def admin_login():
    db = get_db()
    
    # If OAuth is not configured, redirect directly to admin console
    if not is_oauth_configured():
        flash('OAuth not configured. Direct access granted for setup.', 'info')
        return redirect(url_for('admin_console'))
    
    oauth_configured = is_oauth_configured()
    return render_template('admin_login.html', oauth_configured=oauth_configured)

# Setup route for initial OAuth configuration (no auth required)
@app.route('/admin/setup', methods=['GET', 'POST'])
def admin_setup():
    db = get_db()
    
    # Check if OAuth is already configured
    oauth_client_id = get_setting('oauth_client_id', '')
    oauth_client_secret = get_setting('oauth_client_secret', '')
    
    if oauth_client_id and oauth_client_secret:
        flash('OAuth is already configured. Please use the login page.', 'info')
        return redirect(url_for('admin_login'))
    
    if request.method == 'POST':
        # Update OAuth settings
        oauth_settings = ['oauth_client_id', 'oauth_client_secret', 'oauth_redirect_uri']
        
        for setting_key in oauth_settings:
            if setting_key in request.form:
                value = request.form[setting_key]
                update_setting(setting_key, value)
        
        flash('OAuth configured successfully! You can now login.', 'success')
        return redirect(url_for('admin_login'))
    
    # Get current settings for display
    settings = {}
    all_settings = db.execute('SELECT key, value, description FROM settings').fetchall()
    for setting in all_settings:
        settings[setting['key']] = {
            'value': setting['value'],
            'description': setting['description']
        }
    
    return render_template('admin_setup.html', settings=settings)

# OAuth login route
@app.route('/admin/oauth/login')
def oauth_login():
    # Try to setup OAuth, with retry logic
    max_retries = 3
    for attempt in range(max_retries):
        print(f"OAuth setup attempt {attempt + 1}/{max_retries}")
        success = setup_oauth()  # Configure OAuth with current settings
        
        if hasattr(oauth, 'google'):
            print("OAuth client verified - proceeding with login")
            break
            
        if attempt < max_retries - 1:
            print("OAuth setup failed, retrying...")
            # Clear any partial registration
            if hasattr(oauth, '_clients') and 'google' in oauth._clients:
                del oauth._clients['google']
            if hasattr(oauth, '_registry') and 'google' in oauth._registry:
                del oauth._registry['google']
    
    if not hasattr(oauth, 'google'):
        # Better error message with debugging info
        client_id = get_setting('oauth_client_id')
        client_secret = get_setting('oauth_client_secret')
        print(f"Final OAuth state check failed after {max_retries} attempts")
        print(f"OAuth _clients: {getattr(oauth, '_clients', {})}")
        print(f"OAuth _registry: {getattr(oauth, '_registry', {})}")
        error_msg = f"OAuth registration failed. Debug: client_id={'set' if client_id else 'missing'}, client_secret={'set' if client_secret else 'missing'}"
        print(error_msg)
        flash(error_msg, 'danger')
        return redirect(url_for('admin_login'))
    
    redirect_uri = get_setting('oauth_redirect_uri', url_for('oauth_callback', _external=True))
    return oauth.google.authorize_redirect(redirect_uri)

# OAuth callback route
@app.route('/admin/oauth/callback')
def oauth_callback():
    setup_oauth()
    if not hasattr(oauth, 'google'):
        flash('OAuth not configured.', 'danger')
        return redirect(url_for('admin_login'))
    
    try:
        token = oauth.google.authorize_access_token()
        user_info = token.get('userinfo')
        
        if user_info:
            email = user_info.get('email')
            name = user_info.get('name')
            
            # Check if this email belongs to an admin user
            db = get_db()
            admin_user = db.execute(
                'SELECT * FROM users WHERE email = ? AND is_admin = 1', 
                (email,)
            ).fetchone()
            
            if admin_user:
                # Valid admin user - create session
                session['admin_user_id'] = admin_user['id']
                session['admin_user_email'] = email
                session['admin_user_name'] = name
                flash(f'Welcome, {name}!', 'success')
                return redirect(url_for('admin_console'))
            else:
                flash('Access denied. Only admin users can access the admin console.', 'danger')
                return redirect(url_for('admin_login'))
        else:
            flash('Failed to get user information from Google.', 'danger')
            return redirect(url_for('admin_login'))
            
    except Exception as e:
        print(f"OAuth callback error: {e}")
        flash('Authentication failed.', 'danger')
        return redirect(url_for('admin_login'))

# Admin logout route
@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_user_id', None)
    session.pop('admin_user_email', None) 
    session.pop('admin_user_name', None)
    flash('Logged out successfully.', 'success')
    return redirect_to_admin_login()

# Admin console page (protected only when OAuth is configured)
@app.route('/admin/console', methods=['GET', 'POST'])
def admin_console():
    # Check if admin authentication is required
    if requires_admin_auth():
        return redirect_to_admin_login()
    
    db = get_db()
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        email_notifications = request.form.get('email_notifications', 'all')
        magic_token = uuid.uuid4().hex
        try:
            cursor = db.execute('INSERT INTO users (name, email, magic_token, email_notifications) VALUES (?, ?, ?, ?)', 
                               (name, email, magic_token, email_notifications))
            user_id = cursor.lastrowid
            db.commit()
            
            # Send welcome email if notifications are enabled
            if get_setting('notifications_enabled', 'false').lower() == 'true':
                try:
                    send_notification_email('account_created', user_id)
                    print(f"Welcome email sent to {email}")
                except Exception as e:
                    print(f"Failed to send welcome email to {email}: {e}")
            
            flash('User added!', 'success')
        except sqlite3.IntegrityError:
            flash('Email already exists!', 'danger')
        return redirect(url_for('admin_console'))

    users = db.execute('SELECT * FROM users').fetchall()
    filter_tags = db.execute('SELECT * FROM filter_tags ORDER BY name').fetchall()
    oauth_configured = is_oauth_configured()
    return render_template('admin_console.html', users=users, filter_tags=filter_tags, oauth_configured=oauth_configured)

# Remove user
@app.route('/admin/users/remove/<int:user_id>', methods=['POST'])
def remove_user(user_id):
    # Check if admin authentication is required
    if requires_admin_auth():
        return redirect_to_admin_login()
    
    db = get_db()
    db.execute('DELETE FROM users WHERE id = ?', (user_id,))
    db.commit()
    flash('User removed.', 'info')
    return redirect(url_for('admin_console'))

# Toggle admin status
@app.route('/admin/users/toggle-admin/<int:user_id>', methods=['POST'])
def toggle_admin_status(user_id):
    try:
        # Check if admin authentication is required
        if requires_admin_auth():
            return jsonify({'error': 'Unauthorized'}), 401
        
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
        
    except Exception as e:
        print(f"Error in toggle_admin_status: {e}")
        return jsonify({'error': str(e)}), 500

# Update user email notification preferences
@app.route('/admin/users/update-notifications/<int:user_id>', methods=['POST'])
def update_user_notifications(user_id):
    # Check if admin authentication is required
    if requires_admin_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    db = get_db()
    email_notifications = request.form.get('email_notifications', 'all')
    
    db.execute('UPDATE users SET email_notifications = ? WHERE id = ?', (email_notifications, user_id))
    db.commit()
    
    return jsonify({'success': True})

# Add filter tag
@app.route('/admin/tags/add', methods=['POST'])
def add_filter_tag():
    # Check if admin authentication is required
    if requires_admin_auth():
        return redirect_to_admin_login()
    
    db = get_db()
    name = request.form.get('name', '').strip().lower()
    display_name = request.form.get('display_name', '').strip()
    color = request.form.get('color', '#3b82f6')
    
    if not name or not display_name:
        flash('Tag name and display name are required!', 'danger')
        return redirect(url_for('admin_console'))
    
    try:
        db.execute('INSERT INTO filter_tags (name, display_name, color) VALUES (?, ?, ?)',
                  (name, display_name, color))
        db.commit()
        flash('Filter tag added!', 'success')
    except sqlite3.IntegrityError:
        flash('Tag name already exists!', 'danger')
    
    return redirect(url_for('admin_console'))

# Remove filter tag
@app.route('/admin/tags/remove/<int:tag_id>', methods=['POST'])
def remove_filter_tag(tag_id):
    # Check if admin authentication is required
    if requires_admin_auth():
        return redirect_to_admin_login()
    
    db = get_db()
    db.execute('DELETE FROM filter_tags WHERE id = ?', (tag_id,))
    db.commit()
    flash('Filter tag removed!', 'info')
    return redirect(url_for('admin_console'))

# Settings page for SMTP configuration
@app.route('/admin/settings', methods=['GET', 'POST'])
def admin_settings():
    # Check if admin authentication is required
    if requires_admin_auth():
        return redirect_to_admin_login()
    
    db = get_db()
    
    if request.method == 'POST':
        # Update settings from form
        settings_to_update = [
            'oauth_client_id', 'oauth_client_secret', 'oauth_redirect_uri',
            'smtp_server', 'smtp_port', 'smtp_username', 'smtp_password',
            'smtp_use_tls', 'email_from_name', 'email_from_address', 'notifications_enabled'
        ]
        
        for setting_key in settings_to_update:
            if setting_key in request.form:
                value = request.form[setting_key]
                # Handle checkboxes
                if setting_key in ['smtp_use_tls', 'notifications_enabled']:
                    value = 'true' if request.form.get(setting_key) else 'false'
                
                db.execute('UPDATE settings SET value = ?, updated = CURRENT_TIMESTAMP WHERE key = ?',
                          (value, setting_key))
        
        db.commit()
        flash('Settings updated successfully!', 'success')
        return redirect(url_for('admin_settings'))
    
    # Get all settings for display
    settings = {}
    all_settings = db.execute('SELECT key, value, description FROM settings').fetchall()
    for setting in all_settings:
        settings[setting['key']] = {
            'value': setting['value'],
            'description': setting['description']
        }
    
    return render_template('admin_settings.html', settings=settings)

# Email Templates Management
@app.route('/admin/email-templates')
def admin_email_templates():
    # Check if admin authentication is required
    if requires_admin_auth():
        return redirect_to_admin_login()
    
    db = get_db()
    templates = db.execute('SELECT * FROM email_templates ORDER BY template_name').fetchall()
    return render_template('admin_email_templates.html', templates=templates)

@app.route('/admin/email-templates/edit/<int:template_id>', methods=['GET', 'POST'])
def edit_email_template(template_id):
    # Check if admin authentication is required
    if requires_admin_auth():
        return redirect_to_admin_login()
    
    db = get_db()
    
    if request.method == 'POST':
        # Update template
        display_name = request.form['display_name']
        description = request.form.get('description', '')
        subject_template = request.form['subject_template']
        html_template = request.form['html_template']
        plain_template = request.form['plain_template']
        variables = request.form.get('variables', '')
        is_active = 1 if request.form.get('is_active') else 0
        
        db.execute('''UPDATE email_templates 
                     SET display_name = ?, description = ?, subject_template = ?, 
                         html_template = ?, plain_template = ?, variables = ?, 
                         is_active = ?, updated = CURRENT_TIMESTAMP 
                     WHERE id = ?''',
                  (display_name, description, subject_template, html_template, 
                   plain_template, variables, is_active, template_id))
        db.commit()
        
        flash('Email template updated successfully!', 'success')
        return redirect(url_for('admin_email_templates'))
    
    # Get template for editing
    template = db.execute('SELECT * FROM email_templates WHERE id = ?', (template_id,)).fetchone()
    if not template:
        abort(404)
    
    return render_template('admin_email_template_edit.html', template=template)

@app.route('/admin/email-templates/test/<int:template_id>', methods=['POST'])
def test_email_template(template_id):
    # Check if admin authentication is required
    if requires_admin_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        db = get_db()
        template = db.execute('SELECT * FROM email_templates WHERE id = ?', (template_id,)).fetchone()
        
        if not template:
            return jsonify({'success': False, 'error': 'Template not found'})
        
        # Get test email address
        test_email = None
        if 'admin_user_email' in session:
            test_email = session['admin_user_email']
        else:
            test_email = 'root@localhost'
        
        if not test_email:
            return jsonify({'success': False, 'error': 'No test email address available'})
        
        # Render template with sample data
        sample_data = {
            'user_name': 'Test User',
            'family_name': get_setting('family_name', 'Familybook'),
            'magic_link': url_for('posts', magic_token='sample-token', _external=True),
            'post_title': 'Sample Post Title',
            'post_author': 'Sample Author',
            'post_content': 'This is sample post content for testing the email template.',
            'post_tags': 'photos, test',
            'original_comment': 'This is a sample comment',
            'reply_author': 'Reply Author',
            'reply_content': 'This is a sample reply to test the template.'
        }
        
        rendered_subject = render_template_string(template['subject_template'], **sample_data)
        rendered_html = render_template_string(template['html_template'], **sample_data)
        rendered_plain = render_template_string(template['plain_template'], **sample_data)
        
        # Send test email
        success = send_traditional_smtp_email(
            test_email,
            f"[TEST] {rendered_subject}",
            rendered_html,
            rendered_plain
        )
        
        if success:
            return jsonify({'success': True, 'message': f'Test email sent to {test_email}'})
        else:
            return jsonify({'success': False, 'error': 'Failed to send test email'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/admin/email-templates/create-defaults', methods=['POST'])
def create_default_email_templates():
    # Check if admin authentication is required
    if requires_admin_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        db = get_db()
        
        # Define default templates
        default_templates = [
            {
                'template_name': 'user_invitation',
                'display_name': 'User Invitation',
                'description': 'Sent when a new user is invited to the family book',
                'subject_template': 'Welcome to {{family_name}}!',
                'html_template': '''
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; border-radius: 10px; color: white; text-align: center;">
        <h1 style="margin: 0;">Welcome to {{family_name}}!</h1>
    </div>
    <div style="padding: 30px; background: #f8f9fa; border-radius: 0 0 10px 10px;">
        <p>Hi {{user_name}},</p>
        <p>You've been invited to join the {{family_name}} family photo book! This is a private space where we share memories, photos, and stay connected.</p>
        <div style="text-align: center; margin: 30px 0;">
            <a href="{{magic_link}}" style="background: #3b82f6; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; display: inline-block;">View Family Posts</a>
        </div>
        <p>Bookmark the link above to easily access all our family updates!</p>
        <p style="color: #666; font-size: 14px;">This is your personal access link. Please don't share it with others.</p>
    </div>
</body>
</html>
                ''',
                'plain_template': '''Hi {{user_name}},

You've been invited to join the {{family_name}} family photo book!

Visit: {{magic_link}}

Bookmark this link to easily access all our family updates.

This is your personal access link. Please don't share it with others.
                ''',
                'variables': 'user_name, family_name, magic_link'
            },
            {
                'template_name': 'new_post_notification',
                'display_name': 'New Post Notification',
                'description': 'Sent when a new post is added to notify family members',
                'subject_template': 'New post: {{post_title}} - {{family_name}}',
                'html_template': '''
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; border-radius: 10px 10px 0 0; color: white;">
        <h2 style="margin: 0;">New Post in {{family_name}}</h2>
    </div>
    <div style="padding: 30px; background: #f8f9fa; border-radius: 0 0 10px 10px;">
        <h3 style="color: #333; margin-top: 0;">{{post_title}}</h3>
        <p style="color: #666;">Posted by {{post_author}}</p>
        <div style="background: white; padding: 20px; border-radius: 5px; margin: 20px 0;">
            {{post_content}}
        </div>
        <div style="text-align: center; margin: 30px 0;">
            <a href="{{magic_link}}" style="background: #10b981; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; display: inline-block;">View Post</a>
        </div>
    </div>
</body>
</html>
                ''',
                'plain_template': '''New Post in {{family_name}}

{{post_title}}
Posted by {{post_author}}

{{post_content}}

View the full post: {{magic_link}}
                ''',
                'variables': 'user_name, family_name, magic_link, post_title, post_author, post_content'
            },
            {
                'template_name': 'weekly_digest',
                'display_name': 'Weekly Family Digest',
                'description': 'Weekly summary of family activity (if implemented)',
                'subject_template': 'Weekly Family Update - {{family_name}}',
                'html_template': '''
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; border-radius: 10px 10px 0 0; color: white; text-align: center;">
        <h1 style="margin: 0;">📧 Weekly Family Update</h1>
        <p style="margin: 10px 0 0 0;">{{family_name}}</p>
    </div>
    <div style="padding: 30px; background: #f8f9fa; border-radius: 0 0 10px 10px;">
        <p>Hi {{user_name}},</p>
        <p>Here's what happened in the {{family_name}} family this week:</p>
        
        <div style="background: white; padding: 20px; border-radius: 5px; margin: 20px 0;">
            <h3 style="color: #333; margin-top: 0;">📱 This Week's Activity</h3>
            <p>{{weekly_summary}}</p>
        </div>
        
        <div style="text-align: center; margin: 30px 0;">
            <a href="{{magic_link}}" style="background: #3b82f6; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; display: inline-block;">View All Posts</a>
        </div>
        
        <p style="color: #666; font-size: 14px; text-align: center;">You can update your notification preferences anytime.</p>
    </div>
</body>
</html>
                ''',
                'plain_template': '''Weekly Family Update - {{family_name}}

Hi {{user_name}},

Here's what happened in the {{family_name}} family this week:

{{weekly_summary}}

View all posts: {{magic_link}}

You can update your notification preferences anytime.
                ''',
                'variables': 'user_name, family_name, magic_link, weekly_summary'
            }
        ]
        
        # Insert templates
        created_count = 0
        for template in default_templates:
            # Check if template already exists
            existing = db.execute('SELECT id FROM email_templates WHERE template_name = ?', 
                                (template['template_name'],)).fetchone()
            
            if not existing:
                db.execute('''INSERT INTO email_templates 
                    (template_name, display_name, description, subject_template, 
                     html_template, plain_template, variables, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1)''',
                    (template['template_name'], template['display_name'], 
                     template['description'], template['subject_template'],
                     template['html_template'], template['plain_template'], 
                     template['variables']))
                created_count += 1
        
        db.commit()
        
        return jsonify({
            'success': True, 
            'message': f'Created {created_count} default email templates',
            'created_count': created_count
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# User Notification Preferences
@app.route('/user-settings/<magic_token>')
def user_settings(magic_token):
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE magic_token = ?', (magic_token,)).fetchone()
    if not user:
        abort(403)
    
    # Get user's notification preferences
    prefs = db.execute('SELECT * FROM user_notification_preferences WHERE user_id = ?', 
                      (user['id'],)).fetchone()
    
    # If no preferences exist, create default ones
    if not prefs:
        db.execute('''INSERT INTO user_notification_preferences 
                     (user_id, account_created, new_post, major_event, comment_reply, magic_link_reminder) 
                     VALUES (?, 1, 1, 1, 1, 1)''', (user['id'],))
        db.commit()
        prefs = db.execute('SELECT * FROM user_notification_preferences WHERE user_id = ?', 
                          (user['id'],)).fetchone()
    
    return render_template('user_settings.html', user=user, prefs=prefs)

@app.route('/user-settings/<magic_token>/update', methods=['POST'])
def update_user_settings(magic_token):
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE magic_token = ?', (magic_token,)).fetchone()
    if not user:
        abort(403)
    
    # Update notification preferences
    account_created = 1 if request.form.get('account_created') else 0
    new_post = 1 if request.form.get('new_post') else 0
    major_event = 1 if request.form.get('major_event') else 0
    comment_reply = 1 if request.form.get('comment_reply') else 0
    magic_link_reminder = 1 if request.form.get('magic_link_reminder') else 0
    
    # Update or insert preferences
    existing = db.execute('SELECT id FROM user_notification_preferences WHERE user_id = ?', 
                         (user['id'],)).fetchone()
    
    if existing:
        db.execute('''UPDATE user_notification_preferences 
                     SET account_created = ?, new_post = ?, major_event = ?, 
                         comment_reply = ?, magic_link_reminder = ?, updated = CURRENT_TIMESTAMP
                     WHERE user_id = ?''',
                  (account_created, new_post, major_event, comment_reply, 
                   magic_link_reminder, user['id']))
    else:
        db.execute('''INSERT INTO user_notification_preferences 
                     (user_id, account_created, new_post, major_event, comment_reply, magic_link_reminder) 
                     VALUES (?, ?, ?, ?, ?, ?)''',
                  (user['id'], account_created, new_post, major_event, comment_reply, magic_link_reminder))
    
    db.commit()
    flash('Your notification preferences have been updated!', 'success')
    return redirect(url_for('user_settings', magic_token=magic_token))

# Test email functionality
@app.route('/admin/test-email', methods=['POST'])
def test_email():
    # Check if admin authentication is required
    if requires_admin_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        # Get test recipient email - try admin user or use local root
        test_email = None
        if 'admin_user_email' in session:
            test_email = session['admin_user_email']
        else:
            # Use local root user for testing local Postfix
            test_email = 'root@localhost'
        
        if not test_email:
            return jsonify({'success': False, 'error': 'No test email address available'})
        
        # Get email settings for display names
        email_from_name = get_setting('email_from_name', 'Slugranch Familybook')
        
        html_body = """
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; text-align: center; color: white;">
                <h1 style="margin: 0;">🏠 Slugranch Familybook</h1>
                <p style="margin: 5px 0 0 0;">Email Configuration Test</p>
            </div>
            <div style="padding: 20px; background: #f9f9f9;">
                <h2 style="color: #333; margin-top: 0;">✅ Email Settings Working!</h2>
                <p>This is a test email to verify your SMTP configuration is working correctly.</p>
                <p style="color: #666; font-size: 14px; text-align: center; margin-top: 30px;">
                    If you received this email, your notification system is ready to go!
                </p>
            </div>
        </body>
        </html>
        """
        
        plain_body = """
Slugranch Familybook - Email Configuration Test

✅ Email Settings Working!

This is a test email to verify your SMTP configuration is working correctly.

If you received this email, your notification system is ready to go!
        """
        
        # Send test email using local SMTP
        success = send_traditional_smtp_email(
            test_email,
            'Test Email from Slugranch Familybook',
            html_body,
            plain_body
        )
        
        if success:
            return jsonify({'success': True, 'message': f'Test email sent to {test_email}'})
        else:
            return jsonify({'success': False, 'error': 'Failed to send test email'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# Posts feed with magic link
@app.route('/posts/<magic_token>')
@app.route('/posts/<magic_token>/<year_month>')
@app.route('/posts/<magic_token>/show/<show_type>')
@app.route('/posts/<magic_token>/tag/<tag_filter>')
def posts(magic_token, year_month=None, show_type=None, tag_filter=None):
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
        from google_photos import is_authenticated
        
        # Check if authenticated
        if not is_authenticated():
            auth_url = url_for('google_photos_auth', _external=True)
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
            auth_url = url_for('google_photos_auth', _external=True)
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
def download_selected_media():
    """Download and process selected media from Google Photos Picker"""
    try:
        data = request.get_json()
        selected_items = data.get('selectedItems', [])
        
        if not selected_items:
            return jsonify({'success': False, 'error': 'No media provided'}), 400
        
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
                
                # Use appropriate download parameter based on media type
                if mime_type.startswith('video/'):
                    download_url = f"{base_url}=dv"  # Download original video
                else:
                    download_url = f"{base_url}=d"   # Download original image
                
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
        print(f"Error downloading selected media: {str(e)}")
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

# Google Photos OAuth Routes
@app.route('/google-photos/auth')
def google_photos_auth():
    """Initiate Google Photos OAuth flow"""
    try:
        # Build the redirect URI
        redirect_uri = url_for('google_photos_callback', _external=True)
        
        # Get the authorization URL
        from google_photos import get_auth_url
        auth_url, state = get_auth_url(redirect_uri)
        
        # Store state in session for security
        session['oauth_state'] = state
        
        # Redirect user to Google's OAuth consent screen
        return redirect(auth_url)
    except Exception as e:
        return f"Error initiating OAuth: {str(e)}", 500

@app.route('/google-photos/callback')
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
        redirect_uri = url_for('google_photos_callback', _external=True)
        
        # Handle the OAuth callback
        from google_photos import handle_oauth_callback
        creds = handle_oauth_callback(state, request.url, redirect_uri)
        
        # Clear the state from session
        session.pop('oauth_state', None)
        
        # Redirect to a success page or back to the create post page
        return redirect(url_for('create_post'))
    except Exception as e:
        return f"Error handling OAuth callback: {str(e)}", 500

# About Us Routes
@app.route('/about-us')
@app.route('/about_us')
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

@app.route('/admin/about-us/edit', methods=['GET', 'POST'])
def admin_about_us_edit():
    """Edit the About Us page content"""
    if request.method == 'POST':
        try:
            content = request.form.get('content', '')
            
            # Save to database
            conn = sqlite3.connect('familybook.db')
            cursor = conn.cursor()
            
            # Create table if it doesn't exist
            cursor.execute('''CREATE TABLE IF NOT EXISTS about_us 
                             (id INTEGER PRIMARY KEY, content TEXT, updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
            
            # Insert new content
            cursor.execute('INSERT INTO about_us (content) VALUES (?)', (content,))
            conn.commit()
            conn.close()
            
            flash('About Us page updated successfully!', 'success')
            return flask_redirect(url_for('admin_about_us_edit'))
            
        except Exception as e:
            print(f"Error saving about us content: {str(e)}")
            flash('Error saving content', 'error')
    
    # GET request - show the form
    try:
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
        
        return render_template('admin_about_us_edit.html', content=content)
    except Exception as e:
        print(f"Error loading about us editor: {str(e)}")
        return "Error loading editor", 500


if __name__ == "__main__":
    init_db()
    # Initialize OAuth on startup if configured
    with app.app_context():
        try:
            setup_oauth()
        except Exception as e:
            print(f"OAuth initialization failed at startup: {e}")
    app.run(debug=True)