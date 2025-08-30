import os
import pickle
import requests
import json

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build_from_document
from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/photoslibrary.readonly',
    'https://www.googleapis.com/auth/photoslibrary.readonly.appcreateddata',
    'https://www.googleapis.com/auth/photospicker.mediaitems.readonly'
]
CREDENTIALS_FILE = 'client_secret.json'  # Updated to use the correct file name
TOKEN_FILE = 'token.pickle'
DISCOVERY_DOC_FILE = 'photoslibrary_v1_discovery.json'

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
    
    # Try to use local discovery document first
    if os.path.exists(DISCOVERY_DOC_FILE):
        try:
            with open(DISCOVERY_DOC_FILE, 'r') as f:
                discovery_doc = f.read()
            return build_from_document(discovery_doc, credentials=creds)
        except Exception as e:
            print(f"Failed to use local discovery document: {e}")
    
    # Fallback: download discovery document
    try:
        discovery_url = "https://photoslibrary.googleapis.com/$discovery/rest?version=v1"
        response = requests.get(discovery_url)
        if response.status_code == 200:
            discovery_doc = response.text
            # Save for future use
            with open(DISCOVERY_DOC_FILE, 'w') as f:
                f.write(discovery_doc)
            return build_from_document(discovery_doc, credentials=creds)
        else:
            raise Exception(f"Failed to fetch discovery document: HTTP {response.status_code}")
    except Exception as e:
        print(f"Error with discovery document: {e}")
        # Final fallback: try direct API call approach
        return DirectPhotosAPI(creds)

def list_recent_photos(page_size=20):
    service = get_authenticated_service()
    results = service.mediaItems().list(pageSize=page_size).execute()
    items = results.get('mediaItems', [])
    return items

def download_media(media_item, save_dir='static/imported'):
    # Check if this is a video using multiple detection methods
    mime_type = media_item.get('mimeType', '')
    media_metadata = media_item.get('mediaMetadata', {})
    is_video = mime_type.startswith('video/') or media_metadata.get('video') is not None
    
    # Use appropriate download parameter based on media type
    if is_video:
        url = media_item['baseUrl'] + "=dv"  # Download original video
        # Determine video extension from mimeType
        if 'mp4' in mime_type:
            ext = 'mp4'
        elif 'mov' in mime_type:
            ext = 'mov'
        elif 'webm' in mime_type:
            ext = 'webm'
        else:
            ext = 'mp4'  # Default video extension
    else:
        url = media_item['baseUrl'] + "=d"   # Download original image
        # Determine image extension from mimeType
        if 'jpeg' in mime_type or 'jpg' in mime_type:
            ext = 'jpg'
        elif 'png' in mime_type:
            ext = 'png'
        elif 'gif' in mime_type:
            ext = 'gif'
        elif 'webp' in mime_type:
            ext = 'webp'
        else:
            ext = 'jpg'  # Default image extension
    
    response = requests.get(url)
    if response.status_code == 200:
        filename = f"{media_item['id']}.{ext}"
        path = os.path.join(save_dir, filename)
        os.makedirs(save_dir, exist_ok=True)
        with open(path, 'wb') as f:
            f.write(response.content)
        return filename
    return None

class DirectPhotosAPI:
    """Direct API calls to Google Photos as fallback"""
    
    def __init__(self, credentials):
        self.credentials = credentials
        self.base_url = "https://photoslibrary.googleapis.com/v1"
    
    def _make_request(self, endpoint, method="GET", params=None, data=None):
        """Make authenticated request to Photos API"""
        headers = {
            'Authorization': f'Bearer {self.credentials.token}',
            'Content-Type': 'application/json'
        }
        
        url = f"{self.base_url}/{endpoint}"
        
        if method == "GET":
            response = requests.get(url, headers=headers, params=params)
        elif method == "POST":
            response = requests.post(url, headers=headers, json=data)
        else:
            raise ValueError(f"Unsupported method: {method}")
        
        if response.status_code == 401:
            # Token might be expired, refresh it
            self.credentials.refresh(Request())
            headers['Authorization'] = f'Bearer {self.credentials.token}'
            
            if method == "GET":
                response = requests.get(url, headers=headers, params=params)
            elif method == "POST":
                response = requests.post(url, headers=headers, json=data)
        
        return response
    
    def mediaItems(self):
        return DirectMediaItems(self)

class DirectMediaItems:
    """Direct media items API"""
    
    def __init__(self, api):
        self.api = api
    
    def list(self, pageSize=50, pageToken=None):
        params = {'pageSize': pageSize}
        if pageToken:
            params['pageToken'] = pageToken
        
        response = self.api._make_request('mediaItems', params=params)
        return DirectAPIResponse(response)

