#!/bin/bash
# =============================================================
# OreX - Oracle Cloud Free Tier Deployment Script
# Run this on a fresh Ubuntu 22.04+ instance after SSH-ing in
# =============================================================

set -e

echo "=== Updating system ==="
sudo apt update && sudo apt upgrade -y

echo "=== Installing Python and Nginx ==="
sudo apt install -y python3 python3-pip python3-venv nginx git

echo "=== Cloning repository ==="
cd /home/ubuntu
git clone https://github.com/YOUR_USERNAME/at3-major-project-Zechariah-Guo.git orex
cd orex

echo "=== Creating virtual environment ==="
python3 -m venv venv
source venv/bin/activate

echo "=== Installing dependencies ==="
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn

echo "=== Generating a secret key ==="
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

echo "=== Creating environment file ==="
cat > /home/ubuntu/orex/.env << EOF
SECRET_KEY=${SECRET_KEY}
EOF

echo "=== Creating systemd service ==="
sudo tee /etc/systemd/system/orex.service > /dev/null << 'EOF'
[Unit]
Description=OreX Flask Application
After=network.target

[Service]
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/orex/src
Environment="PATH=/home/ubuntu/orex/venv/bin"
EnvironmentFile=/home/ubuntu/orex/.env
ExecStart=/home/ubuntu/orex/venv/bin/gunicorn "app:create_app()" --bind 127.0.0.1:8000 --workers 1 --timeout 120
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "=== Configuring Nginx ==="
sudo tee /etc/nginx/sites-available/orex > /dev/null << 'EOF'
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }

    location /static/ {
        alias /home/ubuntu/orex/src/static/;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/orex /etc/nginx/sites-enabled/orex
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t

echo "=== Starting services ==="
sudo systemctl daemon-reload
sudo systemctl enable orex
sudo systemctl start orex
sudo systemctl restart nginx

echo ""
echo "=== Deployment complete! ==="
echo "Your app should be running at http://$(curl -s ifconfig.me)"
echo ""
echo "Useful commands:"
echo "  sudo systemctl status orex      # Check app status"
echo "  sudo journalctl -u orex -f      # View app logs"
echo "  sudo systemctl restart orex     # Restart app"
