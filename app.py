import os
import sqlite3
import uuid
from flask import Flask, jsonify, request, render_template, render_template_string, flash, g, abort, session
from google_photos import get_authenticated_service, create_picker_session, poll_picker_session, get_picked_media_items
import time
import json
import base64
from authlib.integrations.flask_client import OAuth
from datetime import datetime, timezone, timedelta
import pytz
from utils.timezone_utils import get_pacific_timezone, get_pacific_now, utc_to_pacific
from utils.url_utils import (
    get_url_prefix, detect_url_prefix, url_for_with_prefix, redirect,
    override_url_for, static_url, upload_url, utility_processor,
    fix_content_urls, content_processor
)
# Media-related imports moved to services.media_service
from services.media_service import (
    ALLOWED_IMAGE_EXTENSIONS, ALLOWED_VIDEO_EXTENSIONS,
    handle_single_media_upload, handle_multiple_image_upload, handle_multiple_media_upload,
    process_google_photos_media, serve_uploaded_file, handle_google_photos_download,
    initialize_upload_folder, extract_images_from_posts, cleanup_orphaned_media
)
from db.database import get_db, close_db, init_db, init_oauth_on_import
from db.queries import (
    get_setting, update_setting, log_activity, log_email, update_email_log,
    get_user_by_magic_token, get_user_by_id, get_all_users, get_users_with_emails,
    create_user, delete_user, toggle_user_admin, update_user_email_notifications,
    update_user_last_login, create_post, get_posts_by_date_range, get_posts_by_tag,
    get_all_posts, get_post_by_id, delete_post, create_comment, get_comments_for_post,
    get_reaction_count, check_user_reaction, toggle_reaction, get_all_filter_tags,
    get_filter_tag_names, create_filter_tag, delete_filter_tag, get_all_settings,
    get_email_template, get_all_email_templates,
    get_email_template_by_id, update_email_template, create_default_email_templates,
    get_user_notification_preferences, create_default_user_notification_preferences,
    update_user_notification_preferences, get_individual_images, update_settings_batch,
    get_activity_logs, get_email_logs, get_email_logs_stats, get_about_us_content,
    update_about_us_content
)
from services.email_service import (
    send_gmail_oauth_email, render_email_template, send_templated_email,
    send_notification_email, send_traditional_smtp_email, send_email_notifications
)
from services.auth_service import (
    setup_oauth, is_oauth_configured, requires_admin_auth,
    redirect_to_admin_login, get_admin_oauth_token
)
from blueprints.main_bp import main_bp
from blueprints.admin_bp import admin_bp

app = Flask(__name__)

# Initialize upload folder and configuration
initialize_upload_folder(app)
app.config['DATABASE'] = os.environ.get('FAMILYBOOK_DATABASE_PATH', 'familybook.db')
app.secret_key = os.environ.get('FAMILYBOOK_SECRET_KEY', 'your-secret-key-change-this-in-production')

# URL configuration for subdirectory deployment

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
def detect_url_prefix_handler():
    """Detect URL prefix from nginx headers"""
    detect_url_prefix()

# OAuth setup
oauth = OAuth(app)
app.oauth = oauth  # Make oauth available for database initialization

# Register URL utility context processors
@app.context_processor
def register_override_url_for():
    return override_url_for()

@app.context_processor
def register_utility_processor():
    return utility_processor()

@app.context_processor
def register_content_processor():
    return content_processor()

# Register database teardown handler
app.teardown_appcontext(close_db)

# Register blueprints
app.register_blueprint(main_bp)
app.register_blueprint(admin_bp)

# OAuth initialization moved to db/database.py
# Call the initialization
init_oauth_on_import(app)

# Media file extension constants moved to services/media_service.py

# Database functions moved to db/database.py and db/queries.py


# init_db function moved to db/database.py

# log_activity function moved to db/queries.py

# Authentication functions moved to services/auth_service.py

# get_setting and update_setting functions moved to db/queries.py


# Main application routes have been moved to blueprints/main_bp.py
# Admin routes have been moved to blueprints/admin_bp.py


if __name__ == "__main__":
    with app.app_context():
        init_db()
        # Initialize OAuth on startup if configured
        try:
            setup_oauth()
        except Exception as e:
            print(f"OAuth initialization failed at startup: {e}")
    app.run(debug=True)