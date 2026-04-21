# WebSocket proxy checklist (`/ai/logs/ws/...`)

For autonomous goal log streaming, Nginx must:

1. **`http` context:** define `map $http_upgrade $connection_upgrade` (see `deploy/nginx/nginx-http-map-websocket.conf`).
2. **`location ^~ /ai`:**  
   - `proxy_http_version 1.1;`  
   - `proxy_set_header Upgrade $http_upgrade;`  
   - `proxy_set_header Connection $connection_upgrade;`  
   (included from `sites-available/app.thiramai.co.in.conf` after `proxy-thiramai-api.conf`).
3. **Timeouts:** long `proxy_read_timeout` for idle WS (set in `snippets/proxy-thiramai-api.conf`).
4. **Rate limit:** `limit_req` on `/ai` applies to the **upgrade request** as well; keep **`burst`** high enough that a single browser session is not cut off (current site config sets burst on `/ai`).

Verify with:

```bash
curl -i -N \
  -H "Connection: Upgrade" -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: $(openssl rand -base64 16)" \
  "https://app.thiramai.co.in/ai/logs/ws/<job_id>?token=<JWT>"
```

Expect **101 Switching Protocols** when token and job are valid.
