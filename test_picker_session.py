#!/usr/bin/env python3
"""
Test the new Google Photos Picker session creation
"""

import sys
import os
sys.path.append(os.path.dirname(__file__))

from google_photos import create_picker_session, poll_picker_session

def test_picker_session():
    """Test creating a picker session"""
    print("=== TESTING GOOGLE PHOTOS PICKER SESSION ===")
    
    try:
        print("1. Creating picker session...")
        session = create_picker_session()
        
        print(f"Session created successfully!")
        print(f"Session ID: {session.get('id', 'Unknown')}")
        print(f"Picker URI: {session.get('pickerUri', 'Unknown')}")
        print(f"State: {session.get('pickerState', 'Unknown')}")
        
        return True
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_picker_session()
    
    if success:
        print("\nSUCCESS! PICKER SESSION TEST PASSED")
        print("The Google Photos Picker API integration is working!")
    else:
        print("\nERROR: PICKER SESSION TEST FAILED")
        print("Check the error messages above for troubleshooting.")