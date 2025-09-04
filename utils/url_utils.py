"""
URL utilities for subdirectory deployment support.

Handles URL prefix detection and URL generation for the familybook application
to support deployment in subdirectories (e.g., /familybook/).
"""

import os
from flask import url_for as flask_url_for, redirect as flask_redirect, has_request_context, request, current_app


def get_url_prefix():
    """
    Get the URL prefix for subdirectory deployment.
    
    Returns:
        str: The URL prefix (e.g., '/familybook') or empty string if deployed at root
    """
    # First try environment variable
    env_prefix = os.environ.get('FAMILYBOOK_URL_PREFIX', '')
    if env_prefix:
        return env_prefix
    
    # Try to detect from nginx proxy headers during request context
    try:
        if has_request_context():
            script_name = request.environ.get('HTTP_X_SCRIPT_NAME') or request.environ.get('SCRIPT_NAME', '')
            if script_name and script_name != '/':
                return script_name
    except:
        pass
    
    return ''


def detect_url_prefix():
    """
    Detect URL prefix from nginx X-Script-Name header and update app config.
    This is typically called as a before_request handler.
    """
    script_name = request.environ.get('HTTP_X_SCRIPT_NAME') or request.environ.get('SCRIPT_NAME', '')
    if script_name and script_name != '/' and script_name != current_app.config.get('URL_PREFIX', ''):
        current_app.config['URL_PREFIX'] = script_name
        current_app.config['APPLICATION_ROOT'] = script_name


def url_for_with_prefix(endpoint, **values):
    """
    Generate URLs that work with subdirectory deployment.
    
    Args:
        endpoint: Flask endpoint name
        **values: URL parameters
        
    Returns:
        str: URL with proper prefix for subdirectory deployment
    """
    # Generate the URL normally
    url = flask_url_for(endpoint, **values)
    
    # Don't modify external URLs (they already contain the full domain and path)
    if values.get('_external', False) or url.startswith(('http://', 'https://')):
        return url
    
    # If we have a URL prefix and the URL doesn't already include it, prepend it
    url_prefix = current_app.config.get('URL_PREFIX', '')
    if url_prefix and not url.startswith(url_prefix):
        url = url_prefix + url
    return url


def redirect(location, code=302):
    """
    Redirect that works with subdirectory deployment.
    
    Args:
        location: Redirect location
        code: HTTP status code for redirect (default: 302)
        
    Returns:
        Flask redirect response
    """
    # If the location is a relative URL starting with /, prepend the prefix
    url_prefix = current_app.config.get('URL_PREFIX', '')
    if location.startswith('/') and url_prefix and not location.startswith(url_prefix):
        location = url_prefix + location
    return flask_redirect(location, code)


def override_url_for():
    """
    Context processor to override Flask's url_for in templates.
    
    Returns:
        dict: Template context with custom url_for function
    """
    return dict(url_for=url_for_with_prefix)


def static_url(filename):
    """
    Generate URLs for static files that work with subdirectory deployment.
    
    Args:
        filename: Static file name
        
    Returns:
        str: URL to static file with proper prefix
    """
    url_prefix = current_app.config.get('URL_PREFIX', '')
    if url_prefix:
        return url_prefix + '/static/' + filename
    return '/static/' + filename


def upload_url(filename):
    """
    Generate URLs for uploaded files that work with subdirectory deployment.
    
    Args:
        filename: Uploaded file name
        
    Returns:
        str: URL to uploaded file with proper prefix
    """
    url_prefix = current_app.config.get('URL_PREFIX', '')
    if url_prefix:
        return url_prefix + '/uploads/' + filename
    return '/uploads/' + filename


def utility_processor():
    """
    Context processor to add URL utility functions to template context.
    
    Returns:
        dict: Template context with static_url and upload_url functions
    """
    return dict(static_url=static_url, upload_url=upload_url)


def fix_content_urls(content):
    """
    Fix image and file URLs in post content for subdirectory deployment.
    
    Args:
        content: HTML content with potential URLs to fix
        
    Returns:
        str: Content with URLs fixed for subdirectory deployment
    """
    if not content:
        return content
        
    url_prefix = current_app.config.get('URL_PREFIX', '')
    if not url_prefix:
        return content
    
    import re
    # Fix image sources - handle both /uploads/ and /static/uploads/
    content = re.sub(
        r'src=["\']/?(?:static/)?uploads/',
        f'src="{url_prefix}/uploads/',
        content
    )
    # Fix any other static references
    content = re.sub(
        r'(?:href|src)=["\']/?static/',
        f'src="{url_prefix}/static/',
        content
    )
    return content


def content_processor():
    """
    Context processor to add content processing functions to template context.
    
    Returns:
        dict: Template context with fix_content_urls function
    """
    return dict(fix_content_urls=fix_content_urls)