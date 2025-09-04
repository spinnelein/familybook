#!/usr/bin/env python3
"""
Fix email templates by converting Handlebars syntax to Jinja2 syntax.

Converts:
- {{#variable}} ... {{/variable}} → {% if variable %} ... {% endif %}
- {{variable}} → {{ variable }} (these stay the same)
"""

import sys
import os
import re

# Add the app directory to the Python path
sys.path.insert(0, os.path.dirname(__file__))

from app import app
from db.database import get_db

def convert_handlebars_to_jinja2(template_content):
    """Convert Handlebars template syntax to Jinja2"""
    if not template_content:
        return template_content
    
    # Convert {{#variable}} to {% if variable %}
    content = re.sub(r'\{\{#(\w+)\}\}', r'{% if \1 %}', template_content)
    
    # Convert {{/variable}} to {% endif %}
    content = re.sub(r'\{\{/\w+\}\}', '{% endif %}', content)
    
    # Handle {{#each}} loops if they exist
    content = re.sub(r'\{\{#each (\w+)\}\}', r'{% for item in \1 %}', content)
    content = re.sub(r'\{\{/each\}\}', '{% endfor %}', content)
    
    return content

def fix_email_templates(dry_run=True):
    """Fix all email templates by converting syntax"""
    with app.app_context():
        db = get_db()
        
        # Get all email templates
        templates = db.execute('SELECT * FROM email_templates').fetchall()
        
        print(f"Found {len(templates)} email templates to check:\n")
        
        changes_made = 0
        
        for template in templates:
            template_id = template['id']
            template_name = template['template_name']
            html_body = template['html_body'] or ''
            plain_body = template['plain_body'] or ''
            
            print(f"=== Template: {template_name} (ID: {template_id}) ===")
            
            # Check if conversion is needed
            needs_html_fix = '{{#' in html_body or '{{/' in html_body
            needs_plain_fix = '{{#' in plain_body or '{{/' in plain_body
            
            if not needs_html_fix and not needs_plain_fix:
                print("  ✓ No Handlebars syntax found - template is OK")
                continue
            
            # Convert templates
            new_html_body = convert_handlebars_to_jinja2(html_body)
            new_plain_body = convert_handlebars_to_jinja2(plain_body)
            
            # Show changes
            if needs_html_fix:
                print("  HTML Body Changes:")
                if '{{#' in html_body:
                    handlebars_matches = re.findall(r'\{\{#\w+\}\}.*?\{\{/\w+\}\}', html_body, re.DOTALL)
                    for i, match in enumerate(handlebars_matches[:3]):  # Show first 3 matches
                        print(f"    BEFORE: {match[:100]}...")
                        converted = convert_handlebars_to_jinja2(match)
                        print(f"    AFTER:  {converted[:100]}...")
                
            if needs_plain_fix:
                print("  Plain Body Changes:")
                if '{{#' in plain_body:
                    handlebars_matches = re.findall(r'\{\{#\w+\}\}.*?\{\{/\w+\}\}', plain_body, re.DOTALL)
                    for i, match in enumerate(handlebars_matches[:2]):  # Show first 2 matches
                        print(f"    BEFORE: {match[:100]}...")
                        converted = convert_handlebars_to_jinja2(match)
                        print(f"    AFTER:  {converted[:100]}...")
            
            if dry_run:
                print("  [DRY RUN] Would update this template")
            else:
                # Update the database
                try:
                    db.execute('''UPDATE email_templates 
                                SET html_body = ?, plain_body = ? 
                                WHERE id = ?''',
                             (new_html_body, new_plain_body, template_id))
                    db.commit()
                    print("  ✓ Template updated successfully")
                    changes_made += 1
                except Exception as e:
                    print(f"  ✗ Failed to update template: {e}")
            
            print()
        
        if dry_run:
            print("\n=== DRY RUN MODE ===")
            print("No changes were made. Run with --execute to apply fixes.")
        else:
            print(f"\n✓ Updated {changes_made} email templates")
            print("Email templates should now work with Jinja2!")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Fix email template syntax from Handlebars to Jinja2')
    parser.add_argument('--execute', action='store_true', help='Actually fix the templates (without this flag, runs in dry-run mode)')
    args = parser.parse_args()
    
    fix_email_templates(dry_run=not args.execute)