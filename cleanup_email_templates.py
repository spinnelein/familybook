#!/usr/bin/env python3
"""
Cleanup unused email templates and consolidate template naming.

This script will:
1. Check which templates actually exist in the database
2. Identify unused templates that can be safely removed
3. Consolidate template naming (rename new_post_notification to new_post if needed)
"""

import sys
import os

# Add the app directory to the Python path
sys.path.insert(0, os.path.dirname(__file__))

from app import app
from db.database import get_db

def analyze_template_usage():
    """Analyze which templates are used in code vs database"""
    
    # Templates used in the codebase
    used_templates = {
        'account_created',  # Used in admin blueprint and email service
        'new_post',         # Used in main_bp.py for regular posts  
        'major_event',      # Used in main_bp.py for major posts
        'comment_reply'     # Used in email service preferences
    }
    
    # Templates that are just definitions but not used
    unused_templates = {
        'user_invitation',      # Only in admin template definitions
        'new_post_notification' # Only in admin template definitions, conflicts with new_post
    }
    
    return used_templates, unused_templates

def cleanup_templates(dry_run=True):
    """Clean up email templates"""
    with app.app_context():
        db = get_db()
        
        # Get all templates from database
        templates = db.execute('SELECT * FROM email_templates ORDER BY template_name').fetchall()
        
        print(f"Found {len(templates)} email templates in database:\n")
        
        used_templates, unused_templates = analyze_template_usage()
        
        for template in templates:
            template_name = template['template_name']
            is_active = bool(template['is_active'])
            
            status = "ACTIVE" if is_active else "INACTIVE"
            
            if template_name in used_templates:
                print(f"✓ KEEP   {template_name:<20} ({status}) - Used in code")
            elif template_name in unused_templates:
                print(f"✗ REMOVE {template_name:<20} ({status}) - Unused template definition")
            else:
                print(f"? CHECK  {template_name:<20} ({status}) - Unknown template")
        
        print("\n" + "="*60 + "\n")
        
        # Handle new_post vs new_post_notification conflict
        new_post = None
        new_post_notification = None
        
        for template in templates:
            if template['template_name'] == 'new_post':
                new_post = template
            elif template['template_name'] == 'new_post_notification':
                new_post_notification = template
        
        if new_post and new_post_notification:
            print("CONFLICT DETECTED: Both 'new_post' and 'new_post_notification' exist")
            print(f"  new_post:              Active={bool(new_post['is_active'])}")
            print(f"  new_post_notification: Active={bool(new_post_notification['is_active'])}")
            print("\nRecommendation: Keep the active one, remove the other")
            
        elif new_post_notification and not new_post:
            print("NAMING ISSUE: 'new_post_notification' exists but code expects 'new_post'")
            print("Recommendation: Rename 'new_post_notification' to 'new_post'")
            
        elif new_post and not new_post_notification:
            print("✓ GOOD: 'new_post' exists and matches code expectations")
        
        # Removal candidates
        removal_candidates = []
        for template in templates:
            if template['template_name'] in unused_templates:
                removal_candidates.append(template)
        
        if removal_candidates:
            print(f"\nTemplates to remove ({len(removal_candidates)}):")
            for template in removal_candidates:
                print(f"  - {template['template_name']} (ID: {template['id']})")
        
        if dry_run:
            print("\n=== DRY RUN MODE ===")
            print("No changes will be made. Run with --execute to apply changes.")
        else:
            print("\n=== APPLYING CHANGES ===")
            
            # Remove unused templates
            for template in removal_candidates:
                try:
                    db.execute('DELETE FROM email_templates WHERE id = ?', (template['id'],))
                    print(f"✓ Removed template: {template['template_name']}")
                except Exception as e:
                    print(f"✗ Failed to remove {template['template_name']}: {e}")
            
            # Handle new_post_notification rename if needed
            if new_post_notification and not new_post:
                try:
                    db.execute("UPDATE email_templates SET template_name = 'new_post' WHERE id = ?", 
                             (new_post_notification['id'],))
                    print(f"✓ Renamed 'new_post_notification' to 'new_post'")
                except Exception as e:
                    print(f"✗ Failed to rename template: {e}")
            
            db.commit()
            print("\n✓ Email template cleanup completed!")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Cleanup unused email templates')
    parser.add_argument('--execute', action='store_true', help='Actually remove templates (without this flag, runs in dry-run mode)')
    args = parser.parse_args()
    
    cleanup_templates(dry_run=not args.execute)