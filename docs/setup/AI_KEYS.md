# AI API Keys Setup

The Thiramai platform uses AI services for decision-making and research. Configure API keys from the providers below.

## Required Services

### 1. GROQ (LLM Inference)

**What it's for:** Fast AI model inference for decision-making and chat brain paths.

**Get your key:**

1. Visit: https://console.groq.com/
2. Sign up / log in
3. Open the API Keys section
4. Create a new key
5. Copy the key into `.env.production`

**Add to `.env.production`:**

```bash
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxx
```

### 2. Tavily (Web Search)

**What it's for:** Web search and research context where the brain stack uses Tavily.

**Get your key:**

1. Visit: https://tavily.com/
2. Sign up / log in
3. Open the API / dashboard section
4. Copy your API key

**Add to `.env.production`:**

```bash
TAVILY_API_KEY=tvly-xxxxxxxxxxxxxxxxxxxxx
```

## Optional Services

### 3. OpenAI (Alternative LLM)

**What it's for:** Optional integrations that call OpenAI models (when enabled in code).

**Get your key:**

1. Visit: https://platform.openai.com/
2. Create an account / log in
3. Open API Keys
4. Create a new secret key

**Add to `.env.production`:**

```bash
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxx
```

Also ensure `docker-compose.production.yml` passes `OPENAI_API_KEY` into the `web` service (this repo does).

## Testing Without Real Keys

You can set non-empty placeholder strings so processes that only check “key present” proceed. **Provider calls will fail** until you replace them with valid keys:

```bash
GROQ_API_KEY=placeholder_groq_key
TAVILY_API_KEY=placeholder_tavily_key
```

For full `/chat/decision` and `/chat` behavior, use **real** keys.

## After Adding Keys

```powershell
# Reload env into the web container (restart alone may not refresh env)
docker compose -f docker-compose.production.yml --env-file .env.production up -d --force-recreate web

Start-Sleep -Seconds 15

# Health: AI block should show keys configured
Invoke-RestMethod http://localhost:8000/health/ready

# Decision API smoke test
.\scripts\test_decision_api.ps1
```

## Troubleshooting

### "Authentication required or credentials invalid"

- Confirm JWT: log in again and pass `Authorization: Bearer <token>`.

### "An internal error occurred" / generic 5xx

- With `THIRAMAI_SAFE_ERRORS=1`, details are masked; check logs: `docker compose -f docker-compose.production.yml logs web`
- Confirm keys are non-empty in the container: `docker compose ... exec web printenv GROQ_API_KEY` (avoid printing real keys in shared logs)
- If logs show `relation "ai_decisions" does not exist` (or similar), the database schema is behind the app: run Alembic migrations on that database (`alembic upgrade head` in your deploy process), not an AI key issue.

### 401 / 403 from AI provider

- Key invalid, revoked, or wrong project — regenerate at the provider.

### 503 "Missing GROQ_API_KEY or TAVILY_API_KEY"

- Variables missing in `.env.production` or not passed under `web.environment` in Compose — see [README](../../README.md) and `docker-compose.production.yml`.

## Security Notes

- Do not commit real `.env.production` files
- Prefer secrets manager / CI-injected env in production
- Rotate keys if exposed
- Monitor usage and billing on provider dashboards
