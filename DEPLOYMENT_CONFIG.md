# Familybook Deployment Configuration

This application now supports both local development and subdirectory deployment (e.g., home.slugranch.org/familybook/).

## Configuration

The application uses environment variables for configuration. Copy `.env.example` to `.env` and update as needed.

### Key Environment Variables

- `FAMILYBOOK_URL_PREFIX`: Set to `/familybook` for subdirectory deployment, leave empty for local development
- `FAMILYBOOK_DATABASE_PATH`: Path to SQLite database file
- `FAMILYBOOK_UPLOADS_PATH`: Path to uploads directory (can be mounted from NAS)
- `FAMILYBOOK_SECRET_KEY`: Secret key for Flask sessions (MUST be changed in production)

## Local Development

For local development at `localhost:5000`:

```bash
# No environment variables needed, or use:
export FAMILYBOOK_URL_PREFIX=""
python app.py
```

## Production Deployment

For deployment at `home.slugranch.org/familybook/`:

```bash
export FAMILYBOOK_URL_PREFIX="/familybook"
export FAMILYBOOK_SECRET_KEY="your-secure-secret-key"
# Add other environment variables as needed
```

### With systemd service

Add environment variables to your service file:

```ini
[Service]
Environment="FAMILYBOOK_URL_PREFIX=/familybook"
Environment="FAMILYBOOK_SECRET_KEY=your-secure-secret-key"
Environment="FAMILYBOOK_DATABASE_PATH=/var/www/familybook/data/familybook.db"
Environment="FAMILYBOOK_UPLOADS_PATH=/mnt/synology/familybook/uploads"
```

### With Apache/WSGI

Set environment variables in your Apache configuration:

```apache
SetEnv FAMILYBOOK_URL_PREFIX /familybook
SetEnv FAMILYBOOK_SECRET_KEY your-secure-secret-key
```

## How It Works

1. **URL Generation**: The app overrides Flask's `url_for()` to automatically prepend the URL prefix
2. **Static Files**: Static and upload URLs are automatically adjusted based on the prefix
3. **Content Processing**: Images and links in post content are automatically updated with the correct prefix
4. **API Endpoints**: All AJAX/fetch calls in templates use `url_for()` for proper URL generation

## Testing

To test subdirectory deployment locally:

```bash
export FAMILYBOOK_URL_PREFIX="/familybook"
python app.py
```

Then access the app at `http://localhost:5000/familybook/`

Note: The development server doesn't actually serve at the subdirectory, but all generated URLs will include the prefix, simulating production behavior.