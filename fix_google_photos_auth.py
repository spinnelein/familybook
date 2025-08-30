#!/usr/bin/env python3
"""
Fix Google Photos authentication with comprehensive scopes
"""

import os
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# Comprehensive scopes for Google Photos
COMPREHENSIVE_SCOPES = [
    'https://www.googleapis.com/auth/photoslibrary',
    'https://www.googleapis.com/auth/photoslibrary.readonly',
    'https://www.googleapis.com/auth/photoslibrary.readonly.appcreateddata'
]

CREDENTIALS_FILE = 'client_secret.json'
TOKEN_FILE = 'token.pickle'

def fix_authentication():
    """Fix authentication with comprehensive scopes"""
    print("=== FIXING GOOGLE PHOTOS AUTHENTICATION ===")
    print("This will use broader permissions to access your photos.")
    print("")
    
    # Remove old token
    if os.path.exists(TOKEN_FILE):
        os.remove(TOKEN_FILE)
        print(f"Removed old token: {TOKEN_FILE}")
    
    print("Starting authentication with comprehensive scopes...")
    print("Scopes being requested:")
    for scope in COMPREHENSIVE_SCOPES:
        print(f"  - {scope}")
    print("")
    
    try:
        # Start fresh authentication with all scopes
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, COMPREHENSIVE_SCOPES)
        creds = flow.run_local_server(port=0)
        
        # Save new token
        with open(TOKEN_FILE, 'wb') as token:
            pickle.dump(creds, token)
        
        print(f"SUCCESS: Authentication completed!")
        print(f"Token saved to: {TOKEN_FILE}")
        print("")
        print("Now test your Google Photos integration:")
        print("1. Start your Flask app: python app.py")
        print("2. Go to create post page")
        print("3. Click 'Browse Google Photos' button")
        
        return True
        
    except Exception as e:
        print(f"Authentication failed: {e}")
        print("")
        print("TROUBLESHOOTING:")
        print("1. Make sure client_secret.json is valid")
        print("2. Check that Google Photos Library API is enabled")
        print("3. Verify your Google Cloud project settings")
        return False

if __name__ == "__main__":
    success = fix_authentication()
    if success:
        print("\nREADY TO TEST: Try the Google Photos picker now!")
    else:
        print("\nNEEDS ATTENTION: Fix the issues above and try again.")