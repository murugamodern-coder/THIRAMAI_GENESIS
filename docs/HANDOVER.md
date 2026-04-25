# Thiramai Sovereign OS — Client Handover Document
Version: 1.0.0
Date: April 2026
Prepared by: Thiramai Engineering Team

## 1. SYSTEM OVERVIEW

### What is Thiramai?
Thiramai Sovereign OS is an AI-native business operating system
designed for Indian SMBs. It unifies command intelligence,
business operations, and personal productivity in one platform.

### Live URL
https://app.thiramai.co.in

### Architecture

```text
[Browser] -> [Nginx] -> [FastAPI] -> [PostgreSQL]
                              |
                              v
                           [Redis]
                              |
                              v
                    [Groq AI / Tavily]
```

### Tech Stack
| Layer | Technology | Version |
|-------|-----------|---------|
| Backend | FastAPI | 0.115+ |
| Language | Python | 3.12 |
| Database | PostgreSQL | 16 |
| Cache | Redis | 7 |
| Frontend | React + Vite | 18/5 |
| AI | Groq (Llama) | Latest |
| Research | Tavily | Latest |
| Deploy | Docker + Nginx | Latest |
| Server | DigitalOcean | Ubuntu 24 |

## 2. WORKING FEATURES (Demo Ready)

### Command Center
- AI-powered command interface
- Natural language business queries
- System status monitoring
- Real-time intelligence

### Business OS
- Inventory management (CRUD)
- Billing and invoicing
- Production tracking
- Supplier management
- Purchase orders
- Expense tracking

### Personal OS
- Daily briefing (AI-powered)
- Health tracking
- Finance management
- Meeting management
- Habit tracking

### Control Center
- Governance and guardrails
- Decision intelligence
- Automation rules
- Opportunity detection

### Research Engine
- Market research
- Competitor analysis
- Research projects

### Stock Watchlist
- Real-time stock prices
- Portfolio tracking
- Price alerts

## 3. COMING SOON FEATURES

| Feature | Expected | Status |
|---------|----------|--------|
| Analytics Dashboard | Q2 2026 | 🔜 |
| GST Filing | Q3 2026 | 🔜 |
| Payroll Management | Q3 2026 | 🔜 |
| Reports Suite | Q2 2026 | 🔜 |
| Settings Panel | Q2 2026 | 🔜 |
| Purchase Orders | Q2 2026 | 🔜 |

## 4. CREDENTIALS & ACCESS

### Admin Login
- URL: https://app.thiramai.co.in
- Email: admin@thiramai.local
- Role: Owner (full access)

### Server Access
- Provider: DigitalOcean
- IP: 139.59.24.80
- Region: Bangalore (BLR1)
- OS: Ubuntu 24.04 LTS
- RAM: 4GB | CPU: 2 vCPU | Disk: 35GB

### Required API Keys (in .env.production)
| Key | Purpose | Required |
|-----|---------|---------|
| GROQ_API_KEY | AI responses | Yes |
| TAVILY_API_KEY | Research | Yes |
| JWT_SECRET_KEY | Auth security | Yes |
| DATABASE_URL | PostgreSQL | Yes |
| REDIS_URL | Cache | Yes |

## 5. DEPLOYMENT GUIDE

### Standard Deploy
```bash
cd /root/thiramai-app
git pull origin main
docker compose -f docker-compose.production.yml \
  --env-file .env.production \
  up -d --force-recreate --build web
sleep 30
docker exec thiramai-app-web-1 alembic upgrade head
bash scripts/post_deploy_check.sh
```

### Health Check
```bash
curl https://app.thiramai.co.in/health/live
# Expected: {"status":"alive","service":"thiramai-genesis"}
```

### View Logs
```bash
docker logs thiramai-app-web-1 --tail 50
docker logs thiramai-app-worker-jobs-1 --tail 20
```

## 6. DATABASE BACKUP

### Manual Backup
```bash
docker exec thiramai-app-db-1 \
  pg_dump -U thiramai thiramai > \
  /root/backups/thiramai_$(date +%Y%m%d).sql
```

### Restore
```bash
docker exec -i thiramai-app-db-1 \
  psql -U thiramai thiramai < backup.sql
```

## 7. MONITORING

### System Status
```bash
bash scripts/post_deploy_check.sh
```

### Container Status
```bash
docker ps --format "{{.Names}}: {{.Status}}"
```

### Resource Usage
```bash
free -h && df -h /
```

## 8. SECURITY

### Security Features
- JWT authentication with secure cookies
- Role-based access control (RBAC)
- Rate limiting per endpoint type
- Dangerous endpoint blocking in production
- Security audit logging
- CORS locked to production domain
- CSP headers enabled

### Rate Limits
| Endpoint Type | Limit |
|--------------|-------|
| Authentication | 5/minute |
| AI Chat | 20/minute |
| Research | 10/minute |
| Autonomy | 3/minute |
| CRUD operations | 60/minute |

## 9. KNOWN LIMITATIONS

1. Stock data is demo-grade (yfinance) — not broker-grade
2. AI responses require GROQ_API_KEY to be configured
3. Research requires TAVILY_API_KEY
4. GST/Payroll/Analytics are Coming Soon
5. Email/WhatsApp notifications not yet configured
6. Weather widget requires API key configuration

## 10. SUPPORT & ESCALATION

### Emergency Restart
```bash
docker compose -f docker-compose.production.yml \
  --env-file .env.production restart web
```

### Full System Restart
```bash
docker compose -f docker-compose.production.yml \
  --env-file .env.production down
docker compose -f docker-compose.production.yml \
  --env-file .env.production up -d
```
