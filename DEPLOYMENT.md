# Familybook Ubuntu Deployment Guide

This guide covers deploying Familybook on Ubuntu with Synology NAS mounting for media storage.

## Prerequisites

- Ubuntu server (20.04+ recommended)
- Synology NAS with NFS or SMB/CIFS shares enabled
- Python 3.8+
- Git

## 1. Server Setup

### Update System
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3 python3-pip python3-venv git nginx supervisor sqlite3 -y
```

### Create Application User
```bash
sudo useradd -m -s /bin/bash familybook
sudo usermod -aG www-data familybook
```

## 2. Synology NAS Configuration

### Option A: NFS Share (Recommended)
1. **On Synology DSM:**
   - Control Panel → File Services → NFS
   - Enable NFS service
   - Control Panel → Shared Folder → Create or edit folder
   - NFS Permissions → Create rule:
     - Hostname/IP: `your-ubuntu-server-ip`
     - Privilege: Read/Write
     - Squash: Map all users to admin
     - Security: sys

2. **On Ubuntu Server:**
```bash
# Install NFS utilities
sudo apt install nfs-common -y

# Create mount point
sudo mkdir -p /var/familybook/uploads

# Test mount (replace with your Synology IP and path)
sudo mount -t nfs 192.168.1.100:/volume1/familybook /var/familybook/uploads

# Make permanent by adding to /etc/fstab
echo "192.168.1.100:/volume1/familybook /var/familybook/uploads nfs defaults,_netdev 0 0" | sudo tee -a /etc/fstab
```

### Option B: SMB/CIFS Share
1. **On Synology DSM:**
   - Control Panel → File Services → SMB
   - Enable SMB service
   - Create or configure shared folder

2. **On Ubuntu Server:**
```bash
# Install CIFS utilities
sudo apt install cifs-utils -y

# Create credentials file
sudo mkdir -p /etc/familybook
sudo tee /etc/familybook/synology-creds << EOF
username=your-synology-username
password=your-synology-password
domain=your-domain-or-blank
EOF
sudo chmod 600 /etc/familybook/synology-creds

# Create mount point
sudo mkdir -p /var/familybook/uploads

# Add to /etc/fstab
echo "//192.168.1.100/familybook /var/familybook/uploads cifs credentials=/etc/familybook/synology-creds,uid=familybook,gid=www-data,iocharset=utf8,vers=3.0,_netdev 0 0" | sudo tee -a /etc/fstab

# Mount
sudo mount /var/familybook/uploads
```

## 3. Application Deployment

### Clone Repository
```bash
sudo -u familybook bash
cd /home/familybook
git clone https://github.com/spinnelein/familybook.git
cd familybook
```

### Setup Python Environment
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Configure Environment Variables
```bash
# Create environment file
cat > .env << EOF
# Uploads path (points to Synology mount)
FAMILYBOOK_UPLOADS_PATH=/var/familybook/uploads

# Database path
FAMILYBOOK_DATABASE_PATH=/home/familybook/familybook/familybook.db

# Security (generate a strong secret key)
FAMILYBOOK_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")

# Flask environment
FLASK_ENV=production
FLASK_APP=app.py
EOF

# Set secure permissions
chmod 600 .env
```

### Initialize Database
```bash
source venv/bin/activate
source .env
python3 -c "from app import init_db; init_db()"
```

### Set Permissions
```bash
# Give familybook user ownership
sudo chown -R familybook:www-data /home/familybook/familybook
sudo chmod -R 755 /home/familybook/familybook

