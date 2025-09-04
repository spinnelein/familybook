"""
Media service module for the FamilyBook application.

This module handles all media-related operations including:
- File upload processing and validation
- UUID generation for filenames
- Media file management and organization  
- Image/video specific handling and optimization
- Upload folder initialization and configuration
- Orphaned media cleanup
- Media extraction from posts
- Google Photos integration

Constants:
    ALLOWED_IMAGE_EXTENSIONS: Set of allowed image file extensions
    ALLOWED_VIDEO_EXTENSIONS: Set of allowed video file extensions

Main Functions:
    initialize_upload_folder(app): Initialize upload folder during app startup
    handle_single_media_upload(): Handle TinyMCE single file uploads
    handle_multiple_image_upload(): Handle batch image uploads
    handle_multiple_media_upload(): Handle batch media (image/video) uploads
    handle_google_photos_download(): Handle Google Photos media downloads
    serve_uploaded_file(filename): Serve files from upload directory
    cleanup_orphaned_media(): Remove unused media files
    extract_images_from_posts(): Extract media references from post content
"""

import os
import uuid
import requests
import re
import glob
from datetime import datetime
from flask import current_app, jsonify, request, url_for, send_from_directory
from utils.url_utils import url_for_with_prefix


# Constants for allowed file extensions
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'mov', 'avi', 'webm'}


def get_upload_folder():
    """Get the configured upload folder path."""
    return current_app.config['UPLOAD_FOLDER']


def initialize_upload_folder(app):
    """
    Initialize the upload folder with proper handling for symlinks and directories.
    This should be called during application startup.
    
    Args:
        app: Flask application instance
    """
    # Configure uploads folder - can be overridden with environment variable for Synology mounting
    app.config['UPLOAD_FOLDER'] = os.environ.get('FAMILYBOOK_UPLOADS_PATH', 'static/uploads')
    
    upload_path = app.config['UPLOAD_FOLDER']
    
    if os.path.exists(upload_path):
        # Check if it's a symlink (common for Synology/NAS setups)
        if os.path.islink(upload_path):
            if os.path.isdir(upload_path):
                print(f"Using symlinked uploads directory: {upload_path} -> {os.readlink(upload_path)}")
            else:
                print(f"Warning: Symlink {upload_path} points to non-directory")
        elif not os.path.isdir(upload_path):
            # Path exists but is not a directory or symlink - remove it and create directory
            print(f"Warning: {upload_path} exists as a file, removing it to create directory")
            try:
                os.remove(upload_path)
                os.makedirs(upload_path, exist_ok=True)
            except Exception as e:
                print(f"Error removing file and creating directory: {e}")
                raise
        # If it's already a directory (or symlink to directory), we're good
    else:
        # Path doesn't exist, create it (only for non-symlink cases)
        try:
            os.makedirs(upload_path, exist_ok=True)
            print(f"Created uploads directory: {upload_path}")
        except PermissionError as e:
            print(f"Permission error creating uploads folder: {e}")
            print(f"Please create the directory manually or set up symlink: {upload_path}")
            print(f"For Synology: ln -sf /volume1/your-path {upload_path}")
            # Don't raise - let the application start, admin can fix the symlink
            pass
    
    # Also configure max content length for uploads
    app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max upload size


def generate_unique_filename(original_filename, is_video=False):
    """
    Generate a unique filename with UUID to prevent conflicts.
    
    Args:
        original_filename (str): The original filename
        is_video (bool): Whether this is a video file
        
    Returns:
        str: Unique filename with format: {prefix}_{uuid}.{ext}
    """
    if '.' not in original_filename:
        ext = 'jpg' if not is_video else 'mp4'
    else:
        ext = original_filename.rsplit('.', 1)[-1].lower()
    
    prefix = 'vid' if is_video else 'img'
    return f"{prefix}_{uuid.uuid4().hex}.{ext}"


def validate_file_extension(filename, allowed_extensions=None):
    """
    Validate if a file has an allowed extension.
    
    Args:
        filename (str): The filename to validate
        allowed_extensions (set, optional): Set of allowed extensions. 
                                          If None, uses both image and video extensions.
        
    Returns:
        bool: True if extension is allowed, False otherwise
    """
    if not filename or '.' not in filename:
        return False
    
    ext = filename.rsplit('.', 1)[-1].lower()
    
    if allowed_extensions is None:
        allowed_extensions = ALLOWED_IMAGE_EXTENSIONS | ALLOWED_VIDEO_EXTENSIONS
    
    return ext in allowed_extensions


