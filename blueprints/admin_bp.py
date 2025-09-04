"""
Admin Blueprint - Contains all admin-related routes
"""
import sqlite3
import uuid
from flask import Blueprint, jsonify, request, render_template, render_template_string, flash, session, abort
from db.database import get_db
from db.queries import (
    get_setting, update_setting, log_activity,
    get_user_by_id, get_all_users, create_user, delete_user, 
    toggle_user_admin, update_user_email_notifications,
    get_all_filter_tags, create_filter_tag, delete_filter_tag,
    get_all_email_templates, get_email_template_by_id, update_email_template,
    create_default_email_templates, get_activity_logs, get_email_logs,
    get_about_us_content, update_about_us_content
)
from services.email_service import send_notification_email, send_traditional_smtp_email
from services.auth_service import (
    setup_oauth, is_oauth_configured, requires_admin_auth,
    redirect_to_admin_login, get_admin_oauth_token
)
from utils.url_utils import url_for_with_prefix, redirect

# Create the blueprint
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

@admin_bp.route('/login')
def admin_login():
    """Admin login page"""
    db = get_db()
    
    # If OAuth is not configured, redirect directly to admin console
    if not is_oauth_configured():
        flash('OAuth not configured. Direct access granted for setup.', 'info')
        return redirect(url_for_with_prefix('admin.admin_console'))
    
    oauth_configured = is_oauth_configured()
    return render_template('admin_login.html', oauth_configured=oauth_configured)

@admin_bp.route('/setup', methods=['GET', 'POST'])
def admin_setup():
    """Setup route for initial OAuth configuration (no auth required)"""
    db = get_db()
    
    # Check if OAuth is already configured
    oauth_client_id = get_setting('oauth_client_id', '')
    oauth_client_secret = get_setting('oauth_client_secret', '')
    
    if oauth_client_id and oauth_client_secret:
        flash('OAuth is already configured. Please use the login page.', 'info')
        return redirect(url_for_with_prefix('admin.admin_login'))
    
    if request.method == 'POST':
        # Update OAuth settings
        oauth_settings = ['oauth_client_id', 'oauth_client_secret', 'oauth_redirect_uri']
        
        for setting_key in oauth_settings:
            if setting_key in request.form:
                value = request.form[setting_key]
                update_setting(setting_key, value)
        
        flash('OAuth configured successfully! You can now login.', 'success')
        return redirect(url_for_with_prefix('admin.admin_login'))
    
    # Get current settings for display
    settings = {}
    all_settings = db.execute('SELECT key, value, description FROM settings').fetchall()
    for setting in all_settings:
        settings[setting['key']] = {
            'value': setting['value'],
            'description': setting['description']
        }
    
    return render_template('admin_setup.html', settings=settings)

@admin_bp.route('/oauth/login')
def oauth_login():
    """OAuth login route"""
    from app import oauth  # Import oauth from main app
    
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
        return redirect(url_for_with_prefix('admin.admin_login'))
    
    redirect_uri = get_setting('oauth_redirect_uri', url_for_with_prefix('admin.oauth_callback', _external=True))
    return oauth.google.authorize_redirect(redirect_uri)

@admin_bp.route('/oauth/callback')
def oauth_callback():
    """OAuth callback route"""
    from app import oauth  # Import oauth from main app
    
    setup_oauth()
    if not hasattr(oauth, 'google'):
        flash('OAuth not configured.', 'danger')
        return redirect(url_for_with_prefix('admin.admin_login'))
    
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
                return redirect(url_for_with_prefix('admin.admin_console'))
            else:
                flash('Access denied. Only admin users can access the admin console.', 'danger')
                return redirect(url_for_with_prefix('admin.admin_login'))
        else:
            flash('Failed to get user information from Google.', 'danger')
            return redirect(url_for_with_prefix('admin.admin_login'))
            
    except Exception as e:
        print(f"OAuth callback error: {e}")
        flash('Authentication failed.', 'danger')
        return redirect(url_for_with_prefix('admin.admin_login'))

@admin_bp.route('/logout')
def admin_logout():
    """Admin logout route"""
    session.pop('admin_user_id', None)
    session.pop('admin_user_email', None) 
    session.pop('admin_user_name', None)
    flash('Logged out successfully.', 'success')
    return redirect_to_admin_login()

