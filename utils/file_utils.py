"""
File utility functions for the FamilyBook application.

This module contains general file utility functions.
Note: Media-specific functions have been moved to services/media_service.py
"""

import os


def allowed_file(filename, allowed_exts):
    """
    Check if a file has an allowed extension.
    
    Note: This function is deprecated. Use validate_file_extension() from 
    services.media_service instead.
    
    Args:
        filename (str): Name of the file to check
        allowed_exts (set or list): Set/list of allowed file extensions
        
    Returns:
        bool: True if file has allowed extension, False otherwise
    """
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_exts