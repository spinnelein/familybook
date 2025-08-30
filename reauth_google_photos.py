#!/usr/bin/env python3
"""
Re-authenticate Google Photos with proper scopes
"""

import os
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# Updated scopes
SCOPES = [
    'https://www.googleapis.com/auth/photoslibrary.readonly',
    'https://www.googleapis.com/auth/photoslibrary.readonly.appcreateddata'
]

CREDENTIALS_FILE = 'client_secret.json'
TOKEN_FILE = 'token.pickle'

def reauth():
    """Re-authenticate with Google Photos"""
    print("Re-authenticating Google Photos with updated scopes...")
    
    # Remove old token
    if os.path.exists(TOKEN_FILE):
        os.remove(TOKEN_FILE)
        print(f"Removed old token file: {TOKEN_FILE}")
    
    # Start fresh authentication
    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
    creds = flow.run_local_server(port=0)
    
    # Save new token
    with open(TOKEN_FILE, 'wb') as token:
        pickle.dump(creds, token)
    
    print(f"Authentication successful! Token saved to {TOKEN_FILE}")
    print("You can now use the Google Photos picker in your app.")

if __name__ == "__main__":
    reauth()