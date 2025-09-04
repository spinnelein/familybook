"""
Email service module for the Familybook application.

This module contains all email-related functionality including Gmail OAuth,
SMTP configuration, email template rendering, logging, and notification preferences.
"""

import smtplib
import email.utils
from flask import render_template_string, url_for, current_app
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from db.database import get_db
from db.queries import get_setting, get_admin_oauth_token, log_email, update_email_log
from utils.timezone_utils import get_pacific_now


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


def send_templated_email(template_name, to_email, user_id=None, **context):
    """Send an email using a template"""
    try:
        subject, html_body, plain_body = render_email_template(template_name, **context)
        
        if not subject:
            print(f"Failed to render template '{template_name}'")
            return False
        
        # Debug email content
        print(f"Sending email '{template_name}' to {to_email}")
        print(f"Subject: {subject}")
        print(f"HTML body length: {len(html_body or '')} chars")
        print(f"Plain body length: {len(plain_body or '')} chars")
        print(f"HTML body starts with: {(html_body or '')[:100]}...")
        
        return send_traditional_smtp_email(to_email, subject, html_body, plain_body, template_name, user_id)
    
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
        
        return send_templated_email(template_name, user['email'], user_id, **context)
    
    except Exception as e:
        print(f"Error sending notification email to user {user_id}: {e}")
        return False



def send_traditional_smtp_email(to_email, subject, html_body, plain_body, template_name=None, user_id=None):
    """Send email using traditional SMTP (fallback method)"""
    # Log the email attempt
    log_id = log_email(to_email, template_name, subject, 'pending', None, user_id)
    
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
            error_msg = "Missing SMTP server or from address"
            print(f"Email sending skipped: {error_msg}")
            if log_id:
                update_email_log(log_id, 'failed', error_msg)
            return False
        
        # Create email
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"{email_from_name} <{email_from_address}>"
        msg['To'] = to_email
        msg['Date'] = email.utils.formatdate()
        
        # Add both plain text and HTML versions
        # Note: Attach plain text first, HTML last (per RFC, last is preferred)
        msg.attach(MIMEText(plain_body, 'plain', 'utf-8'))
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))
        
        # Send email
        server = smtplib.SMTP(smtp_server, smtp_port)
        if smtp_use_tls:
            server.starttls()
        
        # Only authenticate if username and password are provided
        if smtp_username and smtp_password:
            server.login(smtp_username, smtp_password)
        
        server.send_message(msg)
        server.quit()
        
        # Log successful send
        if log_id:
            update_email_log(log_id, 'sent')
        print(f"Email sent successfully to {to_email}")
        return True
        
    except Exception as e:
        error_msg = str(e)
        print(f"SMTP email sending failed: {error_msg}")
        if log_id:
            update_email_log(log_id, 'failed', error_msg)
        return False


def send_email_notifications(post_id, title, content, tags):
    """DEPRECATED: Use send_notification_email with templates instead"""
    print("Warning: send_email_notifications is deprecated. Use templated email system instead.")
    # Legacy function kept for backward compatibility but no longer functional
    return False