@admin_bp.route('/console', methods=['GET', 'POST'])
def admin_console():
    """Admin console page (protected only when OAuth is configured)"""
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
        return redirect(url_for_with_prefix('admin.admin_console'))

    users = db.execute('SELECT * FROM users').fetchall()
    filter_tags = db.execute('SELECT * FROM filter_tags ORDER BY name').fetchall()
    oauth_configured = is_oauth_configured()
    return render_template('admin_console.html', users=users, filter_tags=filter_tags, oauth_configured=oauth_configured)

@admin_bp.route('/users/remove/<int:user_id>', methods=['POST'])
def remove_user(user_id):
    """Remove user"""
    # Check if admin authentication is required
    if requires_admin_auth():
        return redirect_to_admin_login()
    
    db = get_db()
    db.execute('DELETE FROM users WHERE id = ?', (user_id,))
    db.commit()
    flash('User removed.', 'info')
    return redirect(url_for_with_prefix('admin.admin_console'))

@admin_bp.route('/users/toggle-admin/<int:user_id>', methods=['POST'])
def toggle_admin_status(user_id):
    """Toggle admin status"""
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

@admin_bp.route('/users/update-notifications/<int:user_id>', methods=['POST'])
def update_user_notifications(user_id):
    """Update user email notification preferences"""
    # Check if admin authentication is required
    if requires_admin_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    db = get_db()
    email_notifications = request.form.get('email_notifications', 'all')
    
    db.execute('UPDATE users SET email_notifications = ? WHERE id = ?', (email_notifications, user_id))
    db.commit()
    
    return jsonify({'success': True})

@admin_bp.route('/tags/add', methods=['POST'])
def add_filter_tag():
    """Add filter tag"""
    # Check if admin authentication is required
    if requires_admin_auth():
        return redirect_to_admin_login()
    
    db = get_db()
    name = request.form.get('name', '').strip().lower()
    display_name = request.form.get('display_name', '').strip()
    color = request.form.get('color', '#3b82f6')
    
    if not name or not display_name:
        flash('Tag name and display name are required!', 'danger')
        return redirect(url_for_with_prefix('admin.admin_console'))
    
    try:
        db.execute('INSERT INTO filter_tags (name, display_name, color) VALUES (?, ?, ?)',
                  (name, display_name, color))
        db.commit()
        flash('Filter tag added!', 'success')
    except sqlite3.IntegrityError:
        flash('Tag name already exists!', 'danger')
    
    return redirect(url_for_with_prefix('admin.admin_console'))

@admin_bp.route('/tags/remove/<int:tag_id>', methods=['POST'])
def remove_filter_tag(tag_id):
    """Remove filter tag"""
    # Check if admin authentication is required
    if requires_admin_auth():
        return redirect_to_admin_login()
    
    db = get_db()
    db.execute('DELETE FROM filter_tags WHERE id = ?', (tag_id,))
    db.commit()
    flash('Filter tag removed!', 'info')
    return redirect(url_for_with_prefix('admin.admin_console'))

@admin_bp.route('/settings', methods=['GET', 'POST'])
def admin_settings():
    """Settings page for SMTP configuration"""
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
        return redirect(url_for_with_prefix('admin.admin_settings'))
    
    # Get all settings for display
    settings = {}
    all_settings = db.execute('SELECT key, value, description FROM settings').fetchall()
    for setting in all_settings:
        settings[setting['key']] = {
            'value': setting['value'],
            'description': setting['description']
        }
    
    # Generate email stats for the template using email_logs table
    try:
        # Get today's emails count
        today_emails = db.execute('''
            SELECT COUNT(*) as count FROM email_logs 
            WHERE date(sent_at) = date('now', 'localtime')
            AND status = 'sent'
        ''').fetchone()
        
        # Get yesterday's emails count
        yesterday_emails = db.execute('''
            SELECT COUNT(*) as count FROM email_logs 
            WHERE date(sent_at) = date('now', '-1 day', 'localtime')
            AND status = 'sent'
        ''').fetchone()
        
        # Get users who might be rate limited (sent more than 10 emails today)
        limited_users = db.execute('''
            SELECT u.name, u.email, COUNT(el.id) as email_count
            FROM email_logs el
            JOIN users u ON el.user_id = u.id
            WHERE date(el.sent_at) = date('now', 'localtime')
            AND el.status = 'sent'
            GROUP BY u.id, u.name, u.email
            HAVING COUNT(el.id) >= 10
            ORDER BY email_count DESC
        ''').fetchall()
        
        email_stats = {
            'today_emails': today_emails['count'] if today_emails else 0,
            'yesterday_emails': yesterday_emails['count'] if yesterday_emails else 0,
            'limited_users': [{'name': row['name'], 'email': row['email'], 'count': row['email_count']} 
                            for row in limited_users] if limited_users else []
        }
    except Exception as e:
        print(f"Error calculating email statistics: {e}")
        # Fall back to placeholder values if there's an error
        email_stats = {
            'today_emails': 0,
            'yesterday_emails': 0,
            'limited_users': []
        }
    
    return render_template('admin_settings.html', settings=settings, email_stats=email_stats)

