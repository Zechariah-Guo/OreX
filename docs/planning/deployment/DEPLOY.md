# Deploying OreX to Oracle Cloud Free Tier

## Step 1: Create an Oracle Cloud Account

1. Go to [cloud.oracle.com](https://cloud.oracle.com) and sign up
2. You'll need a credit card for verification (you won't be charged)
3. Choose your home region (pick one close to your players)

## Step 2: Create a Free Tier VM

1. Go to **Compute → Instances → Create Instance**
2. Configure:
   - **Name:** orex
   - **Image:** Ubuntu 22.04 (or 24.04)
   - **Shape:** VM.Standard.A1.Flex (ARM) — set to 1 OCPU, 1 GB RAM
   - **Networking:** Create a new VCN with public subnet (defaults are fine)
   - **SSH key:** Upload your public key or let Oracle generate one (download it!)
3. Click **Create**

> The Always Free tier gives you up to 4 ARM OCPUs and 24 GB RAM total.
> 1 OCPU + 1 GB is more than enough for OreX.

## Step 3: Open Port 80 (HTTP)

1. Go to **Networking → Virtual Cloud Networks** → your VCN
2. Click your **public subnet** → **Default Security List**
3. **Add Ingress Rule:**
   - Source CIDR: `0.0.0.0/0`
   - Destination Port: `80`
   - Protocol: TCP
4. Also open port **443** if you plan to add HTTPS later

Then on the instance itself, run:
```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo netfilter-persistent save
```

## Step 4: SSH into the Instance

```bash
ssh -i /path/to/your-key.pem ubuntu@YOUR_INSTANCE_IP
```

## Step 5: Deploy the App

Option A — Run the setup script:
```bash
# Upload the script or clone the repo first, then:
chmod +x deploy/oracle-setup.sh
./deploy/oracle-setup.sh
```

Option B — Manual steps (if you prefer):
```bash
# Update system
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv nginx git

# Clone your repo
git clone https://github.com/YOUR_USERNAME/at3-major-project-Zechariah-Guo.git orex
cd orex

# Set up Python
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install gunicorn

# Test it works
cd src
gunicorn "app:create_app()" --bind 0.0.0.0:8000 --workers 1
# Ctrl+C to stop after confirming it starts
```

Then set up the systemd service and Nginx as shown in `oracle-setup.sh`.

## Step 6: Verify

Visit `http://YOUR_INSTANCE_IP` in your browser. You should see OreX running.

## Updating the App

When you push new code:
```bash
cd /home/ubuntu/orex
git pull
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart orex
```

## Backing Up the Database

The SQLite database lives at `/home/ubuntu/orex/src/data/orex.db`. To back it up:
```bash
cp /home/ubuntu/orex/src/data/orex.db /home/ubuntu/orex-backup-$(date +%Y%m%d).db
```

Consider setting up a cron job for daily backups:
```bash
crontab -e
# Add this line:
0 3 * * * cp /home/ubuntu/orex/src/data/orex.db /home/ubuntu/backups/orex-$(date +\%Y\%m\%d).db
```

## Optional: Add HTTPS with Let's Encrypt

If you get a free domain (e.g., from freenom or use a subdomain you own):
```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com
```

## Optional: Free Domain

If you don't have a domain, you can use services like:
- **DuckDNS** (free dynamic DNS subdomain)
- **No-IP** (free subdomain)

These give you a memorable URL instead of a raw IP address.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Can't connect to port 80 | Check both OCI security list AND iptables (Step 3) |
| App crashes on start | Check logs: `sudo journalctl -u orex -n 50` |
| 502 Bad Gateway | Gunicorn isn't running: `sudo systemctl status orex` |
| Database permission error | Fix ownership: `sudo chown -R ubuntu:ubuntu /home/ubuntu/orex/src/data` |
