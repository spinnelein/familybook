# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

**Run the application:**
```bash
python app.py
```
The Flask app runs in debug mode by default on localhost:5000.

**Install dependencies:**
```bash
pip install -r requirements.txt
```

**Database initialization:**
The database is automatically initialized when running `app.py`. Tables are created using the `init_db()` function.

**Database management:**
- Check tables: `python tablecheck.py`
- Create user table migration: `python migrations/create\ user\ table.py`
- Manual table creation: `python maketable.py`

## Architecture Overview

This is a Flask-based family photo sharing application with the following key components:

### Core Application Structure
- **app.py**: Main Flask application with direct SQLite integration (legacy approach)
- **models.py**: SQLAlchemy models for newer functionality (User, Post, Comment, Tag, ImportedPhoto)
- **extensions.py**: Flask extensions configuration
- **config.py**: Application configuration settings

### Database Architecture
The application uses a **dual database approach**:
1. **Direct SQLite** (familybook.db) - Used by app.py for posts table
2. **SQLAlchemy ORM** (site.db) - Used by models.py for user management and newer features

Key tables:
- `posts` (direct SQLite): title, content, image_filename, video_filename, created
- `users` (SQLAlchemy): email, name, is_admin, magic_token
- `comments`, `tags`, `post_tags` (SQLAlchemy): For future social features

### Authentication & Access Control
- **Magic link system**: Users access posts via `/posts/<magic_token>` URLs
- **Admin interface**: `/admin/users` for user management
- **No traditional login**: Uses unique tokens instead of passwords

### Media Handling
- **Upload directory**: `static/uploads/` for user-uploaded images and videos
- **TinyMCE integration**: Rich text editor with image upload support
- **Google Photos integration**: `google_photos.py` for importing photos from Google Photos API
- **File naming**: UUIDs prevent filename conflicts (e.g., `img_uuid.jpg`, `vid_uuid.mp4`)

### Key Features
- **Post creation**: Rich text posts with image/video attachments
- **Multi-image upload**: Batch upload functionality for multiple images
- **Magic link sharing**: Secure, tokenized access to family posts
- **Google Photos import**: Automated photo importing from Google Photos

### Template Structure
- `create_post.html`: Post creation form with TinyMCE
- `posts.html`: Main feed for viewing posts (requires magic token)
- `manage_users.html`: Admin interface for user management
- `posts_feed.html`: Alternative post display template

### Google Photos Integration (Updated 2024)
- **Legacy API Removed**: Google changed Photos API in 2024 - apps can only see photos they uploaded
- **New Approach**: Users download photos from photos.google.com and upload via device picker
- **User Flow**: "Browse Google Photos" button explains the process and opens photos.google.com
- **Files**: Old backend API routes removed, frontend shows helpful migration guidance

## Important Notes

- The application mixes direct SQLite queries (app.py) with SQLAlchemy ORM (models.py)
- Secret key is hardcoded in app.py - should be moved to environment variable
- Debug mode is enabled by default - disable for production
- Magic tokens provide security through obscurity rather than traditional authentication
- TinyMCE editor is included locally in `static/tinymce/`