import os
import datetime
import pickle

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from extensions import db
from models import ImportedPhoto

# Path to your credentials JSON
CLIENT_SECRETS_FILE = "client_secret.json"
TOKEN_PICKLE = "token.pickle"

# Google Photos API Scopes
SCOPES = ['https://www.googleapis.com/auth/photoslibrary.readonly']

# Set up Flask app context if needed, or use raw SQLAlchemy here
DATABASE_URL = "sqlite:///your_database.db"  # Change as needed

def get_authenticated_service():
    creds = None
    if os.path.exists(TOKEN_PICKLE):
        with open(TOKEN_PICKLE, 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PICKLE, 'wb') as token:
            pickle.dump(creds, token)
    return build('photoslibrary', 'v1', credentials=creds)

def get_imported_google_ids(session):
    return set(row[0] for row in session.query(ImportedPhoto.google_id).all())

def main():
    # Set up DB session (replace with Flask context if needed)
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    # Get already imported google_ids
    imported_ids = get_imported_google_ids(session)

    service = get_authenticated_service()
    
    # Start of this month (UTC)
    now = datetime.datetime.utcnow()
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start_of_month_iso = start_of_month.isoformat("T") + "Z"

    next_page_token = None
    new_photos = []

    while True:
        results = service.mediaItems().list(
            pageSize=100,
            pageToken=next_page_token
        ).execute()
        items = results.get('mediaItems', [])
        for item in items:
            # Check creation date
            creation_time = item['mediaMetadata']['creationTime']
            if creation_time < start_of_month_iso:
                continue
            if item['id'] in imported_ids:
                continue
            # Save to DB
            imported_photo = ImportedPhoto(
                google_id=item['id'],
                filename=item['filename'],
                status='pending'
            )
            session.add(imported_photo)
            new_photos.append(item['filename'])
        session.commit()
        next_page_token = results.get('nextPageToken')
        if not next_page_token:
            break

    print(f"Imported {len(new_photos)} new photos: {new_photos}")

if __name__ == "__main__":
    main()