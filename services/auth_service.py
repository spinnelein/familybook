"""
Authentication Service Module

This module handles all authentication-related functionality including:
- Admin authentication checks
- OAuth configuration and setup
- Authentication redirects and helpers
"""

from flask import session, request
from authlib.integrations.flask_client import OAuth
from utils.url_utils import redirect
from db.queries import get_setting, get_user_by_id
from db.database import get_db


def setup_oauth():
    """Configure OAuth client with database settings"""
    from flask import current_app
    # Get the oauth instance from the app
    oauth = current_app.oauth
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


def is_oauth_configured():
    """Check if OAuth is configured"""
    oauth_client_id = get_setting('oauth_client_id', '')
    oauth_client_secret = get_setting('oauth_client_secret', '')
    return bool(oauth_client_id and oauth_client_secret)


def requires_admin_auth():
    """Check if admin authentication is required (only if OAuth is configured)"""
    if not is_oauth_configured():
        return False  # Open access when OAuth not configured
    
    return 'admin_user_id' not in session


def redirect_to_admin_login():
    """Helper function to redirect to admin login while preserving subpath"""
    script_name = request.environ.get('SCRIPT_NAME', '')
    return redirect(f'{script_name}/admin/login')


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