import os
import pickle
import requests
import json
import uuid

# Allow HTTP for development/testing (disable HTTPS requirement)
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

from google_auth_oauthlib.flow import InstalledAppFlow, Flow
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

# Store OAuth flows temporarily (in production, use Redis or database)
oauth_flows = {}

def create_oauth_flow(redirect_uri):
    """Create an OAuth flow for web-based authentication"""
    flow = Flow.from_client_secrets_file(
        CREDENTIALS_FILE,
        scopes=SCOPES,
        redirect_uri=redirect_uri
    )
    return flow

def get_auth_url(redirect_uri):
    """Get the OAuth authorization URL for the user to visit"""
    flow = create_oauth_flow(redirect_uri)
    auth_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='false',  # Prevent scope mixing
        prompt='consent'
    )
    # Store the flow for later use
    oauth_flows[state] = flow
    return auth_url, state

def handle_oauth_callback(authorization_response, redirect_uri):
    """Handle the OAuth callback and save credentials"""
    # Create a new flow for the callback (don't rely on stored state)
    flow = Flow.from_client_secrets_file(
        CREDENTIALS_FILE,
        scopes=SCOPES,
        redirect_uri=redirect_uri
    )
    
    # Exchange authorization code for tokens
    flow.fetch_token(authorization_response=authorization_response)
    
    # Validate that we got the expected scopes
    creds = flow.credentials
    if hasattr(creds, 'scopes') and creds.scopes:
        expected_scopes = set(SCOPES)
        actual_scopes = set(creds.scopes)
        if not expected_scopes.issubset(actual_scopes):
            missing_scopes = expected_scopes - actual_scopes
            print(f"Warning: Missing expected scopes: {missing_scopes}")
    
    # Save credentials
    with open(TOKEN_FILE, 'wb') as token:
        pickle.dump(creds, token)
    
    return creds

def is_authenticated():
    """Check if valid authentication exists"""
    if not os.path.exists(TOKEN_FILE):
        return False
    
    try:
        with open(TOKEN_FILE, 'rb') as token:
            creds = pickle.load(token)
        
        if creds and creds.valid:
            return True
        
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(TOKEN_FILE, 'wb') as token:
                pickle.dump(creds, token)
            return True
    except Exception:
        pass
    
    return False


def get_authenticated_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(TOKEN_FILE, 'wb') as token:
                pickle.dump(creds, token)
        else:
            # On a headless server, we can't use run_local_server
            # The app should handle authentication via web flow
            raise Exception("Authentication required. Please authenticate via the web interface.")
    
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
            with open(TOKEN_FILE, 'wb') as token:
                pickle.dump(creds, token)
        else:
            # On a headless server, authentication must be done via web flow
            raise Exception("Authentication required. Please authenticate via the web interface.")
    
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


def download_selected_media(selected_items, upload_folder):
    """Download and process selected media from Google Photos"""
    import uuid
    from flask import url_for
    
    imported_media = []
    total_original_size = 0
    total_processed_size = 0
    
    # Get authenticated credentials
    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'rb') as token:
            creds = pickle.load(token)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(TOKEN_FILE, 'wb') as token:
                pickle.dump(creds, token)
        else:
            raise Exception("Authentication required")
    
    headers = {'Authorization': f'Bearer {creds.token}'}
    
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
            
            response = requests.get(download_url, headers=headers)
            
            if response.status_code == 200:
                total_original_size += len(response.content)
                
                # Determine file extension and type
                if mime_type.startswith('image/'):
                    if 'jpeg' in mime_type or 'jpg' in mime_type:
                        ext = 'jpg'
                    elif 'png' in mime_type:
                        ext = 'png'
                    elif 'gif' in mime_type:
                        ext = 'gif'
                    elif 'webp' in mime_type:
                        ext = 'webp'
                    else:
                        ext = 'jpg'
                    
                    prefix = 'img'
                    media_type = 'image'
                elif mime_type.startswith('video/'):
                    if 'mp4' in mime_type:
                        ext = 'mp4'
                    elif 'mov' in mime_type:
                        ext = 'mov'
                    elif 'webm' in mime_type:
                        ext = 'webm'
                    else:
                        ext = 'mp4'
                    
                    prefix = 'vid'
                    media_type = 'video'
                else:
                    ext = 'jpg'
                    prefix = 'img'
                    media_type = 'image'
                
                # Generate unique filename
                unique_filename = f"{prefix}_{uuid.uuid4().hex}.{ext}"
                file_path = os.path.join(upload_folder, unique_filename)
                
                # Process and save the file
                processed_content = response.content
                
                # For images, try to optimize with Pillow if available
                if media_type == 'image' and ext in ['jpg', 'jpeg', 'png', 'webp']:
                    try:
                        from PIL import Image
                        import io
                        
                        image = Image.open(io.BytesIO(response.content))
                        
                        # Convert to RGB if necessary
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
                        
                        processed_content = output.getvalue()
                        
                    except ImportError:
                        # PIL not available, use original
                        pass
                    except Exception as resize_error:
                        print(f"Error optimizing image: {resize_error}")
                        # Use original if optimization fails
                        pass
                
                total_processed_size += len(processed_content)
                
                # Save the file
                with open(file_path, 'wb') as f:
                    f.write(processed_content)
                
                # Generate URL
                file_url = url_for('uploaded_file', filename=unique_filename, _external=True)
                
                imported_media.append({
                    'filename': unique_filename,
                    'original_name': filename,
                    'url': file_url,
                    'type': media_type,
                    'extension': ext,
                    'google_photo_id': item.get('id', media_file.get('id', 'unknown'))
                })
                
                print(f"Successfully imported {media_type}: {unique_filename}")
                
        except Exception as item_error:
            print(f"Error processing item: {str(item_error)}")
            continue
    
    return {
        'success': True,
        'media': imported_media,
        'count': len(imported_media),
        'totalOriginalSize': total_original_size,
        'totalProcessedSize': total_processed_size
    }


def create_picker_session():
    """Create a Google Photos Picker session using the correct API endpoint"""
    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'rb') as token:
            creds = pickle.load(token)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(TOKEN_FILE, 'wb') as token:
                pickle.dump(creds, token)
        else:
            # On a headless server, authentication must be done via web flow
            raise Exception("Authentication required. Please authenticate via the web interface.")
    
    # Create picker session using correct Photo Picker API endpoint
    headers = {
        'Authorization': f'Bearer {creds.token}',
        'Content-Type': 'application/json'
    }
    
    # Request body for picker session
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
