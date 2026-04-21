# Let's Encrypt (Certbot) for `app.thiramai.co.in`

## 1. DNS

Point an **A (or AAAA) record** for `app.thiramai.co.in` to this server’s public IP before running certbot.

## 2. Install certbot (Debian / Ubuntu)

```bash
sudo apt update
sudo apt install -y certbot python3-certbot-nginx
```

## 3. Webroot (first-time, Nginx already serving port 80)

The site config in `deploy/nginx/sites-available/app.thiramai.co.in.conf` includes:

```nginx
location /.well-known/acme-challenge/ { root /var/www/certbot; }
```

```bash
sudo mkdir -p /var/www/certbot
```

**Option A — certbot nginx plugin (simplest if a default server is up):**

```bash
sudo certbot --nginx -d app.thiramai.co.in
```

**Option B — standalone (stop Nginx briefly):**

```bash
sudo systemctl stop nginx
sudo certbot certonly --standalone -d app.thiramai.co.in
sudo systemctl start nginx
```

## 4. Align Nginx TLS paths

Ensure your `sites-available/app.thiramai.co.in.conf` ssl_certificate paths match:

`/etc/letsencrypt/live/app.thiramai.co.in/fullchain.pem`  
`/etc/letsencrypt/live/app.thiramai.co.in/privkey.pem`

Certbot typically drops `options-ssl-nginx.conf` and `ssl-dhparams.pem` — if missing:

```bash
sudo openssl dhparam -out /etc/letsencrypt/ssl-dhparams.pem 2048
```

## 5. Auto-renewal

Certbot installs a **systemd timer** on most distributions:

```bash
systemctl list-timers | grep certbot
sudo certbot renew --dry-run
```

Renewal reloads hooks: add post-hook if needed:

```bash
sudo mkdir -p /etc/letsencrypt/renewal-hooks/deploy
sudo tee /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh >/dev/null <<'EOF'
#!/bin/sh
systemctl reload nginx
EOF
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
```

HTTP → HTTPS is handled by the `deploy/nginx` server block on port 80.