def get_file_type_and_extension(filename, mime_type=None):
    """
    Determine file type and extension from filename and optionally mime type.
    
    Args:
        filename (str): The filename
        mime_type (str, optional): MIME type hint
        
    Returns:
        tuple: (file_type, extension, prefix) where:
               - file_type: 'image' or 'video'
               - extension: file extension without dot
               - prefix: 'img' or 'vid'
    """
    if '.' in filename:
        ext = filename.rsplit('.', 1)[-1].lower()
    else:
        # Fallback based on mime_type if available
        if mime_type:
            if mime_type.startswith('video/'):
                ext = 'mp4'
            else:
                ext = 'jpg'
        else:
            ext = 'jpg'
    
    # Determine if it's a video based on extension or mime type
    is_video = (ext in ALLOWED_VIDEO_EXTENSIONS or 
                (mime_type and mime_type.startswith('video/')))
    
    if is_video:
        return 'video', ext, 'vid'
    else:
        return 'image', ext, 'img'


def save_uploaded_file(file, custom_filename=None):
    """
    Save an uploaded file to the upload directory.
    
    Args:
        file: Flask file upload object
        custom_filename (str, optional): Custom filename to use instead of generating UUID
        
    Returns:
        dict: Dictionary containing:
              - success (bool): Whether save was successful
              - filename (str): Generated/used filename
              - original_name (str): Original filename
              - url (str): URL to access the file
              - type (str): 'image' or 'video'
              - extension (str): File extension
              - error (str): Error message if failed
    """
    try:
        if not file or not file.filename:
            return {'success': False, 'error': 'No file provided'}
        
        # Validate file extension
        if not validate_file_extension(file.filename):
            return {'success': False, 'error': 'Invalid file type'}
        
        # Get file type and extension
        file_type, ext, prefix = get_file_type_and_extension(file.filename)
        
        # Generate filename
        if custom_filename:
            filename = custom_filename
        else:
            filename = generate_unique_filename(file.filename, file_type == 'video')
        
        # Save file
        file_path = os.path.join(get_upload_folder(), filename)
        file.save(file_path)
        
        # Generate URL
        file_url = url_for('uploaded_file', filename=filename, _external=True)
        
        return {
            'success': True,
            'filename': filename,
            'original_name': file.filename,
            'url': file_url,
            'type': file_type,
            'extension': ext
        }
        
    except Exception as e:
        return {'success': False, 'error': str(e)}


def handle_single_media_upload():
    """
    Handle single file upload from TinyMCE or similar editors.
    
    Returns:
        dict: JSON response with success/error status and file info
    """
    file = request.files.get('file')
    if not file:
        return {'error': 'No file', 'status': 400}
    
    # Validate image files only for TinyMCE uploads
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return {'error': 'Invalid file type', 'status': 400}
    
    result = save_uploaded_file(file)
    
    if result['success']:
        return {'location': result['url']}
    else:
        return {'error': result['error'], 'status': 400}


def handle_multiple_image_upload():
    """
    Handle multiple image uploads.
    
    Returns:
        dict: JSON response with uploaded images info
    """
    try:
        files = request.files.getlist('images')
        if not files or all(f.filename == '' for f in files):
            return {'error': 'No files provided', 'status': 400}
        
        uploaded_images = []
        
        for file in files:
            if file and file.filename and file.filename != '':
                # Validate extension
                if not validate_file_extension(file.filename, ALLOWED_IMAGE_EXTENSIONS):
                    continue
                
                result = save_uploaded_file(file)
                if result['success']:
                    uploaded_images.append({
                        'filename': result['filename'],
                        'original_name': result['original_name'],
                        'url': result['url']
                    })
        
        return {
            'success': True,
            'images': uploaded_images,
            'count': len(uploaded_images)
        }
        
    except Exception as e:
        return {'error': f'Upload failed: {str(e)}', 'status': 500}


