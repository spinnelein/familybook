#!/bin/bash
# Wrapper script to run fix_stuck_emails.py with proper environment

# Change to the application directory
cd /var/www/apps/familybook

# Activate virtual environment (adjust path if needed)
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
elif [ -f "env/bin/activate" ]; then
    source env/bin/activate
elif [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
else
    echo "Error: Could not find virtual environment"
    echo "Looking for venv/, env/, or .venv/ directories"
    echo "Please adjust the script with your virtual environment path"
    exit 1
fi

# Run the Python script with all arguments passed through
python fix_stuck_emails.py "$@"