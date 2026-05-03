# Secrets management

## Overview

Thiramai resolves sensitive configuration through `core.secrets_manager`, which supports multiple backends and TTL caching. Values are never written to application logs; audit lines record **key names** and **actions** only.

## Backends

| `SECRETS_BACKEND` / `THIRAMAI_SECRETS_BACKEND` | Behavior |
| --- | --- |
| `environment` (default) | Read from process environment (`.env` / Docker / k8s env). |
| `aws` | AWS Secrets Manager (`boto3`). Set `AWS_REGION`. |
| `vault` | HashiCorp Vault KV v2. Set `VAULT_ADDR`, `VAULT_TOKEN`, optional `VAULT_KV_MOUNT`. Requires `hvac`. |
| `gcp` / `google` | Google Secret Manager. Set `GOOGLE_CLOUD_PROJECT`. Requires `google-cloud-secret-manager`. |

### Local development

```bash
# .env
DATABASE_URL=postgresql://...
SECRET_KEY=...
```

### Production (AWS)

```bash
export SECRETS_BACKEND=aws
export AWS_REGION=ap-south-1
```

Store secrets under the same logical names as env vars (for example `DATABASE_URL`, `SECRET_KEY`).

## Settings integration

- `ThiramaiSettings.get_secret_or_env(key)` — secrets manager first, then `os.environ`.
- `ThiramaiSettings.get_database_url_secure()` — `DATABASE_URL` via the above.
- `core.database.get_database_url()` uses `get_secret_or_env("DATABASE_URL")` when settings load succeeds.

## Rotation

### CLI

```bash
# One key
python scripts/rotate_secrets.py --secret SECRET_KEY

# Auto-rotatable set (see script for list)
python scripts/rotate_secrets.py --all

# Preview
python scripts/rotate_secrets.py --all --dry-run

# Optional blocking grace (run from automation only)
python scripts/rotate_secrets.py --secret SECRET_KEY --grace-seconds 60
```

Provider-issued or infrastructure secrets (broker keys, `DATABASE_URL`, third-party API keys) should be rotated in the provider console or via dedicated runbooks — they are not in the default `--all` list.

### GitHub Actions

Workflow: `.github/workflows/rotate-secrets.yml`.

- **Scheduled** (1st of month): **always** `--dry-run` (no writes).
- **Manual** `workflow_dispatch`: enable **live_rotation** only when you intend to write to the configured backend (requires AWS credentials in repo/org secrets for the `aws` backend).

## Adding a new secret

1. Store the value in your backend (or `.env` for dev).
2. Read it in code:

```python
from core.secrets_manager import get_secret

api_key = get_secret("MY_NEW_SECRET")
```

3. Add the logical name to `_KNOWN_SECRET_KEYS` in `core/secrets_manager.py` if it should appear in `EnvironmentBackend.list_secrets()` (dev inventory only).

## Security practices

- Do not commit secrets; rely on `.gitignore` for `.env`.
- Use separate secret names / projects for staging and production.
- For AWS, enable CloudTrail / data events appropriate to your org for API auditing.
- Prefer short TTL caches in high-churn environments (`SecretsManager(..., cache_ttl_seconds=...)` if you construct a custom instance).