@admin_bp.route('/email-templates')
def admin_email_templates():
    """Email Templates Management"""
    # Check if admin authentication is required
    if requires_admin_auth():
        return redirect_to_admin_login()
    
    db = get_db()
    templates = db.execute('SELECT * FROM email_templates ORDER BY template_name').fetchall()
    return render_template('admin_email_templates.html', templates=templates)

@admin_bp.route('/email-templates/edit/<int:template_id>', methods=['GET', 'POST'])
def edit_email_template(template_id):
    """Edit email template"""
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
        return redirect(url_for_with_prefix('admin.admin_email_templates'))
    
    # Get template for editing
    template = db.execute('SELECT * FROM email_templates WHERE id = ?', (template_id,)).fetchone()
    if not template:
        abort(404)
    
    return render_template('admin_email_template_edit.html', template=template)

@admin_bp.route('/email-templates/test/<int:template_id>', methods=['POST'])
def test_email_template(template_id):
    """Test email template"""
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
            'magic_link': url_for_with_prefix('main.posts', magic_token='sample-token', _external=True),
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

@admin_bp.route('/email-templates/create-defaults', methods=['POST'])
def create_default_email_templates():
    """Create default email templates"""
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

@admin_bp.route('/test-email', methods=['POST'])
def test_email():
    """Test email functionality"""
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

