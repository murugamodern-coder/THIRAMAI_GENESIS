"""
Centralized secrets access with pluggable backends, TTL cache, and audit logging.

Backends:
- ``environment`` — ``os.environ`` (local / CI)
- ``aws`` — AWS Secrets Manager (optional boto3)
- ``vault`` — HashiCorp Vault KV v2 (optional hvac)
- ``gcp`` — Google Secret Manager (optional google-cloud-secret-manager)

Never log secret values. Use :func:`reset_secrets_manager` in tests.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Optional, Protocol

logger = logging.getLogger(__name__)


def _audit(action: str, secret_name: str, **kwargs: Any) -> None:
    logger.info(
        "secret_audit action=%s key=%s %s",
        action,
        secret_name,
        " ".join(f"{k}={v!s}" for k, v in sorted(kwargs.items()) if v is not None),
        extra={"secret_audit_action": action, "secret_key": secret_name, **kwargs},
    )


class SecretsBackend(Protocol):
    def get_secret(self, secret_name: str) -> Optional[str]:
        ...

    def set_secret(self, secret_name: str, secret_value: str) -> bool:
        ...

    def delete_secret(self, secret_name: str) -> bool:
        ...

    def list_secrets(self) -> list[str]:
        ...


_KNOWN_SECRET_KEYS = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "GROQ_API_KEY",
        "OPENAI_API_KEY",
        "TAVILY_API_KEY",
        "KITE_API_KEY",
        "KITE_API_SECRET",
        "KITE_ACCESS_TOKEN",
        "DATABASE_URL",
        "REDIS_URL",
        "SECRET_KEY",
        "JWT_SECRET_KEY",
        "JWT_SECRET",
        "FYERS_CLIENT_ID",
        "FYERS_SECRET_KEY",
        "FYERS_ACCESS_TOKEN",
    }
)


class EnvironmentBackend:
    """Read secrets from process environment (dev, Docker env, CI)."""

    def get_secret(self, secret_name: str) -> Optional[str]:
        value = os.getenv(secret_name)
        if value:
            _audit("get", secret_name, source="environment", cache_hit=False)
        return value

    def set_secret(self, secret_name: str, secret_value: str) -> bool:
        logger.warning("environment backend: set_secret not supported for %s", secret_name)
        _audit("set_denied", secret_name, source="environment")
        return False

    def delete_secret(self, secret_name: str) -> bool:
        _audit("delete_denied", secret_name, source="environment")
        return False

    def list_secrets(self) -> list[str]:
        return sorted(k for k in _KNOWN_SECRET_KEYS if os.getenv(k))


class AWSSecretsManagerBackend:
    """AWS Secrets Manager. Requires boto3."""

    def __init__(self, region: str | None = None) -> None:
        self.region = (region or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "ap-south-1").strip()
        self._client: Any = None

    @property
    def client(self) -> Any:
        if self._client is None:
            import boto3

            self._client = boto3.client("secretsmanager", region_name=self.region)
        return self._client

    def get_secret(self, secret_name: str) -> Optional[str]:
        try:
            resp = self.client.get_secret_value(SecretId=secret_name)
            raw = resp.get("SecretString")
            if raw is None:
                _audit("get_empty", secret_name, source="aws")
                return None
            try:
                blob = json.loads(raw)
                if isinstance(blob, dict):
                    val = blob.get("value", blob.get("secret"))
                    if val is not None:
                        _audit("get", secret_name, source="aws", format="json")
                        return str(val)
            except json.JSONDecodeError:
                pass
            _audit("get", secret_name, source="aws", format="string")
            return str(raw)
        except Exception as exc:
            from botocore.exceptions import ClientError

            if isinstance(exc, ClientError) and exc.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                logger.warning("AWS secret not found: %s", secret_name)
                _audit("get_missing", secret_name, source="aws")
                return None
            logger.error("AWS get_secret failed for %s: %s", secret_name, type(exc).__name__)
            _audit("get_error", secret_name, source="aws", error=type(exc).__name__)
            return None

    def set_secret(self, secret_name: str, secret_value: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.put_secret_value(SecretId=secret_name, SecretString=secret_value)
            _audit("set_update", secret_name, source="aws")
            return True
        except ClientError as err:
            code = err.response.get("Error", {}).get("Code")
            if code != "ResourceNotFoundException":
                logger.error("AWS set_secret put failed for %s: %s", secret_name, err)
                _audit("set_error", secret_name, source="aws", error=code or type(err).__name__)
                return False
        try:
            self.client.create_secret(Name=secret_name, SecretString=secret_value)
            _audit("set_create", secret_name, source="aws")
            return True
        except Exception as exc:
            logger.error("AWS set_secret create failed for %s: %s", secret_name, exc)
            _audit("set_error", secret_name, source="aws", error=type(exc).__name__)
            return False

    def delete_secret(self, secret_name: str) -> bool:
        try:
            self.client.delete_secret(SecretId=secret_name, RecoveryWindowInDays=7)
            _audit("delete", secret_name, source="aws", recovery_days=7)
            return True
        except Exception as exc:
            logger.error("AWS delete_secret failed for %s: %s", secret_name, exc)
            return False

    def list_secrets(self) -> list[str]:
        try:
            out: list[str] = []
            paginator = self.client.get_paginator("list_secrets")
            for page in paginator.paginate():
                for s in page.get("SecretList", []):
                    n = s.get("Name")
                    if n:
                        out.append(n)
            return out
        except Exception as exc:
            logger.error("AWS list_secrets failed: %s", exc)
            return []


class VaultBackend:
    """HashiCorp Vault KV v2 (mount ``secret`` by default). Requires hvac."""

    def __init__(
        self,
        *,
        url: str | None = None,
        token: str | None = None,
        mount_point: str | None = None,
    ) -> None:
        self.url = (url or os.getenv("VAULT_ADDR") or "").strip()
        self.token = (token or os.getenv("VAULT_TOKEN") or "").strip()
        self.mount_point = (mount_point or os.getenv("VAULT_KV_MOUNT") or "secret").strip()

    def _client(self) -> Any:
        import hvac

        if not self.url or not self.token:
            raise RuntimeError("VAULT_ADDR and VAULT_TOKEN are required for vault backend")
        c = hvac.Client(url=self.url, token=self.token)
        return c

    def get_secret(self, secret_name: str) -> Optional[str]:
        try:
            c = self._client()
            # secret_name is treated as path under mount, e.g. "thiramai/database_url"
            path = secret_name.strip("/")
            r = c.secrets.kv.v2.read_secret_version(path=path, mount_point=self.mount_point)
            data = (r or {}).get("data", {}).get("data", {})
            val = data.get("value") or data.get("secret")
            if val is not None:
                _audit("get", secret_name, source="vault")
                return str(val)
            _audit("get_empty", secret_name, source="vault")
            return None
        except Exception as exc:
            logger.error("Vault get_secret failed for %s: %s", secret_name, type(exc).__name__)
            _audit("get_error", secret_name, source="vault", error=type(exc).__name__)
            return None

    def set_secret(self, secret_name: str, secret_value: str) -> bool:
        try:
            c = self._client()
            path = secret_name.strip("/")
            c.secrets.kv.v2.create_or_update_secret(path=path, mount_point=self.mount_point, secret={"value": secret_value})
            _audit("set", secret_name, source="vault")
            return True
        except Exception as exc:
            logger.error("Vault set_secret failed for %s: %s", secret_name, exc)
            return False

    def delete_secret(self, secret_name: str) -> bool:
        try:
            c = self._client()
            path = secret_name.strip("/")
            c.secrets.kv.v2.delete_metadata_and_all_versions(path=path, mount_point=self.mount_point)
            _audit("delete", secret_name, source="vault")
            return True
        except Exception as exc:
            logger.error("Vault delete failed for %s: %s", secret_name, exc)
            return False

    def list_secrets(self) -> list[str]:
        return []


class GCPSecretManagerBackend:
    """GCP Secret Manager. Secret id = *secret_name*; project from env."""

    def __init__(self, project_id: str | None = None) -> None:
        self.project_id = (project_id or os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT") or "").strip()

    def get_secret(self, secret_name: str) -> Optional[str]:
        try:
            from google.cloud import secretmanager  # type: ignore

            if not self.project_id:
                logger.error("GCP secret backend: GOOGLE_CLOUD_PROJECT not set")
                return None
            client = secretmanager.SecretManagerServiceClient()
            name = f"projects/{self.project_id}/secrets/{secret_name}/versions/latest"
            resp = client.access_secret_version(name=name)
            raw = resp.payload.data.decode("utf-8")
            _audit("get", secret_name, source="gcp")
            return raw
        except Exception as exc:
            logger.error("GCP get_secret failed for %s: %s", secret_name, type(exc).__name__)
            _audit("get_error", secret_name, source="gcp", error=type(exc).__name__)
            return None

    def set_secret(self, secret_name: str, secret_value: str) -> bool:
        logger.warning("GCP set_secret not implemented in abstraction; use gcloud or console")
        return False

    def delete_secret(self, secret_name: str) -> bool:
        return False

    def list_secrets(self) -> list[str]:
        return []


def _detect_backend() -> SecretsBackend:
    raw = (
        (os.getenv("THIRAMAI_SECRETS_BACKEND") or os.getenv("SECRETS_BACKEND") or "environment")
        .strip()
        .lower()
    )
    if raw == "aws":
        logger.info("secrets backend=aws region=%s", os.getenv("AWS_REGION", "ap-south-1"))
        return AWSSecretsManagerBackend()
    if raw in ("vault", "hashicorp"):
        return VaultBackend()
    if raw in ("gcp", "google"):
        return GCPSecretManagerBackend()
    logger.info("secrets backend=environment")
    return EnvironmentBackend()


class SecretsManager:
    """Resolve secrets via backend with in-process TTL cache (no values in logs)."""

    def __init__(self, backend: SecretsBackend | None = None, *, cache_ttl_seconds: float = 300.0) -> None:
        self.backend = backend or _detect_backend()
        self._cache_ttl_seconds = max(0.0, float(cache_ttl_seconds))
        self._cache: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def get(self, secret_name: str, *, use_cache: bool = True) -> Optional[str]:
        now = time.monotonic()
        with self._lock:
            if use_cache and self._cache_ttl_seconds > 0 and secret_name in self._cache:
                val, exp = self._cache[secret_name]
                if now < exp:
                    _audit("get", secret_name, source="cache", cache_hit=True)
                    return val
                del self._cache[secret_name]

        value = self.backend.get_secret(secret_name)

        if value and use_cache and self._cache_ttl_seconds > 0:
            with self._lock:
                self._cache[secret_name] = (value, now + self._cache_ttl_seconds)
        return value

    def set(self, secret_name: str, secret_value: str) -> bool:
        ok = self.backend.set_secret(secret_name, secret_value)
        if ok:
            with self._lock:
                self._cache.pop(secret_name, None)
            _audit("set_ok", secret_name, source="backend")
        return ok

    def delete(self, secret_name: str) -> bool:
        ok = self.backend.delete_secret(secret_name)
        if ok:
            with self._lock:
                self._cache.pop(secret_name, None)
        return ok

    def rotate(
        self, secret_name: str, new_value: str, *, grace_period_seconds: int = 0
    ) -> bool:
        """
        Store *new_value* and clear cache. Optional blocking grace (prefer doing that in a job, not request path).
        """
        logger.info("secret rotation requested key=%s", secret_name)
        if not self.set(secret_name, new_value):
            return False
        if grace_period_seconds > 0:
            logger.info("secret rotation grace sleep key=%s seconds=%s", secret_name, grace_period_seconds)
            time.sleep(float(grace_period_seconds))
        self.clear_cache()
        logger.info("secret rotation complete key=%s", secret_name)
        return True

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()
        _audit("cache_clear", "__all__", source="manager")


_singleton: SecretsManager | None = None
_singleton_lock = threading.Lock()


def get_secrets_manager() -> SecretsManager:
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = SecretsManager()
    return _singleton


def reset_secrets_manager() -> None:
    global _singleton
    with _singleton_lock:
        _singleton = None


def get_secret(secret_name: str, *, use_cache: bool = True) -> Optional[str]:
    return get_secrets_manager().get(secret_name, use_cache=use_cache)


__all__ = [
    "AWSSecretsManagerBackend",
    "EnvironmentBackend",
    "GCPSecretManagerBackend",
    "SecretsBackend",
    "SecretsManager",
    "VaultBackend",
    "get_secret",
    "get_secrets_manager",
    "reset_secrets_manager",
]
