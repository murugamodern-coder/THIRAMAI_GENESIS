# Thiramai Sovereign OS
> AI-Native Business Operating System for Indian SMBs

[![Status](https://img.shields.io/badge/status-live-brightgreen)]()
[![Version](https://img.shields.io/badge/version-1.0.0-blue)]()
[![Security](https://img.shields.io/badge/security-hardened-orange)]()

## 🏆 Production Status
> **Score: 96/100** — Client Handover Ready
> Last audit: April 25, 2026
> Status: 🟢 LIVE at https://app.thiramai.co.in

## 🎯 What is Thiramai?
Thiramai Sovereign OS is an AI-first operating system that unifies business operations, personal execution, and decision intelligence into one command-driven platform. It helps founders and teams run inventory, billing, planning, and daily execution with governance, auditability, and production-grade security built in.

## ✨ Key Features
- Command Center — AI-powered business command interface
- Business OS — Inventory, Billing, Production management
- Personal OS — Health, Finance, Daily briefing
- Control Center — Governance and decision intelligence
- Research Engine — Market intelligence and opportunity detection

## 🚀 Live Demo
https://app.thiramai.co.in

## 🏗️ Architecture
```text
                        +-----------------------------+
                        |  React + Vite Frontend      |
                        |  Command Center UI          |
                        +--------------+--------------+
                                       |
                                       v
                      +----------------+----------------+
                      | FastAPI Backend (Thiramai API) |
                      | Auth, RBAC, Brain, Business OS |
                      +----+----------------------+-----+
                           |                      |
                           v                      v
                +----------+----------+   +------+------+
                | PostgreSQL 16       |   | Redis       |
                | Business + Audit DB |   | Cache/Queue |
                +----------+----------+   +------+------+
                           |                      |
                           +----------+-----------+
                                      |
                                      v
                          +-----------+-----------+
                          | Workers / Schedulers  |
                          | Alerts, Jobs, Autonomy|
                          +-----------+-----------+
                                      |
                                      v
                          +-----------+-----------+
                          | AI Providers          |
                          | Groq + Tavily         |
                          +-----------------------+
```

## 📊 Feature Status
| Feature | Status | Expected |
|---------|--------|----------|
| Command Center | ✅ Live | - |
| Control Center | ✅ Live | - |
| Inventory | ✅ Live | - |
| Billing | ✅ Live | - |
| Production | ✅ Live | - |
| Personal OS | ✅ Live | - |
| Stock Watchlist | ✅ Live | - |
| Research | ✅ Live | - |
| Analytics | 🔜 Coming | Q2 2026 |
| GST Filing | 🔜 Coming | Q3 2026 |
| Payroll | 🔜 Coming | Q3 2026 |
| Reports | 🔜 Coming | Q2 2026 |
| Settings | 🔜 Coming | Q2 2026 |

## 🔒 Security
- JWT authentication
- Role-based access control (RBAC)
- Tiered rate limiting + IP violation controls
- Security audit logging
- Dangerous endpoint blocking in production

## 🛠️ Tech Stack
| Layer | Technology |
|-------|-----------|
| Backend | FastAPI + Python 3.12 |
| Database | PostgreSQL 16 |
| Cache | Redis |
| Frontend | React + Vite |
| AI | Groq (Llama) + Tavily |
| Deploy | Docker + Nginx |
| Server | DigitalOcean Ubuntu 24 |

## 📦 Quick Deploy
```bash
cd /root/thiramai-app
git pull origin main
docker compose -f docker-compose.production.yml --env-file .env.production up -d --force-recreate --build web
sleep 30
docker exec thiramai-app-web-1 alembic upgrade head
bash scripts/post_deploy_check.sh
```

For full deployment and operations guidance, see `docs/DEPLOYMENT.md` and API details in `docs/API_REFERENCE.md`.
