#!/usr/bin/env python3
"""
Advanced Google Photos API debugging for cases where photos exist but API returns none
"""

import sys
import os
import json
sys.path.append(os.path.dirname(__file__))

from google_photos import get_authenticated_service
import requests
from google.auth.transport.requests import Request

def advanced_debug():
    """Advanced debugging for Google Photos API when photos exist but API returns 0"""
    try:
        print("=== ADVANCED GOOGLE PHOTOS DEBUG ===")
        print("For cases where photos exist but API finds none\n")
        
        service = get_authenticated_service()
        print(f"Service created: {type(service)}")
        
        # Get credentials for direct API calls
        creds = service._http.credentials
        print(f"Credentials type: {type(creds)}")
        print(f"Token valid: {creds.valid}")
        
        if creds.expired:
            print("Token expired, refreshing...")
            creds.refresh(Request())
        
        print(f"Scopes: {creds.scopes}")
        
        # Test 1: Direct HTTP API call
        print("\n1. TESTING DIRECT HTTP API CALL")
        headers = {
            'Authorization': f'Bearer {creds.token}',
            'Content-Type': 'application/json'
        }
        
        url = "https://photoslibrary.googleapis.com/v1/mediaItems"
        params = {'pageSize': 10}
        
        print(f"Making direct request to: {url}")
        response = requests.get(url, headers=headers, params=params)
        print(f"Response status: {response.status_code}")
        print(f"Response headers: {dict(response.headers)}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"Direct API response keys: {list(data.keys())}")
            items = data.get('mediaItems', [])
            print(f"Items found via direct call: {len(items)}")
            
            if len(items) > 0:
                print("SUCCESS: Found photos via direct API call!")
                item = items[0]
                print(f"Sample item keys: {list(item.keys())}")
            else:
                print("Direct API call also returns 0 items")
        else:
            print(f"Direct API call failed: {response.text}")
        
        # Test 2: Try different page sizes
        print("\n2. TESTING DIFFERENT PAGE SIZES")
        for page_size in [1, 5, 25, 100]:
            try:
                result = service.mediaItems().list(pageSize=page_size).execute()
                items = result.get('mediaItems', [])
                print(f"   Page size {page_size}: {len(items)} items")
                if len(items) > 0:
                    break
            except Exception as e:
                print(f"   Page size {page_size}: ERROR - {e}")
        
        # Test 3: Try search instead of list
        print("\n3. TESTING SEARCH API")
        try:
            search_body = {
                'pageSize': 10,
                'filters': {
                    'mediaTypeFilter': {
                        'mediaTypes': ['PHOTO']
                    }
                }
            }
            search_result = service.mediaItems().search(body=search_body).execute()
            search_items = search_result.get('mediaItems', [])
            print(f"   Search for PHOTO: {len(search_items)} items")
        except Exception as e:
            print(f"   Search for PHOTO: ERROR - {e}")
        
        try:
            search_body = {
                'pageSize': 10,
                'filters': {
                    'mediaTypeFilter': {
                        'mediaTypes': ['VIDEO']
                    }
                }
            }
            search_result = service.mediaItems().search(body=search_body).execute()
            search_items = search_result.get('mediaItems', [])
            print(f"   Search for VIDEO: {len(search_items)} items")
        except Exception as e:
            print(f"   Search for VIDEO: ERROR - {e}")
        
        # Test 4: Check albums
        print("\n4. TESTING ALBUMS ACCESS")
        try:
            albums_result = service.albums().list(pageSize=10).execute()
            albums = albums_result.get('albums', [])
            print(f"   Albums found: {len(albums)}")
            
            for album in albums[:3]:
                album_id = album.get('id')
                title = album.get('title', 'Untitled')
                print(f"   Album: '{title}' (ID: {album_id})")
                
                # Try to get items from this album
                try:
                    album_search = service.mediaItems().search(
                        body={'pageSize': 5, 'albumId': album_id}
                    ).execute()
                    album_items = album_search.get('mediaItems', [])
                    print(f"     Items in album: {len(album_items)}")
                    if len(album_items) > 0:
                        print("     SUCCESS: Found items in album!")
                except Exception as ae:
                    print(f"     Album search error: {ae}")
                    
        except Exception as e:
            print(f"   Albums error: {e}")
        
        # Test 5: Check API quotas and limits
        print("\n5. CHECKING API STATUS")
        try:
            # Make a simple API call to check for quota issues
            test_response = requests.get(
                "https://photoslibrary.googleapis.com/v1/mediaItems",
                headers=headers,
                params={'pageSize': 1}
            )
            
            quota_remaining = test_response.headers.get('X-RateLimit-Remaining')
            quota_limit = test_response.headers.get('X-RateLimit-Limit')
            
            if quota_remaining:
                print(f"   API Quota remaining: {quota_remaining}")
            if quota_limit:
                print(f"   API Quota limit: {quota_limit}")
                
            # Check for specific error headers
            if 'X-Goog-API-Client' in test_response.headers:
                print(f"   API Client: {test_response.headers['X-Goog-API-Client']}")
                
        except Exception as e:
            print(f"   Quota check error: {e}")
        
        # Final recommendations
        print("\n=== DIAGNOSIS SUMMARY ===")
        if response.status_code == 200 and len(data.get('mediaItems', [])) == 0:
            print("\n🔍 ISSUE IDENTIFIED:")
            print("- API authentication: WORKING")
            print("- API access: WORKING") 
            print("- Photos returned: NONE")
            print("\nMost likely causes:")
            print("1. Google Photos Library API project setup issue")
            print("2. Photos are in a different Google account")
            print("3. Photos are not backed up to Google Photos cloud")
            print("4. API project doesn't have access to your personal photos")
            
            print("\n🛠️  SOLUTIONS TO TRY:")
            print("1. In Google Photos web interface:")
            print("   - Check if photos are backed up (not just on device)")
            print("   - Look for 'Backup & sync' settings")
            print("   - Verify you're logged into the same Google account")
            print("")
            print("2. In Google Cloud Console:")
            print("   - Go to APIs & Services > Credentials")
            print("   - Edit OAuth 2.0 Client")
            print("   - Verify authorized redirect URIs")
            print("   - Check OAuth consent screen")
            print("")
            print("3. Test account verification:")
            print("   - Make sure the Google account in token matches your photos")
            print("   - Try creating a new test project with same account")
        
    except Exception as e:
        print(f"FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    advanced_debug()