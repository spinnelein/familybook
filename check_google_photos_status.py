#!/usr/bin/env python3
"""
Check Google Photos status and provide solutions
"""

import sys
import os
sys.path.append(os.path.dirname(__file__))

from google_photos import get_authenticated_service

def check_google_photos_status():
    """Check different aspects of Google Photos API access"""
    try:
        print("=== GOOGLE PHOTOS STATUS CHECK ===")
        service = get_authenticated_service()
        
        # Check 1: Basic mediaItems access
        print("\n1. Checking basic media items access...")
        try:
            results = service.mediaItems().list(pageSize=10).execute()
            items = results.get('mediaItems', [])
            print(f"   Found {len(items)} items via basic access")
            
            if results.get('nextPageToken'):
                print("   Has next page token - pagination available")
        except Exception as e:
            print(f"   ERROR: {e}")
        
        # Check 2: Albums access
        print("\n2. Checking albums access...")
        try:
            albums_result = service.albums().list(pageSize=10).execute()
            albums = albums_result.get('albums', [])
            print(f"   Found {len(albums)} albums")
            
            for i, album in enumerate(albums[:3], 1):
                title = album.get('title', 'Untitled')
                item_count = album.get('mediaItemsCount', 'Unknown')
                print(f"   Album {i}: '{title}' ({item_count} items)")
        except Exception as e:
            print(f"   Albums access error: {e}")
        
        # Check 3: Search functionality
        print("\n3. Checking search functionality...")
        try:
            # Try to search for any media items
            search_request = service.mediaItems().search(
                body={
                    'pageSize': 10,
                    'filters': {
                        'mediaTypeFilter': {
                            'mediaTypes': ['PHOTO', 'VIDEO']
                        }
                    }
                }
            )
            search_results = search_request.execute()
            search_items = search_results.get('mediaItems', [])
            print(f"   Found {len(search_items)} items via search")
        except Exception as e:
            print(f"   Search error: {e}")
        
        # Provide recommendations
        print("\n=== RECOMMENDATIONS ===")
        
        if len(items) == 0:
            print("\n⚠️  NO PHOTOS ACCESSIBLE:")
            print("1. Check if you have photos in your Google Photos library")
            print("   - Visit https://photos.google.com in your browser")
            print("   - Upload some test photos if empty")
            print("")
            print("2. Verify API permissions in Google Cloud Console:")
            print("   - Go to https://console.cloud.google.com")
            print("   - Enable 'Photos Library API'")
            print("   - Check OAuth consent screen settings")
            print("")
            print("3. Re-run authentication with broader scopes:")
            print("   - Run: python reauth_google_photos.py")
            print("")
            print("4. Try different authentication scopes:")
            print("   - The API might need different permissions")
        else:
            print(f"✅ SUCCESS: Found {len(items)} photos - integration should work!")
            
    except Exception as e:
        print(f"FATAL ERROR: {e}")
        print("\nThis suggests a fundamental API access problem.")
        print("Check Google Cloud Console configuration.")

if __name__ == "__main__":
    check_google_photos_status()