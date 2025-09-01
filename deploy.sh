#!/bin/bash

# FamilyBook Deployment Script
# This script pulls the latest version from GitHub, sets permissions, and restarts the service

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
PROJECT_DIR="/var/www/apps/familybook"
SERVICE_NAME="familybook"
SUDO_PASSWORD="053hbc"
BACKUP_DIR="/mnt/synology-code/Programming/familybook/localfiles"

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to run sudo commands with password
run_sudo() {
    echo "$SUDO_PASSWORD" | sudo -S "$@"
}

# Start deployment
print_status "Starting FamilyBook deployment..."
echo "=================================="

# Navigate to project directory
cd "$PROJECT_DIR" || {
    print_error "Cannot navigate to project directory: $PROJECT_DIR"
    exit 1
}

print_status "Current directory: $(pwd)"

# Create backup directory if it doesn't exist
print_status "Creating backup directory..."
mkdir -p "$BACKUP_DIR" || {
    print_error "Cannot create backup directory: $BACKUP_DIR"
    print_warning "Continuing without backup..."
    BACKUP_DIR=""
}

# Backup database and gitignored files
if [[ -n "$BACKUP_DIR" ]]; then
    print_status "Backing up local files to Synology..."
    
    # Create timestamped backup subdirectory
    TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
    BACKUP_SUBDIR="$BACKUP_DIR/backup_$TIMESTAMP"
    mkdir -p "$BACKUP_SUBDIR"
    
    # Backup database
    if [[ -f "familybook.db" ]]; then
        cp familybook.db "$BACKUP_SUBDIR/familybook.db"
        print_success "Database backed up"
    fi
    
    # Backup other important local files (gitignored)
    backup_files=(
        "*.db"
        "*.db.backup"
        "*.pickle"
        "*.json"
        "oauth_flow_state_*.json"
        "static/uploads"
        "*.log"
        "venv/lib/python*/site-packages/google*" 
    )
    
    for pattern in "${backup_files[@]}"; do
        if ls $pattern >/dev/null 2>&1; then
            cp -r $pattern "$BACKUP_SUBDIR/" 2>/dev/null || true
        fi
    done
    
    # Create a manifest of what was backed up
    echo "Backup created on: $(date)" > "$BACKUP_SUBDIR/backup_manifest.txt"
    echo "Git commit: $(git rev-parse HEAD)" >> "$BACKUP_SUBDIR/backup_manifest.txt"
    echo "Files backed up:" >> "$BACKUP_SUBDIR/backup_manifest.txt"
    ls -la "$BACKUP_SUBDIR/" >> "$BACKUP_SUBDIR/backup_manifest.txt"
    
    # Keep only the last 10 backups (cleanup old ones)
    if [[ -d "$BACKUP_DIR" ]]; then
        cd "$BACKUP_DIR"
        ls -dt backup_* | tail -n +11 | xargs -r rm -rf
        cd "$PROJECT_DIR"
    fi
    
    print_success "Local files backed up to: $BACKUP_SUBDIR"
else
    print_warning "Skipping backup - Synology mount not available"
fi

# Check git status
print_status "Checking git status..."
git status --porcelain

# Fix git permissions before stashing (git operations need user ownership)
print_status "Fixing git permissions for git operations..."
run_sudo chown -R aaron:aaron .git
run_sudo chmod -R 755 .git

# Temporarily set project files to aaron ownership for git operations
print_status "Setting temporary ownership for git operations..."
run_sudo chown -R aaron:aaron .

# Stash any local changes
if [[ -n $(git status --porcelain) ]]; then
    print_warning "Local changes detected. Stashing them..."
    git stash push -m "Auto-stash before deployment $(date)"
    print_success "Local changes stashed"
fi

# Pull latest changes from GitHub
print_status "Pulling latest changes from GitHub..."
git fetch origin
git pull origin main || {
    print_error "Failed to pull from GitHub"
    exit 1
}
print_success "Successfully pulled latest changes"

# Show what changed
print_status "Recent commits:"
git log --oneline -5

# Set file permissions
print_status "Setting file permissions..."

# Set ownership to www-data for web files (critical for socket creation)
print_status "Setting www-data ownership for entire directory..."
run_sudo chown -R www-data:www-data .

# Set proper permissions for Python files
print_status "Setting file permissions..."
run_sudo chmod 755 *.py

# Set proper permissions for templates
run_sudo chmod -R 755 templates/

# Set proper permissions for static files
run_sudo chmod -R 755 static/

# Ensure directory permissions allow socket creation
run_sudo chmod 755 .

# Remove any existing socket file that might have wrong permissions
if [[ -S "familybook.sock" ]]; then
    print_status "Removing existing socket file..."
    run_sudo rm -f familybook.sock
fi

# Make sure the database is writable by www-data
if [[ -f "familybook.db" ]]; then
    run_sudo chmod 664 familybook.db
    run_sudo chown www-data:www-data familybook.db
    print_success "Database permissions updated"
fi

# Make sure uploads directory exists and is writable
mkdir -p static/uploads
run_sudo chown -R www-data:www-data static/uploads
run_sudo chmod -R 755 static/uploads

print_success "File permissions updated"

# Initialize database (in case new tables were added)
print_status "Initializing database (checking for new tables)..."
run_sudo -u www-data ./venv/bin/python3 -c "
from app import init_db
try:
    init_db()
    print('Database initialization completed')
except Exception as e:
    print(f'Database initialization error (may be normal): {e}')
"

# Restart the familybook service
print_status "Restarting $SERVICE_NAME service..."
run_sudo systemctl restart "$SERVICE_NAME" || {
    print_error "Failed to restart $SERVICE_NAME service"
    exit 1
}

# Wait a moment for service to start
sleep 3

# Check service status
print_status "Checking service status..."
if run_sudo systemctl is-active --quiet "$SERVICE_NAME"; then
    print_success "$SERVICE_NAME service is running"
    
    # Verify socket was created
    if [[ -S "familybook.sock" ]]; then
        print_success "Socket file created successfully"
        ls -la familybook.sock
    else
        print_warning "Socket file not found - this may cause connection issues"
    fi
    
    run_sudo systemctl status "$SERVICE_NAME" --no-pager -l
else
    print_error "$SERVICE_NAME service failed to start"
    print_error "Service logs:"
    run_sudo journalctl -u "$SERVICE_NAME" -n 15 --no-pager
    exit 1
fi

# Final status
print_success "Deployment completed successfully!"
echo "=================================="
print_status "FamilyBook has been updated and restarted"
print_status "Service status: $(run_sudo systemctl is-active $SERVICE_NAME)"
print_status "You can access the application at: http://home.slugranch.org/familybook/"

# Show any stashed changes reminder
if git stash list | grep -q "Auto-stash before deployment"; then
    print_warning "Reminder: Local changes were stashed. Use 'git stash pop' to restore them if needed."
fi