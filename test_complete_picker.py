#!/usr/bin/env python3
"""
Complete test of Google Photos Picker flow
"""

import sys
import os
import time
sys.path.append(os.path.dirname(__file__))

from google_photos import create_picker_session, poll_picker_session, get_picked_media_items

def test_complete_picker_flow():
    """Test the complete picker flow"""
    print("=== COMPLETE GOOGLE PHOTOS PICKER TEST ===")
    
    try:
        print("\n1. Creating picker session...")
        session = create_picker_session()
        
        session_id = session.get('id')
        picker_uri = session.get('pickerUri')
        
        print(f"SUCCESS: Session created!")
        print(f"Session ID: {session_id}")
        print(f"Picker URI: {picker_uri}")
        
        print(f"\n2. Testing session polling...")
        poll_result = poll_picker_session(session_id)
        print(f"Poll result: {poll_result}")
        
        media_items_set = poll_result.get('mediaItemsSet', False)
        print(f"MediaItemsSet: {media_items_set}")
        
        if media_items_set:
            print("\n3. Session indicates items selected, trying to get picked items...")
            try:
                picked_items = get_picked_media_items(session_id)
                print(f"Picked items result: {picked_items}")
            except Exception as e:
                print(f"Expected: User hasn't finished selecting yet - {e}")
        else:
            print("\n3. No items selected yet (expected for new session)")
        
        print(f"\n=== MANUAL TEST INSTRUCTIONS ===")
        print(f"1. Open this URL in your browser:")
        print(f"   {picker_uri}")
        print(f"2. Select some photos/videos")
        print(f"3. Complete the selection process")
        print(f"4. Run this command to check results:")
        print(f"   python -c \"from google_photos import poll_picker_session, get_picked_media_items; print('Session:', poll_picker_session('{session_id}')); print('Items:', get_picked_media_items('{session_id}'))\"")
        
        return True
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_complete_picker_flow()
    
    if success:
        print("\nSUCCESS: Picker session test completed!")
        print("Manual testing required to verify full flow.")
    else:
        print("\nERROR: Picker session test failed!")
        print("Check the error messages above.")