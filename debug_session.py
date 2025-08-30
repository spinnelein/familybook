#!/usr/bin/env python3
"""
Debug session status after photo selection
"""

import sys
import os
sys.path.append(os.path.dirname(__file__))

from google_photos import poll_picker_session, get_picked_media_items

def debug_session(session_id):
    """Debug what's in a session after selection"""
    print(f"=== DEBUGGING SESSION {session_id} ===")
    
    try:
        print("\n1. Polling session...")
        session = poll_picker_session(session_id)
        print(f"Full session data:")
        for key, value in session.items():
            print(f"  {key}: {value}")
        
        media_items_set = session.get('mediaItemsSet', False)
        print(f"\nMediaItemsSet: {media_items_set}")
        
        if media_items_set:
            print("\n2. Trying to get picked items...")
            try:
                picked_items = get_picked_media_items(session_id)
                print(f"Picked items response:")
                if isinstance(picked_items, dict):
                    for key, value in picked_items.items():
                        print(f"  {key}: {value}")
                else:
                    print(f"  {picked_items}")
                    
                if 'pickedMediaItems' in picked_items:
                    items = picked_items['pickedMediaItems']
                    print(f"\nFound {len(items)} picked items:")
                    for i, item in enumerate(items[:3]):  # Show first 3
                        print(f"  Item {i+1}:")
                        for k, v in item.items():
                            print(f"    {k}: {v}")
                        
            except Exception as e:
                print(f"Error getting picked items: {e}")
                import traceback
                traceback.print_exc()
        else:
            print("\n2. No items marked as selected in session")
            
    except Exception as e:
        print(f"Error polling session: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python debug_session.py <session_id>")
        print("Get session_id from your browser's network tab or Flask console")
        sys.exit(1)
    
    session_id = sys.argv[1]
    debug_session(session_id)