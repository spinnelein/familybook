#!/usr/bin/env python3
"""
Test Google Photos API after fixing backup/sync issues
"""

import sys
import os
sys.path.append(os.path.dirname(__file__))

from google_photos import get_authenticated_service

def test_after_backup():
    """Test API after ensuring photos are backed up to Google Photos"""
    print("=== TESTING AFTER BACKUP FIX ===")
    print("Run this after ensuring photos are backed up to Google Photos cloud")
    
    try:
        service = get_authenticated_service()
        
        # Test basic list
        print("\n1. Testing basic media list...")
        results = service.mediaItems().list(pageSize=5).execute()
        items = results.get('mediaItems', [])
        print(f"   Found: {len(items)} items")
        
        if len(items) > 0:
            print("\nSUCCESS! Google Photos API is now working!")
            print("Your photos picker integration should work perfectly now.")
            
            # Show sample photos
            for i, item in enumerate(items[:3], 1):
                print(f"\nPhoto {i}:")
                print(f"   Filename: {item.get('filename', 'Unknown')}")
                print(f"   MIME Type: {item.get('mimeType', 'Unknown')}")
                
                metadata = item.get('mediaMetadata', {})
                if metadata:
                    creation_time = metadata.get('creationTime', 'Unknown')
                    print(f"   Created: {creation_time}")
            
            return True
        else:
            print("\nSTILL NO PHOTOS FOUND")
            print("Additional steps needed:")
            print("1. Verify backup & sync is ON in Google Photos settings")
            print("2. Wait for photos to finish backing up (may take time)")
            print("3. Try uploading a test photo directly to photos.google.com")
            print("4. Make sure you're using the same Google account")
            return False
            
    except Exception as e:
        print(f"\nAPI ERROR: {e}")
        print("Check Google Cloud Console configuration")
        return False

if __name__ == "__main__":
    success = test_after_backup()
    
    if success:
        print("\n=== READY TO USE ===")
        print("Your Google Photos picker should now work in the web app!")
        print("1. Start Flask app: python app.py")  
        print("2. Go to create post page")
        print("3. Click 'Browse Google Photos' button")
    else:
        print("\n=== STILL NEEDS ATTENTION ===")
        print("Follow the backup & sync steps above, then run this test again")