#!/usr/bin/env python3
"""
Debug Google Photos API integration - simulate what the Flask app does
"""

import sys
import os
sys.path.append(os.path.dirname(__file__))

from google_photos import get_authenticated_service

def debug_google_photos_list():
    """Debug the exact same call that Flask app makes"""
    try:
        print("=== DEBUGGING GOOGLE PHOTOS API ===")
        print("Attempting to list Google Photos...")
        
        service = get_authenticated_service()
        print(f"Service created: {type(service)}")
        
        # Same parameters as Flask app
        page_size = 50
        params = {'pageSize': min(page_size, 100)}
        
        print(f"Request parameters: {params}")
        
        # List media items - same call as Flask app
        print("Making API call to mediaItems().list()...")
        results = service.mediaItems().list(**params).execute()
        print(f"API call successful!")
        print(f"Raw results keys: {list(results.keys()) if results else 'None'}")
        
        items = results.get('mediaItems', [])
        print(f"Found {len(items)} total items")
        
        if len(items) == 0:
            print("\nNO PHOTOS FOUND!")
            print("This could mean:")
            print("1. Your Google Photos library is empty")
            print("2. API permissions are insufficient") 
            print("3. Photos are not accessible via API")
            
            # Check if we have any other data
            if results:
                print(f"\nOther data in response: {results}")
        else:
            print(f"\nSUCCESS: Found {len(items)} photos!")
            
            # Show first few items
            for i, item in enumerate(items[:3], 1):
                print(f"\nPhoto {i}:")
                print(f"   ID: {item.get('id', 'N/A')}")
                print(f"   Filename: {item.get('filename', 'N/A')}")
                print(f"   MIME Type: {item.get('mimeType', 'N/A')}")
                print(f"   Base URL: {item.get('baseUrl', 'N/A')[:50]}...")
                
                metadata = item.get('mediaMetadata', {})
                if metadata:
                    print(f"   Creation Time: {metadata.get('creationTime', 'N/A')}")
                    if metadata.get('video'):
                        print(f"   Type: Video")
                    else:
                        print(f"   Type: Photo")
        
        # Filter for images and videos only
        filtered_items = []
        for item in items:
            mime_type = item.get('mimeType', '')
            if mime_type.startswith('image/') or mime_type.startswith('video/'):
                filtered_items.append(item)
        
        print(f"\nSUMMARY:")
        print(f"   Total items: {len(items)}")
        print(f"   Images/Videos: {len(filtered_items)}")
        print(f"   Next page token: {'Yes' if results.get('nextPageToken') else 'No'}")
        
        return {
            'success': True,
            'total_items': len(items),
            'filtered_items': len(filtered_items),
            'photos': filtered_items,
            'has_next_page': bool(results.get('nextPageToken'))
        }
        
    except Exception as e:
        print(f"\nERROR: {str(e)}")
        print(f"Error type: {type(e)}")
        
        error_msg = str(e)
        if "insufficient authentication scopes" in error_msg.lower():
            print("\nSOLUTION: Run 'python reauth_google_photos.py' to fix authentication")
        elif "forbidden" in error_msg.lower():
            print("\nSOLUTION: Enable Google Photos Library API in Google Cloud Console")
        elif "not found" in error_msg.lower():
            print("\nSOLUTION: Check API endpoint configuration")
        
        return {
            'success': False,
            'error': error_msg
        }

if __name__ == "__main__":
    result = debug_google_photos_list()
    
    if result['success']:
        if result['filtered_items'] > 0:
            print(f"\nREADY TO USE: Found {result['filtered_items']} photos/videos!")
        else:
            print(f"\nNO MEDIA FOUND: API works but no photos/videos found")
            print("Check that you have photos uploaded to Google Photos")
    else:
        print(f"\nINTEGRATION BROKEN: {result['error']}")