#!/usr/bin/env python3
"""
Alternative runner that uses subprocess to run fix_stuck_emails.py
with the same Python interpreter that runs the web application.
"""

import subprocess
import sys
import os

# Find the Python interpreter used by the service
# Check common locations for virtual environments
venv_paths = [
    'venv/bin/python',
    'env/bin/python', 
    '.venv/bin/python',
    'venv/bin/python3',
    'env/bin/python3',
    '.venv/bin/python3',
]

app_dir = '/var/www/apps/familybook'
python_exe = None

# Try to find the virtual environment Python
for venv_path in venv_paths:
    full_path = os.path.join(app_dir, venv_path)
    if os.path.exists(full_path):
        python_exe = full_path
        break

if not python_exe:
    # Check if wsgi.py has a shebang that tells us the Python path
    wsgi_path = os.path.join(app_dir, 'wsgi.py')
    if os.path.exists(wsgi_path):
        with open(wsgi_path, 'r') as f:
            first_line = f.readline()
            if first_line.startswith('#!'):
                python_exe = first_line[2:].strip()

if not python_exe:
    print("Error: Could not find virtual environment Python interpreter")
    print("Please edit this script to set the correct path")
    sys.exit(1)

# Run the fix_stuck_emails.py script with the found Python
script_path = os.path.join(app_dir, 'fix_stuck_emails.py')
args = [python_exe, script_path] + sys.argv[1:]

print(f"Running: {' '.join(args)}")
subprocess.run(args)