def handle_multiple_media_upload():
    """
    Handle multiple image and video uploads.
    
    Returns:
        dict: JSON response with uploaded media info
    """
    try:
        files = request.files.getlist('media')
        if not files or all(f.filename == '' for f in files):
            return {'error': 'No files provided', 'status': 400}
        
        uploaded_media = []
        
        for file in files:
            if file and file.filename and file.filename != '':
                # Validate extension for both images and videos
                if not validate_file_extension(file.filename):
                    continue
                
                result = save_uploaded_file(file)
                if result['success']:
                    uploaded_media.append({
                        'filename': result['filename'],
                        'original_name': result['original_name'],
                        'url': result['url'],
                        'type': result['type'],
                        'extension': result['extension']
                    })
        
        return {
            'success': True,
            'media': uploaded_media,
            'count': len(uploaded_media)
        }
        
    except Exception as e:
        return {'error': f'Upload failed: {str(e)}', 'status': 500}


def optimize_image_content(content, ext):
    """
    Optimize image content using PIL if available.
    
    Args:
        content (bytes): Original image content
        ext (str): File extension
        
    Returns:
        bytes: Optimized image content (or original if optimization fails)
    """
    try:
        from PIL import Image
        import io
        
        image = Image.open(io.BytesIO(content))
        
        # Convert to RGB if necessary for JPEG
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
        
        return output.getvalue()
        
    except ImportError:
        # PIL not available, return original content
        return content
    except Exception as e:
        print(f"Error optimizing image: {e}")
        return content


def download_and_save_media_from_url(url, filename, mime_type=None, headers=None):
    """
    Download media from URL and save it to the upload directory.
    
    Args:
        url (str): URL to download from
        filename (str): Original filename hint
        mime_type (str, optional): MIME type of the media
        headers (dict, optional): HTTP headers for the request
        
    Returns:
        dict: Dictionary containing:
              - success (bool): Whether download/save was successful
              - filename (str): Generated filename
              - original_name (str): Original filename
              - url (str): URL to access the saved file
              - type (str): 'image' or 'video'
              - extension (str): File extension
              - original_size (int): Size of downloaded content
              - processed_size (int): Size after processing
              - error (str): Error message if failed
    """
    try:
        # Download the file
        response = requests.get(url, headers=headers or {})
        
        if response.status_code != 200:
            return {'success': False, 'error': f'Failed to download: HTTP {response.status_code}'}
        
        original_size = len(response.content)
        
        # Determine file type and extension
        file_type, ext, prefix = get_file_type_and_extension(filename, mime_type)
        
        # Generate unique filename
        unique_filename = f"{prefix}_{uuid.uuid4().hex}.{ext}"
        file_path = os.path.join(get_upload_folder(), unique_filename)
        
        # Process content (optimize images)
        processed_content = response.content
        if file_type == 'image' and ext in ['jpg', 'jpeg', 'png', 'webp']:
            processed_content = optimize_image_content(response.content, ext)
        
        processed_size = len(processed_content)
        
        # Save the file
        with open(file_path, 'wb') as f:
            f.write(processed_content)
        
        # Generate URL
        file_url = url_for('uploaded_file', filename=unique_filename, _external=True)
        
        return {
            'success': True,
            'filename': unique_filename,
            'original_name': filename,
            'url': file_url,
            'type': file_type,
            'extension': ext,
            'original_size': original_size,
            'processed_size': processed_size
        }
        
    except Exception as e:
        return {'success': False, 'error': str(e)}


def process_google_photos_media(selected_items, auth_headers=None):
    """
    Process and download selected media from Google Photos Picker.
    
    Args:
        selected_items (list): List of selected media items from Google Photos
        auth_headers (dict, optional): Authorization headers for API calls
        
    Returns:
        dict: Dictionary containing:
              - success (bool): Whether processing was successful
              - media (list): List of processed media items
              - count (int): Number of successfully processed items
              - totalOriginalSize (int): Total size of original files
              - totalProcessedSize (int): Total size after processing
              - error (str): Error message if failed
    """
    try:
        if not selected_items:
            return {'success': False, 'error': 'No media provided'}
        
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
                
                # Use appropriate download parameter based on media type
                if mime_type.startswith('video/'):
                    download_url = f"{base_url}=dv"  # Download original video
                else:
                    download_url = f"{base_url}=d"   # Download original image
                
                # Download and save the media
                result = download_and_save_media_from_url(
                    download_url, filename, mime_type, auth_headers
                )
                
                if result['success']:
                    total_original_size += result['original_size']
                    total_processed_size += result['processed_size']
                    
                    imported_media.append({
                        'filename': result['filename'],
                        'original_name': result['original_name'],
                        'url': result['url'],
                        'type': result['type'],
                        'extension': result['extension'],
                        'google_photo_id': item.get('id', media_file.get('id', 'unknown'))
                    })
                    
                    print(f"Successfully imported {result['type']}: {result['filename']}")
                    
            except Exception as item_error:
                print(f"Error processing Google Photos item: {str(item_error)}")
                continue
        
        return {
            'success': True,
            'media': imported_media,
            'count': len(imported_media),
            'totalOriginalSize': total_original_size,
            'totalProcessedSize': total_processed_size
        }
        
    except Exception as e:
        print(f"Error processing Google Photos media: {str(e)}")
        return {'success': False, 'error': str(e)}


