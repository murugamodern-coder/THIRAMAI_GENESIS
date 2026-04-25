"""
Defense-in-depth HTTP headers (XSS / clickjacking / MIME sniffing) and optional Origin checks (CSRF-style).

JWT in ``Authorization`` is not vulnerable to classic cookie CSRF; Origin validation adds a belt
for browser-based clients mixing cookies or future session auth. CLI / mobile without ``Origin``
are allowed through.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Iterable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


def _truthy(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in ("1", "true", "yes", "on")


def _cors_origins() -> set[str]:
    raw = (os.getenv("THIRAMAI_CORS_ORIGINS") or "").strip()
    if not raw:
        return {
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        }
    return {o.strip().rstrip("/") for o in raw.split(",") if o.strip() and o.strip() != "*"}


def _has_bearer(request: Request) -> bool:
    auth = (request.headers.get("authorization") or "").strip()
    return auth.lower().startswith("bearer ")


def _path_exempt_origin(path: str) -> bool:
    p = path.rstrip("/") or "/"
    if p in ("/", "/docs", "/openapi.json", "/redoc"):
        return True
    if p.startswith("/docs") or p.startswith("/redoc"):
        return True
    if p.startswith("/static/"):
        return True
    return False


def _origin_or_referer_allowed(request: Request, allowed: Iterable[str]) -> bool:
    origin = (request.headers.get("origin") or "").strip().rstrip("/")
    if origin:
        return origin in {a.rstrip("/") for a in allowed}
    ref = (request.headers.get("referer") or "").strip()
    if not ref:
        return True
    for a in allowed:
        base = a.rstrip("/")
        if ref.startswith(base + "/") or ref.rstrip("/") == base:
            return True
    return False


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    - API JSON responses: tight CSP (no inline assets from API).
    - Dashboard / script: relaxed ``script-src`` for bundled dashboard.
    - Standard browser hardening headers.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        path = request.url.path or ""

        p = path.rstrip("/") or "/"
        if (
            p.endswith("/dashboard")
            or path.endswith("/script.js")
            or p == "/dashboard"
            or path.startswith("/dashboard/live")
            or p == "/"
            or path.startswith("/static/")
            or path.startswith("/public/")
        ):
            csp = (
                "default-src 'self'; "
                "script-src 'self' https://cdn.tailwindcss.com; "
                "style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; "
                "font-src 'self' https://fonts.gstatic.com data:; "
                "img-src 'self' data:; "
                "connect-src 'self'; "
                "frame-ancestors 'none'; "
                "base-uri 'self'; "
                "object-src 'none'; "
                "form-action 'self'"
            )
        else:
            csp = (
                "default-src 'none'; "
                "frame-ancestors 'none'; "
                "base-uri 'none'; "
                "form-action 'none'; "
                "object-src 'none'"
            )

        response.headers.setdefault("Content-Security-Policy", csp)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Embedder-Policy", "require-corp")
        response.headers.setdefault("X-XSS-Protection", "0")

        # Production: drop framework / dev leakage headers (defense in depth behind reverse proxies).
        env = (os.getenv("THIRAMAI_ENV") or os.getenv("ENV") or "").strip().lower()
        if env in ("production", "prod", "staging"):
            for h in ("server", "x-powered-by", "x-aspnet-version", "x-aspnetmvc-version"):
                if h in response.headers:
                    del response.headers[h]

        return response


class CsrfOriginMiddleware(BaseHTTPMiddleware):
    """
    When ``THIRAMAI_STRICT_ORIGIN=1``, state-changing requests from browsers must send an
    ``Origin`` or ``Referer`` that matches ``THIRAMAI_CORS_ORIGINS``, unless ``Authorization: Bearer`` is present.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not _truthy("THIRAMAI_STRICT_ORIGIN"):
            return await call_next(request)
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return await call_next(request)
        path = request.url.path or ""
        if _path_exempt_origin(path):
            return await call_next(request)
        if _has_bearer(request):
            return await call_next(request)
        allowed = _cors_origins()
        origin = (request.headers.get("origin") or "").strip()
        if not origin and not (request.headers.get("referer") or "").strip():
            return await call_next(request)
        if not _origin_or_referer_allowed(request, allowed):
            from starlette.responses import JSONResponse

            return JSONResponse(
                status_code=403,
                content={"detail": "Origin not allowed for this request."},
            )
        return await call_next(request)
