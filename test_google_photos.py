#!/usr/bin/env python3
"""
Test script for Google Photos API integration
"""

import json
from google_photos import get_authenticated_service

def test_google_photos_api():
    """Test basic Google Photos API functionality"""
    try:
        print("Authenticating with Google Photos...")
        service = get_authenticated_service()
        print(f"Service created: {type(service)}")
        
        print("\nFetching recent photos...")
        results = service.mediaItems().list(pageSize=5).execute()
        items = results.get('mediaItems', [])
        
        print(f"Found {len(items)} photos")
        
        for i, item in enumerate(items[:3], 1):
            print(f"\nPhoto {i}:")
            print(f"   ID: {item.get('id')}")
            print(f"   Filename: {item.get('filename', 'Unknown')}")
            print(f"   MIME Type: {item.get('mimeType', 'Unknown')}")
            
            # Check if it has metadata
            metadata = item.get('mediaMetadata', {})
            if metadata:
                print(f"   Created: {metadata.get('creationTime', 'Unknown')}")
                if metadata.get('video'):
                    print(f"   Type: Video")
                else:
                    print(f"   Type: Photo")
            
            # Check base URL
            base_url = item.get('baseUrl')
            if base_url:
                print(f"   Thumbnail: {base_url}=w200-h200-c")
        
        print(f"\nGoogle Photos API test completed successfully!")
        return True
        
    except Exception as e:
        print(f"ERROR testing Google Photos API: {str(e)}")
        return False

if __name__ == "__main__":
    test_google_photos_api()