#!/bin/bash
set -e

echo "=== Deploy Telethon Monitor Dashboard ==="

# 1. Deploy monitor files
echo "[1/6] Copying monitor files..."
cp -r /root/Egor_fix_python/monitor/monitor_app.py /root/monitor/
cp -r /root/Egor_fix_python/monitor/templates/ /root/monitor/
cp -r /root/Egor_fix_python/monitor/static/ /root/monitor/
cp -r /root/Egor_fix_python/monitor/requirements.txt /root/monitor/

# 2. Install requirements
echo "[2/6] Installing Python dependencies..."
/root/telethon_env/bin/pip install -r /root/monitor/requirements.txt

# 3. Deploy systemd service
echo "[3/6] Setting up systemd service..."
cp /root/Egor_fix_python/monitor/telethon-monitor.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable telethon-monitor.service
systemctl restart telethon-monitor.service

echo "Waiting for monitor to start..."
sleep 3
systemctl status telethon-monitor.service --no-pager || true

# 4. Deploy nginx config (HTTP only first for certbot)
echo "[4/6] Setting up nginx (HTTP only for certbot)..."
cat > /etc/nginx/sites-available/rumyantsevdash.other-digital.ru <<'NGINX'
server {
    listen 80;
    server_name rumyantsevdash.other-digital.ru;

    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    location / {
        proxy_pass http://127.0.0.1:5099;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300;
    }
}
NGINX

ln -sf /etc/nginx/sites-available/rumyantsevdash.other-digital.ru /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

# 5. Get SSL certificate
echo "[5/6] Getting SSL certificate with certbot..."
certbot --nginx -d rumyantsevdash.other-digital.ru --non-interactive --agree-tos --redirect --email admin@other-digital.ru

# 6. Verify
echo "[6/6] Verifying..."
systemctl status telethon-monitor.service --no-pager || true
curl -sk https://rumyantsevdash.other-digital.ru/health 2>/dev/null || echo "(health check may need auth)"

echo ""
echo "=== Done! ==="
echo "Dashboard: https://rumyantsevdash.other-digital.ru"
echo "Login: admin / telethon2026"
