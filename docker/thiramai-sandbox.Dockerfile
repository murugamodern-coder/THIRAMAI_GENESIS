# Minimal Python runtime for THIRAMAI self-heal / compile checks (isolated from host).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /workspace

# Optional: match host tooling if you later run pytest in sandbox (uncomment).
# RUN pip install --no-cache-dir -q pytest

CMD ["python", "--version"]
