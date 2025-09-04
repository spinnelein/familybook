#!/usr/bin/env python3
"""
Utility script to fix emails stuck in pending/retry status.
This can be run on the deployed system to clean up old email logs.
"""

import sys
import os
from datetime import datetime, timedelta

# Add the app directory to the Python path
sys.path.insert(0, os.path.dirname(__file__))

from app import app
from db.database import get_db
from services.email_service import send_templated_email
from utils.timezone_utils import get_pacific_timezone

def fix_stuck_emails(dry_run=True):
    """Fix emails stuck in pending or retry status"""
    with app.app_context():
        db = get_db()
        
        # Get all stuck emails (pending or retry status)
        stuck_emails = db.execute("""
            SELECT el.*, u.email, u.name, u.magic_token 
            FROM email_logs el
            LEFT JOIN users u ON el.user_id = u.id
            WHERE el.status IN ('pending', 'retry')
            ORDER BY el.sent_at DESC
        """).fetchall()
        
        if not stuck_emails:
            print("No stuck emails found!")
            return
        
        print(f"Found {len(stuck_emails)} stuck emails:\n")
        
        for email in stuck_emails:
            print(f"ID: {email['id']}")
            print(f"  Status: {email['status']}")
            print(f"  Recipient: {email['recipient_email']} ({email['name'] or 'Unknown'})")
            print(f"  Template: {email['template_name']}")
            print(f"  Subject: {email['subject']}")
            print(f"  Sent at: {email['sent_at']}")
            print(f"  Error: {email['error_message'] or 'None'}")
            print("")
        
        if dry_run:
            print("\n=== DRY RUN MODE ===")
            print("No changes will be made. Run with --execute to apply fixes.\n")
            
            print("Recommended actions:")
            print("1. Mark old stuck emails as 'failed' (won't resend)")
            print("2. Optionally resend recent important emails")
            print("\nRun with --execute to apply these fixes")
        else:
            print("\n=== EXECUTING FIXES ===\n")
            
            # Fix each stuck email
            for email in stuck_emails:
                email_id = email['id']
                template_name = email['template_name']
                
                # Parse the sent_at timestamp
                try:
                    sent_time = datetime.fromisoformat(email['sent_at'].replace(' ', 'T'))
                    # If no timezone info, assume Pacific
                    if sent_time.tzinfo is None:
                        pacific_tz = get_pacific_timezone()
                        sent_time = pacific_tz.localize(sent_time)
                except:
                    print(f"Could not parse timestamp for email {email_id}, marking as failed")
                    db.execute("UPDATE email_logs SET status = 'failed', error_message = ? WHERE id = ?",
                             ('Could not parse timestamp', email_id))
                    db.commit()
                    continue
                
                # Get current Pacific time
                pacific_tz = get_pacific_timezone()
                now = datetime.now(pacific_tz)
                age_hours = (now - sent_time).total_seconds() / 3600
                
                # Decision logic
                if age_hours > 24:
                    # Emails older than 24 hours: mark as failed
                    print(f"Email {email_id}: Too old ({age_hours:.1f} hours), marking as failed")
                    db.execute("UPDATE email_logs SET status = 'failed', error_message = ? WHERE id = ?",
                             ('Email too old to resend', email_id))
                elif template_name == 'account_created' and email['user_id'] and age_hours < 48:
                    # Welcome emails less than 48 hours old: try to resend
                    print(f"Email {email_id}: Attempting to resend welcome email to {email['recipient_email']}")
                    
                    try:
                        # Resend using the email service
                        success = send_templated_email(
                            template_name='account_created',
                            to_email=email['recipient_email'],
                            user_id=email['user_id'],
                            user_name=email['name'],
                            family_name='Fernwood'  # You may need to adjust this
                        )
                        
                        if success:
                            # Mark original as failed but note it was resent
                            db.execute("UPDATE email_logs SET status = 'failed', error_message = ? WHERE id = ?",
                                     ('Resent as new email', email_id))
                            print(f"  ✓ Resent successfully")
                        else:
                            db.execute("UPDATE email_logs SET status = 'failed', error_message = ? WHERE id = ?",
                                     ('Resend attempt failed', email_id))
                            print(f"  ✗ Resend failed")
                    except Exception as e:
                        db.execute("UPDATE email_logs SET status = 'failed', error_message = ? WHERE id = ?",
                                 (f'Resend error: {str(e)}', email_id))
                        print(f"  ✗ Error resending: {e}")
                else:
                    # Other emails: mark as failed
                    print(f"Email {email_id}: Marking as failed (type: {template_name})")
                    db.execute("UPDATE email_logs SET status = 'failed', error_message = ? WHERE id = ?",
                             ('Stuck email cleanup', email_id))
                
                db.commit()
            
            print("\n✓ All stuck emails have been processed!")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Fix emails stuck in pending/retry status')
    parser.add_argument('--execute', action='store_true', help='Actually fix the emails (without this flag, runs in dry-run mode)')
    args = parser.parse_args()
    
    fix_stuck_emails(dry_run=not args.execute)