# Ensure uploads directory is writable
sudo chown -R familybook:www-data /var/familybook/uploads
sudo chmod -R 775 /var/familybook/uploads
```

## 4. Web Server Configuration

### Nginx Configuration
```bash
sudo tee /etc/nginx/sites-available/familybook << 'EOF'
server {
    listen 80;
    server_name your-domain.com;  # Replace with your domain or IP

    # Security headers
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;
    add_header X-XSS-Protection "1; mode=block";

    # Upload size limit
    client_max_body_size 100M;

    # Static files served directly by nginx
    location /static/ {
        alias /home/familybook/familybook/static/;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # Uploads served from Synology mount
    location /uploads/ {
        alias /var/familybook/uploads/;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # Application
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }
}
EOF

# Enable site
sudo ln -sf /etc/nginx/sites-available/familybook /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

## 5. Process Management with Supervisor

### Supervisor Configuration
```bash
sudo tee /etc/supervisor/conf.d/familybook.conf << 'EOF'
[program:familybook]
command=/home/familybook/familybook/venv/bin/python app.py
directory=/home/familybook/familybook
user=familybook
environment=PATH="/home/familybook/familybook/venv/bin"
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/familybook.log
stdout_logfile_maxbytes=50MB
stdout_logfile_backups=5
EOF

# Update supervisor and start application
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start familybook
```

## 6. SSL Configuration (Optional but Recommended)

### Using Let's Encrypt with Certbot
```bash
# Install Certbot
sudo apt install certbot python3-certbot-nginx -y

# Get certificate (replace with your domain)
sudo certbot --nginx -d your-domain.com

# Auto-renewal is set up automatically
```

## 7. Firewall Configuration

```bash
# Enable UFW
sudo ufw enable

# Allow essential services
sudo ufw allow ssh
sudo ufw allow 'Nginx Full'

# Check status
sudo ufw status
```

## 8. Monitoring and Maintenance

### Log Monitoring
```bash
# Application logs
sudo tail -f /var/log/familybook.log

# Nginx logs
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log

# System logs
sudo journalctl -u supervisor -f
```

### Backup Strategy
```bash
# Database backup script
sudo tee /usr/local/bin/backup-familybook << 'EOF'
#!/bin/bash
BACKUP_DIR="/var/backups/familybook"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p $BACKUP_DIR

# Backup database
sqlite3 /home/familybook/familybook/familybook.db ".backup $BACKUP_DIR/familybook_$DATE.db"

# Keep only last 7 days of backups
find $BACKUP_DIR -name "familybook_*.db" -mtime +7 -delete

echo "Backup completed: $BACKUP_DIR/familybook_$DATE.db"
EOF

sudo chmod +x /usr/local/bin/backup-familybook

# Add to crontab for daily backups at 2 AM
(crontab -l 2>/dev/null; echo "0 2 * * * /usr/local/bin/backup-familybook") | crontab -
```

## 9. Initial Setup

1. **Access the application**: `http://your-server-ip`
2. **Click the Admin link** in bottom-right corner
3. **Configure OAuth** (you'll have direct access since OAuth isn't configured yet):
   - Go to Settings page
   - Add Google OAuth Client ID and Secret
   - Set redirect URI to: `http://your-domain.com/admin/oauth/callback`
4. **Create admin users** and assign admin privileges
5. **Test email notifications** (optional)

## 10. Updating the Application

```bash
sudo -u familybook bash
cd /home/familybook/familybook
source venv/bin/activate

# Pull latest changes
git pull origin main

# Install any new dependencies
pip install -r requirements.txt

# Restart application
sudo supervisorctl restart familybook
```

## Environment Variables Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `FAMILYBOOK_UPLOADS_PATH` | `static/uploads` | Path to uploads directory (set to Synology mount) |
| `FAMILYBOOK_DATABASE_PATH` | `familybook.db` | Path to SQLite database file |
| `FAMILYBOOK_SECRET_KEY` | `your-secret-key-change-this-in-production` | Flask secret key (generate random) |

## Troubleshooting

### Mount Issues
```bash
# Check if mount is active
df -h | grep familybook

# Remount if needed
sudo umount /var/familybook/uploads
sudo mount /var/familybook/uploads

# Check NFS/CIFS connectivity
showmount -e 192.168.1.100  # For NFS
smbclient -L 192.168.1.100   # For SMB/CIFS
```

### Application Issues
```bash
# Check application status
sudo supervisorctl status familybook

# View logs
sudo tail -f /var/log/familybook.log

# Restart services
sudo supervisorctl restart familybook
sudo systemctl restart nginx
```

### Permission Issues
```bash
# Fix upload permissions
sudo chown -R familybook:www-data /var/familybook/uploads
sudo chmod -R 775 /var/familybook/uploads

# Fix application permissions
sudo chown -R familybook:www-data /home/familybook/familybook
```

## Security Considerations

1. **Change default secret key** in production
2. **Use HTTPS** (SSL/TLS) for all connections
3. **Configure firewall** to restrict access
4. **Regular updates** of OS and application
5. **Monitor logs** for suspicious activity
6. **Backup regularly** and test restore procedures
7. **Limit admin users** to trusted individuals only

This configuration provides a robust, scalable deployment with efficient media storage on Synology NAS while keeping the database and application on the Ubuntu server for optimal performance.