from googleapiclient.discovery import build_from_document
from google.oauth2.credentials import Credentials
import json
import os

def get_credentials(token_path):
    # Load OAuth2 credentials from the provided token file path
    return Credentials.from_authorized_user_file(token_path)

def get_photos_service(credentials, discovery_path):
    # Load the Google Photos API discovery document from a file
    with open(discovery_path, "r") as f:
        discovery_doc = f.read()
    # Build and return the service object using the discovery document
    return build_from_document(discovery_doc, credentials=credentials)

def list_albums(service, page_size=10):
    # List albums using the Google Photos service
    results = service.albums().list(pageSize=page_size).execute()
    albums = results.get('albums', [])
    return albums

def main():
    # Set file paths (update these if your files are in different locations)
    token_path = "token.json"
    discovery_path = "photoslibrary_v1_discovery.json"

    # Check that token and discovery documents exist
    if not os.path.exists(token_path):
        print(f"ERROR: {token_path} not found. Please authenticate and download your OAuth token.")
        return
    if not os.path.exists(discovery_path):
        print(f"ERROR: {discovery_path} not found. Download the discovery doc from:")
        print("https://photoslibrary.googleapis.com/$discovery/rest?version=v1")
        return

    # Authenticate and build the service
    creds = get_credentials(token_path)
    service = get_photos_service(creds, discovery_path)

    # List and print albums
    try:
        albums = list_albums(service, page_size=10)
        if not albums:
            print("No albums found.")
        else:
            print("Your Google Photos albums:")
            for album in albums:
                print(f"{album.get('title')} (ID: {album.get('id')})")
    except Exception as e:
        print("An error occurred while listing albums:", e)

if __name__ == "__main__":
    main()