def get_media_stats():
    """
    Get statistics about uploaded media files.
    
    Returns:
        dict: Dictionary containing media statistics
    """
    try:
        upload_dir = get_upload_folder()
        
        stats = {
            'total_files': 0,
            'total_size': 0,
            'images': {'count': 0, 'size': 0},
            'videos': {'count': 0, 'size': 0}
        }
        
        if os.path.exists(upload_dir):
            for filename in os.listdir(upload_dir):
                file_path = os.path.join(upload_dir, filename)
                if os.path.isfile(file_path):
                    file_size = os.path.getsize(file_path)
                    stats['total_files'] += 1
                    stats['total_size'] += file_size
                    
                    if validate_file_extension(filename, ALLOWED_IMAGE_EXTENSIONS):
                        stats['images']['count'] += 1
                        stats['images']['size'] += file_size
                    elif validate_file_extension(filename, ALLOWED_VIDEO_EXTENSIONS):
                        stats['videos']['count'] += 1
                        stats['videos']['size'] += file_size
        
        return stats
        
    except Exception as e:
        print(f"Error getting media stats: {str(e)}")
        return {'total_files': 0, 'total_size': 0, 'images': {'count': 0, 'size': 0}, 'videos': {'count': 0, 'size': 0}}


def serve_uploaded_file(filename):
    """
    Serve an uploaded file from the upload directory.
    
    Args:
        filename (str): The filename to serve
        
    Returns:
        Response: Flask response serving the file
    """
    return send_from_directory(get_upload_folder(), filename)


def handle_google_photos_download():
    """
    Handle the download of selected media from Google Photos Picker.
    This is the route handler for /api/google-photos/download-selected.
    
    Returns:
        tuple: JSON response and status code
    """
    try:
        data = request.get_json()
        selected_items = data.get('selectedItems', [])
        
        if not selected_items:
            return jsonify({'success': False, 'error': 'No media provided'}), 400
        
        # Get authentication headers if available
        auth_headers = None
        try:
            from google_photos import get_authenticated_service
            service = get_authenticated_service()
            if hasattr(service, '_http') and hasattr(service._http, 'credentials'):
                creds = service._http.credentials
                auth_headers = {'Authorization': f'Bearer {creds.token}'}
        except:
            auth_headers = {}
        
        # Process the media using existing function
        result = process_google_photos_media(selected_items, auth_headers)
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 500
            
    except Exception as e:
        print(f"Error in handle_google_photos_download: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


def extract_images_from_posts():
    """
    Extract images from post content and populate images table.
    This is used for legacy data migration.
    """
    from db.database import get_db
    
    with current_app.app_context():
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
                            file_path = os.path.join(get_upload_folder(), filename)
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


def cleanup_orphaned_media():
    """
    Remove uploaded media files that aren't referenced in any posts.
    
    Returns:
        int: Number of orphaned files deleted
    """
    from db.database import get_db
    
    try:
        with current_app.app_context():
            db = get_db()
            
            # Get all uploaded files
            upload_dir = get_upload_folder()
            all_files = set()
            for pattern in ['*.jpg', '*.jpeg', '*.png', '*.gif', '*.webp', '*.mp4', '*.mov', '*.avi', '*.mkv', '*.webm']:
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
            print(f"Files in use: {sorted(list(used_files)[:10])}..." if used_files else "No files in use")
            
            # Find orphaned files
            orphaned_files = all_files - used_files
            
            if orphaned_files:
                print(f"Orphaned files to delete: {sorted(list(orphaned_files)[:10])}...")
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