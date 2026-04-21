## Assets
- Customer business data (inventory, billing, production data)
- JWT tokens and session credentials
- API keys (GROQ, TAVILY)
- Database credentials

## Threat Actors
- External attackers (web)
- Malicious tenants (cross-tenant)
- Compromised dependencies (supply chain)
- Insider threats

## Attack Vectors & Mitigations
| Vector | Risk | Mitigation | Status |
|--------|------|-----------|--------|
| XSS + localStorage JWT theft | High | Move to HttpOnly cookies | TODO |
| Cross-tenant IDOR | High | RLS + app-layer filters | In Progress |
| SQL Injection | Medium | SQLAlchemy ORM + Pydantic | Done |
| Supply chain attack | Medium | pip-audit + SBOM | Done |
| Rate limit bypass | Medium | Trusted proxy validation | Done |
| Secrets in logs | Medium | Log redaction policy | TODO |
