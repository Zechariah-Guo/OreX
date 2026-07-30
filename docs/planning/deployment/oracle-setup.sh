#!/bin/bash
# =============================================================
# OreX - Oracle Cloud Free Tier Deployment Script
# Run this on a fresh Ubuntu 22.04+ ARM instance after SSH-ing in
#
# Stack: cloudflared → Nginx → Gunicorn (port 4000)
# =============================================================

set -e

echo "=== Updating system ==="
sudo apt update && sudo apt upgrade -y

echo "=== Installing Python, Nginx, and Git ==="
sudo apt install -y python3 python3-pip python3-venv nginx git curl

echo "=== Cloning repository ==="
cd /home/ubuntu
git clone https://github.com/YOUR_USERNAME/OreX.git orex
cd orex

echo "=== Creating virtual environment ==="
python3 -m venv venv
source venv/bin/activate

echo "=== Installing dependencies ==="
pip install --upgrade pip
pip install -r requirements.txt
pip install -r docs/planning/deployment/requirements-prod.txt

echo "=== Generating a secret key ==="
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

echo "=== Creating environment file ==="
cat > /home/ubuntu/orex/.env << EOF
SECRET_KEY=${SECRET_KEY}
EOF

echo "=== Creating systemd service (port 4000) ==="
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
ExecStart=/home/ubuntu/orex/venv/bin/gunicorn "app:create_app()" --bind 127.0.0.1:4000 --workers 1 --timeout 120
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "=== Starting OreX service ==="
sudo systemctl daemon-reload
sudo systemctl enable orex
sudo systemctl start orex

echo "=== Configuring Nginx ==="
sudo rm -f /etc/nginx/sites-enabled/default

sudo tee /etc/nginx/sites-available/orex > /dev/null << 'EOF'
server {
    listen 80;
    server_name orex.mochizou.works;

    location /static/ {
        alias /home/ubuntu/orex/src/static/;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }

    location / {
        proxy_pass http://127.0.0.1:4000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        proxy_buffering on;
    }

    error_page 502 503 504 /maintenance.html;
    location = /maintenance.html {
        root /home/ubuntu/orex/src/static;
        internal;
    }
}
EOF

sudo tee /etc/nginx/sites-available/redstoneregister > /dev/null << 'EOF'
server {
    listen 80;
    server_name redstoneregister.mochizou.works;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        proxy_buffering on;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/orex /etc/nginx/sites-enabled/orex
sudo ln -sf /etc/nginx/sites-available/redstoneregister /etc/nginx/sites-enabled/redstoneregister
sudo nginx -t
sudo systemctl enable nginx
sudo systemctl restart nginx

echo "=== Creating maintenance page ==="
cat > /home/ubuntu/orex/src/static/maintenance.html << 'EOF'
<!DOCTYPE html>
<html>
<head><title>OreX - Maintenance</title></head>
<body style="font-family: sans-serif; text-align: center; padding: 50px;">
  <h1>OreX is temporarily down for maintenance</h1>
  <p>We'll be back shortly.</p>
</body>
</html>
EOF

echo "=== Installing cloudflared ==="
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb -o /tmp/cloudflared.deb
sudo dpkg -i /tmp/cloudflared.deb
rm /tmp/cloudflared.deb

echo ""
echo "=== Setup complete! ==="
echo ""
echo "OreX is running on localhost:4000 behind Nginx on port 80"
echo ""
echo "Next steps (manual — require browser auth):"
echo "  1. Run: cloudflared tunnel login"
echo "  2. Run: cloudflared tunnel create orex-tunnel"
echo "  3. Create ~/.cloudflared/config.yml with your tunnel ID"
echo "  4. Run: cloudflared tunnel route dns orex-tunnel orex.mochizou.works"
echo "  5. Run: cloudflared tunnel route dns orex-tunnel redstoneregister.mochizou.works"
echo "  6. Run: sudo cloudflared service install"
echo "  7. Run: sudo systemctl enable cloudflared && sudo systemctl start cloudflared"
echo ""
echo "Useful commands:"
echo "  sudo systemctl status orex          # Check app status"
echo "  sudo systemctl status nginx         # Check Nginx status"
echo "  sudo systemctl status cloudflared   # Check tunnel status"
echo "  sudo journalctl -u orex -f          # View app logs"