class DirectAPIResponse:
    """Wrapper for direct API response"""
    
    def __init__(self, response):
        self.response = response
        self._data = None
    
    def execute(self):
        if self.response.status_code == 200:
            self._data = self.response.json()
            return self._data
        else:
            raise Exception(f"API request failed: {self.response.status_code} - {self.response.text}")
    
    def get(self, key, default=None):
        if self._data is None:
            self.execute()
        return self._data.get(key, default)


def create_picker_session():
    """Create a Google Photos Picker session using the correct API endpoint"""
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
    
    # Create picker session using correct Photo Picker API endpoint
    headers = {
        'Authorization': f'Bearer {creds.token}',
        'Content-Type': 'application/json'
    }
    
    # Request body for picker session - only include pickingConfig if needed
    session_data = {
        'pickingConfig': {
            'maxItemCount': '2000'  # Allow up to 2000 items (default)
        }
    }
    
    # Make request to Photo Picker API
    response = requests.post(
        'https://photospicker.googleapis.com/v1/sessions',
        headers=headers,
        json=session_data
    )
    
    if response.status_code == 401:
        # Token expired, refresh and retry
        creds.refresh(Request())
        headers['Authorization'] = f'Bearer {creds.token}'
        response = requests.post(
            'https://photospicker.googleapis.com/v1/sessions',
            headers=headers,
            json=session_data
        )
    
    if response.status_code in [200, 201]:
        return response.json()
    else:
        raise Exception(f"Failed to create picker session: {response.status_code} - {response.text}")


def poll_picker_session(session_id):
    """Poll a Google Photos Picker session for completion"""
    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'rb') as token:
            creds = pickle.load(token)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise Exception("No valid credentials for polling session")
    
    headers = {
        'Authorization': f'Bearer {creds.token}',
        'Content-Type': 'application/json'
    }
    
    # Get session status from Photo Picker API
    response = requests.get(
        f'https://photospicker.googleapis.com/v1/sessions/{session_id}',
        headers=headers
    )
    
    if response.status_code == 401:
        # Token expired, refresh and retry
        creds.refresh(Request())
        headers['Authorization'] = f'Bearer {creds.token}'
        response = requests.get(
            f'https://photospicker.googleapis.com/v1/sessions/{session_id}',
            headers=headers
        )
    
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Failed to poll picker session: {response.status_code} - {response.text}")


def get_picked_media_items(session_id):
    """Get picked media items from a Picker session using the correct API"""
    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'rb') as token:
            creds = pickle.load(token)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise Exception("No valid credentials for getting picked items")
    
    headers = {
        'Authorization': f'Bearer {creds.token}',
        'Content-Type': 'application/json'
    }
    
    # Get picked media items from Picker API
    response = requests.get(
        f'https://photospicker.googleapis.com/v1/mediaItems?sessionId={session_id}',
        headers=headers
    )
    
    if response.status_code == 401:
        # Token expired, refresh and retry
        creds.refresh(Request())
        headers['Authorization'] = f'Bearer {creds.token}'
        response = requests.get(
            f'https://photospicker.googleapis.com/v1/mediaItems?sessionId={session_id}',
            headers=headers
        )
    
    if response.status_code == 200:
        return response.json()
    elif response.status_code == 400:
        # This might be a FAILED_PRECONDITION error - user hasn't finished selecting
        error_data = response.json()
        if 'FAILED_PRECONDITION' in str(error_data):
            return {'not_ready': True, 'error': error_data}
        else:
            raise Exception(f"Failed to get picked items: {response.status_code} - {response.text}")
    else:
        raise Exception(f"Failed to get picked items: {response.status_code} - {response.text}")


def get_media_item_details(media_item_ids):
    """Get details for selected media items from Photos Library API (legacy function)"""
    service = get_authenticated_service()
    
    media_items = []
    for item_id in media_item_ids:
        try:
            # Use the Photos Library API to get media item details
            if hasattr(service, 'mediaItems'):
                media_item = service.mediaItems().get(mediaItemId=item_id).execute()
            else:
                # Fallback to direct API call
                response = service._make_request(f'mediaItems/{item_id}')
                if response.status_code == 200:
                    media_item = response.json()
                else:
                    continue
            
            media_items.append(media_item)
        except Exception as e:
            print(f"Error getting media item {item_id}: {e}")
            continue
    
    return media_items
