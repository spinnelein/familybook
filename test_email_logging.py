#!/usr/bin/env python3
"""
Test script to verify email logging functionality works correctly.
"""

import sys
import os

# Add the app directory to the Python path
sys.path.insert(0, os.path.dirname(__file__))

from app import app
from db.queries import log_email, update_email_log, get_email_logs

def test_email_logging():
    """Test that email logging works without database errors"""
    with app.app_context():
        print("Testing email logging functionality...")
        
        try:
            # Test 1: Log a new email
            print("1. Testing log_email function...")
            log_id = log_email(
                recipient_email="test@example.com",
                template_name="test_template", 
                subject="Test Email",
                status="pending",
                user_id=1
            )
            
            if log_id:
                print(f"   PASS: Email logged successfully with ID: {log_id}")
            else:
                print("   FAIL: Failed to log email - no ID returned")
                return False
                
            # Test 2: Update email status
            print("2. Testing update_email_log function...")
            success = update_email_log(log_id, "sent")
            
            if success:
                print("   PASS: Email status updated successfully")
            else:
                print("   FAIL: Failed to update email status")
                return False
                
            # Test 3: Retrieve email logs to verify
            print("3. Testing email log retrieval...")
            logs = get_email_logs(limit=1)
            
            if logs and logs[0]['id'] == log_id:
                log_entry = logs[0]
                print(f"   PASS: Email log retrieved: {log_entry['recipient_email']}, status: {log_entry['status']}")
                if log_entry['status'] == 'sent':
                    print("   PASS: Status correctly updated to 'sent'")
                    return True
                else:
                    print(f"   FAIL: Status not updated correctly: {log_entry['status']}")
                    return False
            else:
                print("   FAIL: Failed to retrieve email log")
                return False
                
        except Exception as e:
            print(f"   FAIL: Email logging test failed with error: {e}")
            return False

if __name__ == "__main__":
    success = test_email_logging()
    if success:
        print("\nSUCCESS: All email logging tests passed!")
    else:
        print("\nFAILED: Email logging tests failed!")
        sys.exit(1)