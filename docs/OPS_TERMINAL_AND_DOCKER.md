# Terminal safety, Docker, and stack verification

## Why the terminal “freezes”

- **TTY allocation**: `docker compose exec web …` without `-T` allocates a pseudo-TTY. In some SSH or IDE terminals this blocks or waits for input. **Always use `-T`** for non-interactive commands (Alembic, one-off scripts).
- **Pasting multiple commands**: Pasting several lines at once can start long-running processes, leave half a pipeline running, or confuse the shell. **Run one command, wait for the prompt, then run the next.**
- **Typos**: The Compose service name is **`web`**, not `wed`. Wrong service names fail or hang while Compose resolves names.

## Safe execution rules

1. **One command per paste** — no `&&` / `;` chains unless you know the shell and both commands are instant.
2. **Non-interactive exec** — append **`-T`** after `exec`:
   - `docker compose -f docker-compose.production.yml --env-file .env.production exec -T web alembic current`
3. **Timeout (Linux)** — wrap slow execs:
   - `timeout 120 docker compose -f docker-compose.production.yml --env-file .env.production exec -T web alembic current`
4. **If `exec` still hangs** — open another session and run:
   - `docker compose -f docker-compose.production.yml --env-file .env.production logs web --tail 200`
   - Avoid repeated blocking `exec` until logs show the container is healthy.

## Recovery if the terminal stops responding

1. **Send interrupt**: Ctrl+C (Windows / most SSH clients). Equivalent to SIGINT on the foreground process.
2. **Still stuck**: Close the terminal tab or type `exit` and open a **new** SSH or PowerShell session.
3. **IDE integrated terminal**: Use the trash/kill-terminal control, then open a fresh terminal so input is not stuck behind a background job.

## Validate services (production compose)

Run **each** line separately from the project root (after `cp .env.production.example .env.production` and filling secrets):

```text
docker compose -f docker-compose.production.yml --env-file .env.production ps
```

Expected: **`web`**, **`db`**, and **`redis`** running (and healthy per Compose).

If any are missing or exited:

```text
docker compose -f docker-compose.production.yml --env-file .env.production up -d
```

(Rebuild when code changed: add `--build`.)

## Migration state

```text
docker compose -f docker-compose.production.yml --env-file .env.production exec -T web alembic current
```

- **No output / error**: Check `logs web`. Confirm the `web` container is up and `DATABASE_URL` is correct. If DB is already at head, `alembic current` should print one revision id (must match `EXPECTED_ALEMBIC_REVISION` in `core/migration_head.py` after upgrades).

Apply migrations inside the container when needed:

```text
docker compose -f docker-compose.production.yml --env-file .env.production exec -T web alembic upgrade head
```

## Backend readiness

```text
curl -sS -o NUL -w "%{http_code}" http://127.0.0.1:8000/health/ready
```

(PowerShell: `Invoke-WebRequest -Uri http://127.0.0.1:8000/health/ready -UseBasicParsing -TimeoutSec 15`)

**HTTP 200** means ready. **503** with JSON explains which check failed (DB, Alembic revision mismatch, Redis, workers).

## Automated checks

- **Windows**: `powershell -ExecutionPolicy Bypass -File scripts/verify_stack.ps1`
- **Linux / Git Bash**: `bash scripts/verify_stack.sh` (uses `timeout` when available for `alembic current`)
