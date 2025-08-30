#!/bin/bash
set -e

# Familybook Ubuntu Deployment Script
# Run as root: sudo bash deploy.sh

echo "🏠 Familybook Ubuntu Deployment Script"
echo "======================================"

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo "❌ This script must be run as root (use sudo)"
   exit 1
fi

# Get configuration from user
read -p "📍 Enter your Synology NAS IP address: " SYNOLOGY_IP
read -p "📁 Enter the NFS share path (e.g., /volume1/familybook): " NFS_SHARE
read -p "🌐 Enter your domain name or server IP: " DOMAIN_NAME

echo ""
echo "🔧 Configuration:"
echo "   Synology IP: $SYNOLOGY_IP"
echo "   NFS Share: $NFS_SHARE"
echo "   Domain: $DOMAIN_NAME"
echo ""
read -p "✅ Continue with deployment? (y/N): " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "❌ Deployment cancelled"
    exit 1
fi

echo "📦 Installing system packages..."
apt update && apt upgrade -y
apt install -y python3 python3-pip python3-venv git nginx supervisor sqlite3 nfs-common ufw

echo "👤 Creating application user..."
useradd -m -s /bin/bash familybook || true
usermod -aG www-data familybook

echo "📁 Setting up NFS mount..."
mkdir -p /var/familybook/uploads

# Test NFS mount
echo "🔍 Testing NFS connection..."
if mount -t nfs -o soft,timeo=10,retrans=1 $SYNOLOGY_IP:$NFS_SHARE /var/familybook/uploads; then
    echo "✅ NFS mount successful"
    umount /var/familybook/uploads
else
    echo "❌ Failed to mount NFS share. Please check:"
    echo "   - Synology NFS service is enabled"
    echo "   - Share permissions allow this server's IP"
    echo "   - Network connectivity to Synology"
    exit 1
fi

# Add permanent mount
if ! grep -q "$SYNOLOGY_IP:$NFS_SHARE" /etc/fstab; then
    echo "$SYNOLOGY_IP:$NFS_SHARE /var/familybook/uploads nfs defaults,_netdev 0 0" >> /etc/fstab
fi
mount /var/familybook/uploads

echo "📥 Cloning repository..."
sudo -u familybook bash -c "
    cd /home/familybook
    git clone https://github.com/spinnelein/familybook.git || true
    cd familybook
    git pull origin main
"

echo "🐍 Setting up Python environment..."
sudo -u familybook bash -c "
    cd /home/familybook/familybook
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
"

echo "⚙️ Creating environment configuration..."
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
sudo -u familybook tee /home/familybook/familybook/.env << EOF
FAMILYBOOK_UPLOADS_PATH=/var/familybook/uploads
FAMILYBOOK_DATABASE_PATH=/home/familybook/familybook/familybook.db
FAMILYBOOK_SECRET_KEY=$SECRET_KEY
FLASK_ENV=production
FLASK_APP=app.py
EOF

echo "🗃️ Initializing database..."
sudo -u familybook bash -c "
    cd /home/familybook/familybook
    source venv/bin/activate
    source .env
    python3 -c 'from app import init_db; init_db()'
"

echo "🔐 Setting permissions..."
chown -R familybook:www-data /home/familybook/familybook
chmod -R 755 /home/familybook/familybook
chmod 600 /home/familybook/familybook/.env
chown -R familybook:www-data /var/familybook/uploads
chmod -R 775 /var/familybook/uploads

echo "🌐 Configuring Nginx..."
cat > /etc/nginx/sites-available/familybook << EOF
server {
    listen 80;
    server_name $DOMAIN_NAME;

    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;
    add_header X-XSS-Protection "1; mode=block";

    client_max_body_size 100M;

    location /static/ {
        alias /home/familybook/familybook/static/;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    location /uploads/ {
        alias /var/familybook/uploads/;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }
}
EOF

ln -sf /etc/nginx/sites-available/familybook /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo "🔄 Configuring Supervisor..."
cat > /etc/supervisor/conf.d/familybook.conf << EOF
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

supervisorctl reread
supervisorctl update
supervisorctl start familybook

echo "🔥 Configuring firewall..."
ufw --force enable
ufw allow ssh
ufw allow 'Nginx Full'

echo "📋 Creating backup script..."
cat > /usr/local/bin/backup-familybook << 'EOF'
#!/bin/bash
BACKUP_DIR="/var/backups/familybook"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p $BACKUP_DIR
sqlite3 /home/familybook/familybook/familybook.db ".backup $BACKUP_DIR/familybook_$DATE.db"
find $BACKUP_DIR -name "familybook_*.db" -mtime +7 -delete
echo "Backup completed: $BACKUP_DIR/familybook_$DATE.db"
EOF

chmod +x /usr/local/bin/backup-familybook
(crontab -l 2>/dev/null; echo "0 2 * * * /usr/local/bin/backup-familybook") | crontab -

echo ""
echo "🎉 Deployment Complete!"
echo "======================"
echo ""
echo "✅ Familybook is now running at: http://$DOMAIN_NAME"
echo "✅ Media uploads will be stored on Synology NAS"
echo "✅ Daily database backups are configured"
echo ""
echo "🔧 Next Steps:"
echo "1. Visit http://$DOMAIN_NAME and click the Admin link"
echo "2. Configure Google OAuth credentials in Settings"
echo "3. Create admin users and configure the system"
echo ""
echo "📊 Management Commands:"
echo "   sudo supervisorctl status familybook    # Check status"
echo "   sudo supervisorctl restart familybook   # Restart app"
echo "   sudo tail -f /var/log/familybook.log   # View logs"
echo "   sudo /usr/local/bin/backup-familybook  # Manual backup"
echo ""
echo "🔒 Consider setting up SSL/HTTPS with:"
echo "   sudo apt install certbot python3-certbot-nginx"
echo "   sudo certbot --nginx -d $DOMAIN_NAME"
echo ""