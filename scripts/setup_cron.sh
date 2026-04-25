#!/bin/bash
# Setup automated backup and monitoring

mkdir -p /root/backups
mkdir -p /root/logs

# Add crontab entries
(crontab -l 2>/dev/null; echo "# Thiramai automated tasks") | crontab -
(crontab -l 2>/dev/null; echo "0 2 * * * docker exec thiramai-app-db-1 pg_dump -U thiramai thiramai > /root/backups/thiramai_\$(date +\%Y\%m\%d).sql") | crontab -
(crontab -l 2>/dev/null; echo "0 * * * * docker logs thiramai-app-web-1 --since 1h 2>&1 | grep ERROR >> /root/logs/errors_\$(date +\%Y\%m\%d).log") | crontab -
(crontab -l 2>/dev/null; echo "*/5 * * * * curl -s https://app.thiramai.co.in/health/live | grep -q alive || echo 'ALERT: Thiramai down!' >> /root/logs/alerts.log") | crontab -

echo "✅ Cron jobs setup complete"
crontab -l
