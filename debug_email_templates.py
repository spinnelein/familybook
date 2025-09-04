#!/usr/bin/env python3
"""
Debug email template issues by checking template syntax and content.
"""

import sys
import os

# Add the app directory to the Python path
sys.path.insert(0, os.path.dirname(__file__))

from app import app
from db.database import get_db
from services.email_service import render_email_template

def debug_email_templates():
    """Debug email templates for syntax issues"""
    with app.app_context():
        db = get_db()
        
        # Get all email templates
        templates = db.execute('SELECT * FROM email_templates WHERE is_active = 1').fetchall()
        
        print(f"Found {len(templates)} active email templates:\n")
        
        for template in templates:
            print(f"=== Template: {template['template_name']} ===")
            print(f"Subject: {template['subject']}")
            print(f"ID: {template['id']}")
            
            # Check for problematic characters around position 560
            html_body = template['html_body'] or ''
            plain_body = template['plain_body'] or ''
            
            # Show content around character 560 if it exists
            if len(html_body) > 560:
                start = max(0, 560 - 50)
                end = min(len(html_body), 560 + 50)
                print(f"\nHTML content around position 560:")
                print(f"Characters {start}-{end}:")
                content_slice = html_body[start:end]
                print(repr(content_slice))  # Use repr to show special characters
                
                # Highlight position 560
                print(f"\nFormatted view:")
                for i, char in enumerate(content_slice):
                    if start + i == 560:
                        print(f"[{char}]", end="")  # Highlight the problematic character
                    else:
                        print(char, end="")
                print()
            
            # Try to render the template to catch syntax errors
            try:
                print(f"\nTesting template rendering...")
                subject, html, plain = render_email_template(
                    template['template_name'],
                    user_name="Test User",
                    post_title="Test Post",
                    post_author="Test Author", 
                    post_content="Test content",
                    post_tags="test"
                )
                
                if subject and html:
                    print(f"✓ Template renders successfully")
                    print(f"  Rendered subject: {subject}")
                else:
                    print(f"✗ Template failed to render (returned None)")
                    
            except Exception as e:
                print(f"✗ Template rendering failed: {e}")
                
                # If it's a template syntax error, try to find the problematic line
                error_str = str(e)
                if "line" in error_str.lower():
                    print(f"  Error details: {error_str}")
            
            print("\n" + "="*50 + "\n")

if __name__ == "__main__":
    debug_email_templates()