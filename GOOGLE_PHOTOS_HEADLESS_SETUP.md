# Google Photos OAuth Setup for Headless Server

When deploying the familybook application on a headless Ubuntu server, the Google Photos OAuth authentication needs to be handled differently since there's no local browser to open.

## The Problem

The original implementation uses `flow.run_local_server()` which tries to open a browser on the server itself. This fails on headless servers.

## The Solution

The updated implementation uses a web-based OAuth flow where:
1. Users click "Authenticate with Google Photos" in their browser
2. They are redirected to Google's OAuth consent screen
3. After authorization, they are redirected back to your application
4. The authentication token is saved on the server

## Setup Steps

### 1. Ensure Redirect URI is Configured

In your Google Cloud Console:
1. Go to APIs & Services > Credentials
2. Click on your OAuth 2.0 Client ID
3. Add the following authorized redirect URI:
   - For production: `https://home.slugranch.org/familybook/google-photos/callback`
   - For local testing: `http://localhost:5000/google-photos/callback`

### 2. First-Time Authentication

When you first deploy:
1. Navigate to the create post page
2. Click "Browse Google Photos"
3. If not authenticated, you'll see an error with a link to authenticate
4. Click the authentication link
5. Authorize the app in Google's consent screen
6. You'll be redirected back to the create post page
7. The authentication token will be saved as `token.pickle`

### 3. OAuth Routes Added

The following routes handle the OAuth flow:
- `/google-photos/auth` - Initiates the OAuth flow
- `/google-photos/callback` - Handles the OAuth callback from Google

### 4. Modified Functions

- `get_authenticated_service()` - No longer uses `run_local_server()`
- `create_picker_session()` - No longer uses `run_local_server()`
- Added `get_auth_url()` - Creates OAuth authorization URL
- Added `handle_oauth_callback()` - Processes OAuth callback
- Added `is_authenticated()` - Checks if valid auth exists

## Troubleshooting

### "Authentication required" Error
This is expected on first run. Click the provided authentication link.

### Invalid OAuth State
Clear your browser cookies and try again.

### Redirect URI Mismatch
Ensure the redirect URI in Google Cloud Console exactly matches your deployment URL.

## Security Notes

1. The `oauth_flows` dictionary stores OAuth state temporarily in memory
2. For production, consider using Redis or a database for OAuth state storage
3. The Flask session is used to verify OAuth state for security
4. Always use HTTPS in production for OAuth flows