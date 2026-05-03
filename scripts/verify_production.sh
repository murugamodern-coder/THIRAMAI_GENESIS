#!/bin/bash
set -euo pipefail

echo "╔════════════════════════════════════════════════╗"
echo "║  PRODUCTION MODE VERIFICATION                  ║"
echo "╚════════════════════════════════════════════════╝"
echo ""

# Check environment
echo "1. Checking environment configuration..."
if grep -q "THIRAMAI_SKIP_ALEMBIC_CHECK=0" .env.production && \
   grep -q "THIRAMAI_HEALTH_IGNORE_ALEMBIC_MISMATCH=1" .env.production; then
    echo "   ✅ Clean production mode"
else
    echo "   ❌ Still using workarounds"
fi

# Check health
echo ""
echo "2. Checking /health/live..."
if curl -f -s http://localhost:8000/health/live | grep -q "alive"; then
    echo "   ✅ Service alive"
else
    echo "   ❌ Service not alive"
fi

echo ""
echo "3. Checking /health/ready..."
if curl -f -s http://localhost:8000/health/ready | grep -q "ready"; then
    echo "   ✅ Service ready"
else
    echo "   ❌ Service not ready"
fi

echo ""
echo "✅ Verification complete"
