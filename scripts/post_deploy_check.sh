#!/bin/bash
# Run after every deployment to verify system health

echo "=== POST DEPLOY CHECKLIST ==="

# 1. Health check
echo -n "1. Health: "
curl -s https://app.thiramai.co.in/health/live | grep -q "alive" && echo "✅" || echo "❌"

# 2. Migration check
echo -n "2. Migrations: "
curl -s https://app.thiramai.co.in/health/ready | python3 -c "
import sys,json
d=json.load(sys.stdin)
ok = d.get('alembic',{}).get('ok',False)
print('✅' if ok else '❌ ' + str(d.get('alembic',{})))
"

# 3. Containers check
echo "3. Containers:"
docker ps --format "   {{.Names}}: {{.Status}}" | grep thiramai

# 4. Disk space
echo -n "4. Disk: "
df -h / | tail -1 | awk '{print $5 " used (" $4 " free)"}'

# 5. Memory
echo -n "5. Memory: "
free -h | grep Mem | awk '{print $3 "/" $2 " used"}'

echo "=== CHECKLIST DONE ==="
