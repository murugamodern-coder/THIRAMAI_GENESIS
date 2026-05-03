#!/bin/bash
set -euo pipefail

echo "================================"
echo "Quick Restart - Reload Environment"
echo "================================"
echo ""

COMPOSE_CMD="docker compose -f docker-compose.production.yml --env-file .env.production"

# Stop
echo "Stopping services..."
$COMPOSE_CMD down

# Start
echo ""
echo "Starting with new environment..."
$COMPOSE_CMD up -d

# Wait
echo ""
echo "Waiting 30 seconds for health..."
sleep 30

# Check
echo ""
echo "Checking health..."

if curl -f -s http://localhost:8000/health/live > /dev/null; then
    echo "✅ /health/live OK"
else
    echo "❌ /health/live FAILED"
fi

if curl -f -s http://localhost:8000/health/ready > /dev/null; then
    echo "✅ /health/ready OK"
else
    echo "⚠️  /health/ready non-200 (checking details...)"
    curl -s http://localhost:8000/health/ready | python -m json.tool || echo "Could not parse response"
fi

echo ""
echo "Done!"
