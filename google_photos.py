import os
import pickle
import requests

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/photoslibrary.readonly']
CREDENTIALS_FILE = 'credentials.json'
TOKEN_FILE = 'token.pickle'

def get_authenticated_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'wb') as token:
            pickle.dump(creds, token)
    return build('photoslibrary', 'v1', credentials=creds)

def list_recent_photos(page_size=20):
    service = get_authenticated_service()
    results = service.mediaItems().list(pageSize=page_size).execute()
    items = results.get('mediaItems', [])
    return items

def download_photo(media_item, save_dir='static/imported'):
    url = media_item['baseUrl'] + "=d"  # Download original quality
    response = requests.get(url)
    if response.status_code == 200:
        filename = f"{media_item['id']}.jpg"
        path = os.path.join(save_dir, filename)
        os.makedirs(save_dir, exist_ok=True)
        with open(path, 'wb') as f:
            f.write(response.content)
        return filename
    return None
