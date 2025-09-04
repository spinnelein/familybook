#!/usr/bin/env python3
"""
Improve notification preferences to use a single radio button choice:
- All Posts (new + major events)  
- Major Events Only
- No Notifications

This is more intuitive than separate checkboxes that can create confusing scenarios.
"""

import sys
import os

# Add the app directory to the Python path
sys.path.insert(0, os.path.dirname(__file__))

from app import app
from db.database import get_db

def analyze_current_preferences():
    """Analyze current user notification preferences"""
    with app.app_context():
        db = get_db()
        
        prefs = db.execute('''
            SELECT u.name, u.email, 
                   COALESCE(p.new_post, 1) as new_post,
                   COALESCE(p.major_event, 1) as major_event,
                   COALESCE(p.comment_reply, 1) as comment_reply
            FROM users u
            LEFT JOIN user_notification_preferences p ON u.id = p.user_id
            WHERE u.email != ""
            ORDER BY u.name
        ''').fetchall()
        
        print("Current User Notification Preferences:")
        print("=" * 60)
        
        for pref in prefs:
            print(f"User: {pref['name']} ({pref['email']})")
            print(f"  New Posts: {'ON' if pref['new_post'] else 'OFF'}")
            print(f"  Major Events: {'ON' if pref['major_event'] else 'OFF'}")
            print(f"  Comment Reply: {'ON' if pref['comment_reply'] else 'OFF'}")
            
            # Analyze the combination
            if pref['new_post'] and pref['major_event']:
                category = "ALL POSTS"
            elif pref['major_event'] and not pref['new_post']:
                category = "MAJOR EVENTS ONLY"
            elif pref['new_post'] and not pref['major_event']:
                category = "CONFUSING: Gets regular posts but misses major events!"
            else:
                category = "NO NOTIFICATIONS"
                
            print(f"  Category: {category}")
            print()

def create_migration_script(dry_run=True):
    """Create database migration to improve notification preferences"""
    migration_sql = '''
    -- Add new notification_level column
    ALTER TABLE user_notification_preferences 
    ADD COLUMN notification_level TEXT DEFAULT 'all';
    
    -- Update existing users based on their current preferences
    UPDATE user_notification_preferences 
    SET notification_level = CASE
        WHEN new_post = 1 AND major_event = 1 THEN 'all'
        WHEN new_post = 0 AND major_event = 1 THEN 'major_only'
        ELSE 'none'
    END;
    '''
    
    print("Database Migration Script:")
    print("=" * 40)
    print(migration_sql)
    
    if dry_run:
        print("\n[DRY RUN] Migration script generated but not executed")
        return
    
    # Execute migration
    with app.app_context():
        db = get_db()
        try:
            # Check if column already exists
            cursor = db.execute("PRAGMA table_info(user_notification_preferences)")
            columns = [col[1] for col in cursor.fetchall()]
            
            if 'notification_level' not in columns:
                # Add the column
                db.execute("ALTER TABLE user_notification_preferences ADD COLUMN notification_level TEXT DEFAULT 'all'")
                
                # Update existing records
                db.execute('''
                    UPDATE user_notification_preferences 
                    SET notification_level = CASE
                        WHEN new_post = 1 AND major_event = 1 THEN 'all'
                        WHEN new_post = 0 AND major_event = 1 THEN 'major_only'
                        ELSE 'none'
                    END
                ''')
                
                db.commit()
                print("\n✓ Database migration completed successfully!")
            else:
                print("\n✓ Column 'notification_level' already exists")
                
        except Exception as e:
            print(f"\n✗ Migration failed: {e}")

def generate_new_template():
    """Generate new user settings template with radio buttons"""
    
    template_html = '''
    <!-- Replace the existing checkbox preferences with radio buttons -->
    <div class="notification-preferences">
        <h2>📧 Email Notification Preferences</h2>
        <p class="section-description">Choose how many family updates you'd like to receive:</p>
        
        <div class="radio-group">
            <div class="radio-option">
                <input type="radio" name="notification_level" id="all" value="all" 
                       {% if prefs.notification_level == 'all' %}checked{% endif %}>
                <label for="all">
                    <div class="radio-icon">📬</div>
                    <div class="radio-content">
                        <h3>All Posts</h3>
                        <p>Get notified about all new posts, photos, and major family events</p>
                    </div>
                </label>
            </div>
            
            <div class="radio-option">
                <input type="radio" name="notification_level" id="major_only" value="major_only"
                       {% if prefs.notification_level == 'major_only' %}checked{% endif %}>
                <label for="major_only">
                    <div class="radio-icon">⭐</div>
                    <div class="radio-content">
                        <h3>Major Events Only</h3>
                        <p>Only receive notifications for important family announcements and events</p>
                    </div>
                </label>
            </div>
            
            <div class="radio-option">
                <input type="radio" name="notification_level" id="none" value="none"
                       {% if prefs.notification_level == 'none' %}checked{% endif %}>
                <label for="none">
                    <div class="radio-icon">🔕</div>
                    <div class="radio-content">
                        <h3>No Notifications</h3>
                        <p>Don't send me any email notifications (you can still visit the site)</p>
                    </div>
                </label>
            </div>
        </div>
        
        <!-- Keep comment reply separate as it's different -->
        <div class="preference-item">
            <div class="preference-content">
                <h3>Comment Replies</h3>
                <p>Get notified when someone replies to your comments</p>
            </div>
            <div class="preference-checkbox">
                <input type="checkbox" name="comment_reply" id="comment_reply" 
                       {% if prefs['comment_reply'] %}checked{% endif %}>
            </div>
        </div>
    </div>
    '''
    
    print("New Template HTML:")
    print("=" * 40)
    print(template_html)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Improve notification preferences system')
    parser.add_argument('--analyze', action='store_true', help='Analyze current preferences')
    parser.add_argument('--migrate', action='store_true', help='Generate migration script')
    parser.add_argument('--template', action='store_true', help='Generate new template HTML')
    parser.add_argument('--execute', action='store_true', help='Execute database migration')
    
    args = parser.parse_args()
    
    if args.analyze:
        analyze_current_preferences()
    elif args.migrate:
        create_migration_script(dry_run=not args.execute)
    elif args.template:
        generate_new_template()
    else:
        print("Usage:")
        print("  --analyze  : Show current user preferences")
        print("  --migrate  : Generate migration script") 
        print("  --template : Generate new template HTML")
        print("  --execute  : Actually run migration (use with --migrate)")