@admin_bp.route('/about-us/edit', methods=['GET', 'POST'])
def admin_about_us_edit():
    """Edit the About Us page content"""
    if request.method == 'POST':
        try:
            content = request.form.get('content', '')
            
            # Save to database
            db = get_db()
            
            # Create table if it doesn't exist
            db.execute('''CREATE TABLE IF NOT EXISTS about_us 
                         (id INTEGER PRIMARY KEY, content TEXT, updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
            
            # Insert new content
            db.execute('INSERT INTO about_us (content) VALUES (?)', (content,))
            db.commit()
            
            flash('About Us page updated successfully!', 'success')
            return redirect(url_for_with_prefix('admin.admin_about_us_edit'))
            
        except Exception as e:
            print(f"Error saving about us content: {str(e)}")
            flash('Error saving content', 'error')
    
    # GET request - show the form
    try:
        db = get_db()
        
        # Create table if it doesn't exist
        db.execute('''CREATE TABLE IF NOT EXISTS about_us 
                     (id INTEGER PRIMARY KEY, content TEXT, updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        # Get the latest content
        result = db.execute('SELECT content FROM about_us ORDER BY id DESC LIMIT 1').fetchone()
        
        content = result['content'] if result else '<h2>Welcome to Our Family</h2><p>Share your family story here...</p>'
        
        return render_template('admin_about_us_edit.html', content=content)
    except Exception as e:
        print(f"Error loading about us editor: {str(e)}")
        return "Error loading editor", 500

@admin_bp.route('/activity-log')
def admin_activity_log():
    """Display activity log page"""
    # Check if admin authentication is required
    if requires_admin_auth():
        return redirect_to_admin_login()
    
    try:
        db = get_db()
        
        # Get filter parameters
        action_filter = request.args.get('action', '')
        user_filter = request.args.get('user', '')
        days_filter = int(request.args.get('days', 7))
        page = int(request.args.get('page', 1))
        per_page = 50
        offset = (page - 1) * per_page
        
        # Build filter conditions
        conditions = []
        params = []
        
        if action_filter:
            conditions.append("action_type = ?")
            params.append(action_filter)
        
        if user_filter:
            conditions.append("user_name LIKE ?")
            params.append(f"%{user_filter}%")
        
        conditions.append("created >= datetime('now', '-{} days')".format(days_filter))
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        # Get activity log entries
        query = f'''SELECT * FROM activity_log 
                   WHERE {where_clause}
                   ORDER BY created DESC 
                   LIMIT ? OFFSET ?'''
        params.extend([per_page, offset])
        
        activities = db.execute(query, params).fetchall()
        
        # Get total count for pagination
        count_query = f"SELECT COUNT(*) as total FROM activity_log WHERE {where_clause}"
        count_params = params[:-2]  # Remove LIMIT and OFFSET params
        total = db.execute(count_query, count_params).fetchone()['total']
        
        # Get unique action types for filter
        action_types = db.execute('SELECT DISTINCT action_type FROM activity_log ORDER BY action_type').fetchall()
        
        # Get unique users for filter
        users = db.execute('SELECT DISTINCT user_name FROM activity_log WHERE user_name IS NOT NULL ORDER BY user_name').fetchall()
        
        # Calculate pagination info
        total_pages = (total + per_page - 1) // per_page
        has_prev = page > 1
        has_next = page < total_pages
        
        return render_template('admin_activity_log.html',
                             activities=activities,
                             action_types=action_types,
                             users=users,
                             current_filters={
                                 'action': action_filter,
                                 'user': user_filter,
                                 'days': days_filter
                             },
                             pagination={
                                 'page': page,
                                 'total_pages': total_pages,
                                 'has_prev': has_prev,
                                 'has_next': has_next,
                                 'total': total
                             })
        
    except Exception as e:
        print(f"Error loading activity log: {str(e)}")
        return "Error loading activity log", 500

@admin_bp.route('/email-logs')
def admin_email_logs():
    """Display comprehensive email logs for debugging and statistics"""
    # Check admin authentication
    if requires_admin_auth():
        return redirect(url_for_with_prefix('admin.admin_login'))
    
    try:
        db = get_db()
        
        # Get filter parameters
        status_filter = request.args.get('status', '').strip()
        template_filter = request.args.get('template', '').strip()
        recipient_filter = request.args.get('recipient', '').strip()
        days_filter = int(request.args.get('days', 7))
        page = int(request.args.get('page', 1))
        per_page = 50
        offset = (page - 1) * per_page
        
        # Build WHERE clause
        where_conditions = []
        params = []
        
        if status_filter:
            where_conditions.append("status = ?")
            params.append(status_filter)
        
        if template_filter:
            where_conditions.append("template_name = ?")
            params.append(template_filter)
        
        if recipient_filter:
            where_conditions.append("recipient_email LIKE ?")
            params.append(f"%{recipient_filter}%")
        
        # Time filter
        where_conditions.append("sent_at >= datetime('now', '-{} days')".format(days_filter))
        
        where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"
        
        # Get email logs with user names
        query = f'''SELECT el.*, u.name as user_name
                   FROM email_logs el
                   LEFT JOIN users u ON el.user_id = u.id
                   WHERE {where_clause}
                   ORDER BY el.sent_at DESC
                   LIMIT ? OFFSET ?'''
        
        params.extend([per_page, offset])
        email_logs = db.execute(query, params).fetchall()
        
        # Get total count for pagination
        count_query = f"SELECT COUNT(*) as total FROM email_logs WHERE {where_clause}"
        count_params = params[:-2]  # Remove LIMIT and OFFSET params
        total = db.execute(count_query, count_params).fetchone()['total']
        
        # Get filter options
        statuses = db.execute('SELECT DISTINCT status FROM email_logs ORDER BY status').fetchall()
        templates = db.execute('SELECT DISTINCT template_name FROM email_logs WHERE template_name IS NOT NULL ORDER BY template_name').fetchall()
        
        # Calculate pagination info
        total_pages = (total + per_page - 1) // per_page
        has_prev = page > 1
        has_next = page < total_pages
        
        # Get summary statistics
        stats = {
            'total_sent': db.execute("SELECT COUNT(*) as count FROM email_logs WHERE status = 'sent'").fetchone()['count'],
            'total_failed': db.execute("SELECT COUNT(*) as count FROM email_logs WHERE status = 'failed'").fetchone()['count'],
            'today_sent': db.execute("SELECT COUNT(*) as count FROM email_logs WHERE status = 'sent' AND date(sent_at) = date('now', 'localtime')").fetchone()['count'],
            'yesterday_sent': db.execute("SELECT COUNT(*) as count FROM email_logs WHERE status = 'sent' AND date(sent_at) = date('now', 'localtime', '-1 day')").fetchone()['count']
        }
        
        return render_template('admin_email_logs.html',
                             email_logs=email_logs,
                             statuses=statuses,
                             templates=templates,
                             stats=stats,
                             current_filters={
                                 'status': status_filter,
                                 'template': template_filter,
                                 'recipient': recipient_filter,
                                 'days': days_filter
                             },
                             pagination={
                                 'page': page,
                                 'total_pages': total_pages,
                                 'has_prev': has_prev,
                                 'has_next': has_next,
                                 'total': total
                             })
        
    except Exception as e:
        print(f"Error loading email logs: {str(e)}")
        return "Error loading email logs", 500