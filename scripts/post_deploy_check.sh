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

def find_alembic_obj(node):
    if isinstance(node, dict):
        if 'alembic' in node and isinstance(node['alembic'], dict):
            return node['alembic']
        for value in node.values():
            found = find_alembic_obj(value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = find_alembic_obj(item)
            if found is not None:
                return found
    return None

alembic = find_alembic_obj(d) or {}
ok = alembic.get('ok')
if ok is None:
    ok = d.get('ok')
if ok is None:
    for key in ('migration_ok', 'migrations_ok', 'alembic_ok'):
        if key in d:
            ok = d.get(key)
            break
if ok is None:
    ok = False

if ok:
    print('✅')
else:
    detail = alembic if alembic else {'health_ready_keys': list(d.keys())[:8]}
    print('❌ ' + str(detail))
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
