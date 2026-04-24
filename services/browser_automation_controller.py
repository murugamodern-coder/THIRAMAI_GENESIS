"""Playwright-backed browser automation (optional dependency)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

try:
    from playwright.sync_api import Browser, Page, Playwright, sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None  # type: ignore[misc, assignment]
    Playwright = object  # type: ignore[misc, assignment]
    Browser = object  # type: ignore[misc, assignment]
    Page = object  # type: ignore[misc, assignment]


@dataclass
class BrowserAutomationController:
    """
    Short-lived browser session for one action run.

    Uses ``headless=True`` by default; set ``THIRAMAI_PLAYWRIGHT_HEADFUL=1`` for debugging.
    """

    headless: bool = field(default_factory=lambda: os.getenv("THIRAMAI_PLAYWRIGHT_HEADFUL", "").strip() != "1")
    _pw: Playwright | None = None
    _browser: Browser | None = None
    _page: Page | None = None

    def __enter__(self) -> BrowserAutomationController:
        if sync_playwright is None:
            return self
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self._page = self._browser.new_page()
        return self

    def __exit__(self, *args: Any) -> None:
        try:
            if self._page:
                self._page.close()
        finally:
            self._page = None
        try:
            if self._browser:
                self._browser.close()
        finally:
            self._browser = None
        try:
            if self._pw:
                self._pw.stop()
        finally:
            self._pw = None

    def available(self) -> bool:
        return sync_playwright is not None

    def reload_page(self, *, wait_until: str = "domcontentloaded", timeout_ms: int = 45_000) -> dict[str, Any]:
        if not self._page:
            return {"ok": False, "error": "browser session not active"}
        self._page.reload(wait_until=wait_until, timeout=int(timeout_ms))  # type: ignore[arg-type]
        return {"ok": True, "reloaded": True}

    def open_url(self, url: str, *, timeout_ms: int = 45_000) -> dict[str, Any]:
        if not self._page:
            if sync_playwright is None:
                return {"ok": False, "error": "playwright package not installed"}
            return {"ok": False, "error": "browser session not started; use context manager"}
        try:
            self._page.goto(str(url), wait_until="domcontentloaded", timeout=int(timeout_ms))
        except Exception as exc:  # pragma: no cover
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        title = ""
        try:
            title = (self._page.title() or "")[:300]
        except Exception:
            title = ""
        return {"ok": True, "url": str(url), "title": title}

    def search(self, query: str, *, base_url: str | None = None, timeout_ms: int = 45_000) -> dict[str, Any]:
        if not self._page:
            return {"ok": False, "error": "browser session not active"}
        q = str(query or "").strip()
        if base_url and str(base_url).strip():
            r0 = self.open_url(str(base_url).strip(), timeout_ms=timeout_ms)
            if not r0.get("ok"):
                return r0
        # Prefer DuckDuckGo HTML (lightweight) when no base_url
        from urllib.parse import quote_plus

        ddg = f"https://html.duckduckgo.com/html/?q={quote_plus(q)}"
        try:
            self._page.goto(ddg, wait_until="domcontentloaded", timeout=int(timeout_ms))
        except Exception as exc:  # pragma: no cover
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        snippet = ""
        try:
            snippet = (self._page.inner_text("body") or "")[:2000]
        except Exception:
            snippet = ""
        return {"ok": True, "query": q, "snippet_preview": snippet[:800]}

    def click(self, selector: str, *, timeout_ms: int = 30_000) -> dict[str, Any]:
        if not self._page:
            return {"ok": False, "error": "browser session not active"}
        try:
            self._page.click(str(selector), timeout=int(timeout_ms))
        except Exception as exc:  # pragma: no cover
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        return {"ok": True, "selector": str(selector)}

    def try_click_selectors(
        self, selectors: list[str] | None, *, timeout_ms: int = 30_000
    ) -> dict[str, Any]:
        sels = [s for s in (selectors or []) if str(s).strip()] or [""]
        last_err = ""
        for s in sels:
            r = self.click(s, timeout_ms=timeout_ms)
            if r.get("ok") is True:
                return {**r, "matched_selector": s, "candidates_tried": len(sels)}
            last_err = str(r.get("error") or "")
        return {"ok": False, "error": last_err or "all selectors failed", "candidates_tried": len(sels)}

    def fill_form(self, fields: dict[str, str], *, timeout_ms: int = 30_000) -> dict[str, Any]:
        if not self._page:
            return {"ok": False, "error": "browser session not active"}
        filled: list[str] = []
        for sel, value in (fields or {}).items():
            self._page.fill(str(sel), str(value), timeout=int(timeout_ms))
            filled.append(str(sel))
        return {"ok": True, "filled_selectors": filled}
