# OreX Deployment Plans

Complete deployment guide for hosting OreX on Oracle Cloud Free Tier with Cloudflare Tunnels and a custom domain.

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│                     name.com (GitHub Student Dev Pack)       │
│                     Domain: mochizou.works (1 year free)     │
└──────────────────────┬───────────────────────────────────────┘
                       │ Nameservers pointed to Cloudflare
                       ▼
┌──────────────────────────────────────────────────────────────┐
│                     Cloudflare (Free Plan)                   │
│                                                              │
│  orex.mochizou.works ─────────────────► Tunnel               │
│  redstoneregister.mochizou.works ─────► Tunnel               │
│                                                              │
│  + Free SSL/TLS, DDoS protection, edge caching               │
└──────────────────────┬───────────────────────────────────────┘
                       │ Cloudflare Tunnel (cloudflared)
                       ▼
┌──────────────────────────────────────────────────────────────┐
│              Oracle Cloud Free Tier VM (Ubuntu)              │
│              ARM Ampere A1 — 1 OCPU, 1 GB RAM                │
│                                                              │
│  cloudflared ──► Nginx (port 80)                             │
│                    ├── orex.mochizou.works                   │
│                    │     ├── /static/ → served directly      │
│                    │     └── /* → proxy to Gunicorn :4000    │
│                    └── redstoneregister.mochizou.works       │
│                          └── /* → proxy to localhost :5000   │
│                                                              │
│  Gunicorn :4000 — OreX (Flask)                               │
│  Port :5000 — RedstoneRegister (separate project)            │
└──────────────────────────────────────────────────────────────┘
```

**Why Nginx between cloudflared and Gunicorn?**
- Serves static files (CSS, JS, images) directly without wasting Python worker processes
- Buffers slow client responses so Gunicorn workers are freed immediately
- Provides failover/maintenance pages if Gunicorn goes down
- Enables load balancing across multiple workers if the app grows later

---

## 1. Oracle Cloud Free Tier — What You Get

Oracle's free tier is split into a **30-day trial** ($300 credits) and permanent **Always Free** resources:

| Resource | Always Free Allocation |
|----------|----------------------|
| ARM Compute (Ampere A1) | Up to 2 vCPUs, 12 GB RAM |
| x86 Compute (AMD Micro) | 2 instances, 1 GB RAM each |
| Block Volume Storage | 200 GB total |
| Object Storage | 10 GB |
| Outbound Bandwidth | 10 TB/month |

For OreX, 1 OCPU + 1 GB RAM is more than enough. This leaves capacity for a second project on the same VM.

---

## 2. Oracle Cloud Signup

Oracle is strict during registration to block bot farms. Follow these steps:

1. Go to [Oracle Free Tier Sign Up](https://signup.oraclecloud.com/)
2. Use a **real physical credit/debit card** — Oracle does a temporary $1 auth charge and reverses it. Prepaid/virtual cards will get your account flagged.
3. **Choose your Home Region** carefully — Always Free resources can only deploy here and it **cannot be changed later**. Pick something geographically close to your players.
4. **"Out of Capacity" workaround**: If you hit this error when creating an ARM instance, upgrade your account to **Pay-As-You-Go (PAYG)** in the console. You won't be charged for free-tier resources, but it puts you in a priority queue that unlocks hardware.

---

## 3. Create the VM Instance

1. Go to **Compute → Instances → Create Instance**
2. Configure:
   - **Name:** orex-vm
   - **Image:** Ubuntu 22.04 or 24.04
   - **Shape:** VM.Standard.A1.Flex (ARM) — 1 OCPU, 1 GB RAM
   - **Networking:** Create a new VCN with public subnet (defaults are fine)
   - **SSH key:** Upload your public key or let Oracle generate one (download it!)
3. Click **Create**

---

## 4. Domain Setup — name.com + Cloudflare

### 4.1 Register Domain via GitHub Student Developer Pack

1. Redeem the **name.com** offer through the [GitHub Student Developer Pack](https://education.github.com/pack)
2. Register: **mochizou.works** (1 year free)
3. Don't configure any DNS records on name.com yet — Cloudflare will handle all DNS

### 4.2 Add Domain to Cloudflare

1. Create a free [Cloudflare account](https://dash.cloudflare.com/sign-up)
2. Click **Add a Site** → enter `mochizou.works`
3. Select the **Free plan**
4. Cloudflare will assign you **2 nameservers** (e.g., `ada.ns.cloudflare.com`, `ben.ns.cloudflare.com`)

### 4.3 Update Nameservers on name.com

1. Go to your name.com domain management dashboard
2. Under **Nameservers**, remove the default name.com nameservers
3. Replace with the 2 Cloudflare nameservers
4. Save — propagation takes up to 24 hours but usually under an hour

### 4.4 Configure DNS Records on Cloudflare

Once the domain is active on Cloudflare, add these CNAME records (the tunnel will create these automatically during setup, but for reference):

| Type | Name | Content | Proxy |
|------|------|---------|-------|
| CNAME | orex | `<tunnel-id>.cfargotunnel.com` | Proxied |
| CNAME | redstoneregister | `<tunnel-id>.cfargotunnel.com` | Proxied |

### 4.5 SSL/TLS Settings

1. In Cloudflare dashboard → **SSL/TLS** → set mode to **Full (strict)**
2. Cloudflare handles HTTPS termination automatically — no need for Let's Encrypt or certbot on the VM

---

## 5. VM Server Setup

### 5.1 SSH into the Instance

```bash
ssh -i /path/to/your-key.pem ubuntu@YOUR_INSTANCE_IP
```

### 5.2 System Dependencies

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv nginx git
```

### 5.3 Clone and Set Up OreX

```bash
cd /home/ubuntu
git clone https://github.com/YOUR_USERNAME/OreX.git orex
cd orex

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies (includes prod extras like gunicorn)
pip install --upgrade pip
pip install -r requirements.txt
pip install -r docs/planning/deployment/requirements-prod.txt
```

### 5.4 Environment Configuration

```bash
# Generate a secret key
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

# Create .env file
cat > /home/ubuntu/orex/.env << EOF
SECRET_KEY=${SECRET_KEY}
# Trust Nginx's X-Forwarded-For/-Proto (one hop) for client IP and https
OREX_TRUST_PROXY=1
EOF
```

### 5.5 Create systemd Service for OreX (Port 4000)

```bash
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

sudo systemctl daemon-reload
sudo systemctl enable orex
sudo systemctl start orex
```

Verify it's running:
```bash
sudo systemctl status orex
curl http://127.0.0.1:4000
```

### 5.6 Configure Nginx as Reverse Proxy

Nginx sits between cloudflared and Gunicorn, handling static files, buffering, and routing by hostname.

```bash
# Remove default site
sudo rm -f /etc/nginx/sites-enabled/default

# Create OreX server block
sudo tee /etc/nginx/sites-available/orex > /dev/null << 'EOF'
server {
    listen 80;
    server_name orex.mochizou.works;

    # Requests arrive from cloudflared on 127.0.0.1: take the real client IP from Cloudflare
    set_real_ip_from 127.0.0.1;
    real_ip_header CF-Connecting-IP;

    # Serve static files directly — bypass Gunicorn entirely
    location /static/ {
        alias /home/ubuntu/orex/src/static/;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }

    # Proxy everything else to Gunicorn
    location / {
        proxy_pass http://127.0.0.1:4000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        proxy_buffering on;
    }

    # Custom error page when Gunicorn is down
    error_page 502 503 504 /maintenance.html;
    location = /maintenance.html {
        root /home/ubuntu/orex/src/static;
        internal;
    }
}
EOF

# Create RedstoneRegister server block
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

# Enable both sites
sudo ln -sf /etc/nginx/sites-available/orex /etc/nginx/sites-enabled/orex
sudo ln -sf /etc/nginx/sites-available/redstoneregister /etc/nginx/sites-enabled/redstoneregister

# Test config and start
sudo nginx -t
sudo systemctl enable nginx
sudo systemctl restart nginx
```

Optionally create a maintenance page so users see something friendly if Gunicorn crashes:
```bash
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
```

---

## 6. Install and Configure Cloudflared

### 6.1 Install cloudflared

```bash
# Download the latest cloudflared for ARM64
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb -o cloudflared.deb
sudo dpkg -i cloudflared.deb
rm cloudflared.deb
```

### 6.2 Authenticate with Cloudflare

```bash
cloudflared tunnel login
```

This opens a browser URL — paste it into your local browser, select `mochizou.works`, and authorize. A cert is saved to `~/.cloudflared/cert.pem`.

### 6.3 Create a Tunnel

```bash
cloudflared tunnel create orex-tunnel
```

This creates a tunnel and outputs a **Tunnel ID** (a UUID). Note it down.

### 6.4 Configure the Tunnel for Both Projects

The tunnel points to Nginx on port 80, which then routes by hostname to the correct backend.

```bash
mkdir -p ~/.cloudflared

cat > ~/.cloudflared/config.yml << EOF
tunnel: <TUNNEL_ID>
credentials-file: /home/ubuntu/.cloudflared/<TUNNEL_ID>.json

ingress:
  - hostname: orex.mochizou.works
    service: http://localhost:80
  - hostname: redstoneregister.mochizou.works
    service: http://localhost:80
  - service: http_status:404
EOF
```

Replace `<TUNNEL_ID>` with your actual tunnel UUID.

> **Why both point to port 80:** Nginx uses the `Host` header to determine which server block handles the request. Cloudflared passes the hostname through, so Nginx routes `orex.*` to Gunicorn on :4000 and `redstoneregister.*` to :5000 automatically.

### 6.5 Route DNS

```bash
cloudflared tunnel route dns orex-tunnel orex.mochizou.works
cloudflared tunnel route dns orex-tunnel redstoneregister.mochizou.works
```

This automatically creates the CNAME records in Cloudflare DNS.

### 6.6 Run cloudflared as a systemd Service

```bash
sudo cloudflared service install
sudo systemctl enable cloudflared
sudo systemctl start cloudflared
```

Verify:
```bash
sudo systemctl status cloudflared
```

---

## 7. Oracle Cloud Firewall — Simplified

Since Cloudflare Tunnels create an outbound connection from your VM to Cloudflare's edge (no inbound traffic needed), you do **not** need to open ports 80/443 in Oracle's security list or iptables. The tunnel punches through NAT and firewalls automatically.

This is a security advantage — your VM has zero publicly exposed ports.

---

## 8. Verify the Deployment

1. Visit `https://orex.mochizou.works` — should show OreX running with full HTTPS
2. Check Cloudflare dashboard → **Traffic** to confirm requests are flowing
3. On the VM, confirm both services:
   ```bash
   sudo systemctl status orex
   sudo systemctl status cloudflared
   ```

---

## 9. Development Workflow

Do not edit code directly on the production VM. Maintain a strict local → remote lifecycle:

```
Local Machine          GitHub             Production VM
─────────────          ──────             ─────────────
Code & test    ──►    Push to repo   ──►  git pull
                                          restart service
```

### Deploying Updates

```bash
ssh -i /path/to/key.pem ubuntu@YOUR_INSTANCE_IP

cd /home/ubuntu/orex
git pull
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart orex
```

---

## 10. Database Management

### SQLite File Location
The database lives at `/home/ubuntu/orex/src/data/orex.db`.

### Initial Setup
The repo ships no database (`src/data/*.db` is gitignored). On first start the app creates `orex.db` from `schema.sql` and `seed.sql`.

### Automated Backups
```bash
sudo apt install -y sqlite3
mkdir -p /home/ubuntu/backups
crontab -e
# Add:
0 3 * * * sqlite3 /home/ubuntu/orex/src/data/orex.db ".backup '/home/ubuntu/backups/orex-$(date +\%Y\%m\%d).db'"
```

`sqlite3 ... ".backup"` takes a consistent snapshot while the app is running. A plain `cp` can miss recent writes because the database runs in WAL mode (recent changes sit in `orex.db-wal` until a checkpoint).

---

## 11. Troubleshooting

| Problem | Fix |
|---------|-----|
| Can't reach `orex.mochizou.works` | Check `sudo systemctl status cloudflared` and verify DNS propagation |
| App crashes on start | Check logs: `sudo journalctl -u orex -n 50` |
| Tunnel not connecting | Re-run `cloudflared tunnel login` to refresh creds |
| 502 from Cloudflare | Check Nginx: `sudo systemctl status nginx` then Gunicorn: `sudo systemctl status orex` |
| Nginx config error | Test with `sudo nginx -t`, check `/var/log/nginx/error.log` |
| Maintenance page showing | Gunicorn is down — `sudo systemctl restart orex` |
| Database permission error | `sudo chown -R ubuntu:ubuntu /home/ubuntu/orex/src/data` |
| Domain not resolving | Verify nameservers were updated on name.com, wait for propagation |
| Second project not working | Ensure port 5000 service is running and Nginx site is enabled |

---

## 12. Useful Commands Reference

```bash
# App management
sudo systemctl status orex
sudo systemctl restart orex
sudo journalctl -u orex -f

# Nginx management
sudo systemctl status nginx
sudo systemctl restart nginx
sudo nginx -t                          # Test config before restarting
tail -f /var/log/nginx/error.log       # Nginx error logs
tail -f /var/log/nginx/access.log      # Nginx access logs

# Tunnel management
sudo systemctl status cloudflared
sudo systemctl restart cloudflared
sudo journalctl -u cloudflared -f

# Check what's listening
sudo ss -tlnp | grep -E '80|4000|5000'
```

---

## 13. Cost Summary

| Service | Cost |
|---------|------|
| Oracle Cloud VM | Free forever (Always Free tier) |
| Domain (name.com via GitHub Student Pack) | Free for 1 year |
| Cloudflare (Free plan) | Free |
| SSL/TLS certificates | Free (Cloudflare handles it) |
| **Total** | **$0** |
