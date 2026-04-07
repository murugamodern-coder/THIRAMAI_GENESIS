"""
Central tool access: Groq chat, Tavily search, factory script catalog — timeouts + audit logging.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, TypeVar

from groq import Groq
from tavily import TavilyClient

from core.observability import LatencyTimer, estimate_chars_as_tokens, log_event
from core.policies.loader import (
    GROQ_CHAT_TIMEOUT_SEC,
    GROQ_MODEL,
    GROQ_SEARCH_SEED_TIMEOUT_SEC,
    TAVILY_SEARCH_TIMEOUT_SEC,
    _COMPLETION_TEMPERATURE,
    _MAX_TOKENS,
)
from services.business_service import list_factory_scripts

T = TypeVar("T")


def _run_with_timeout(fn: Callable[[], T], timeout_sec: float) -> T:
    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(fn)
        try:
            return fut.result(timeout=timeout_sec)
        except FuturesTimeout as e:
            raise TimeoutError(f"Tool timed out after {timeout_sec}s") from e


def _usage_tokens(completion: Any) -> tuple[int | None, int | None]:
    u = getattr(completion, "usage", None)
    if u is None:
        return None, None
    pt = getattr(u, "prompt_tokens", None) or getattr(u, "input_tokens", None)
    ct = getattr(u, "completion_tokens", None) or getattr(u, "output_tokens", None)
    try:
        return (int(pt) if pt is not None else None, int(ct) if ct is not None else None)
    except (TypeError, ValueError):
        return None, None


@dataclass
class ToolRegistry:
    request_id: str
    factory_root: Path | None = None
    _audit_tail: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def factory_script_catalog(self) -> list[dict[str, str]]:
        root = self.factory_root or Path(__file__).resolve().parents[1]
        names = list_factory_scripts(root)
        return [{"name": n, "module": f"factory.{n[:-3]}", "kind": "python_script"} for n in names]

    def groq_chat_completions_create(
        self,
        client: Groq,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout_sec: float | None = None,
        event_label: str = "groq.chat",
    ) -> Any:
        use_model = model or GROQ_MODEL
        use_temp = _COMPLETION_TEMPERATURE if temperature is None else temperature
        use_max = _MAX_TOKENS if max_tokens is None else max_tokens
        to = timeout_sec if timeout_sec is not None else GROQ_CHAT_TIMEOUT_SEC
        prompt_est = sum(estimate_chars_as_tokens(m.get("content") or "") for m in messages)
        timer = LatencyTimer()

        def _call() -> Any:
            return client.chat.completions.create(
                model=use_model,
                messages=messages,
                temperature=use_temp,
                max_tokens=use_max,
            )

        try:
            completion = _run_with_timeout(_call, to)
            pt, ct = _usage_tokens(completion)
            log_event(
                self.request_id,
                event_label,
                latency_ms=timer.ms(),
                tool="groq",
                ok=True,
                token_prompt_est=prompt_est,
                token_completion=ct,
                extra={"model": use_model, "provider_prompt_tokens": pt},
            )
            self._audit_tail.append(
                {
                    "tool": "groq",
                    "event": event_label,
                    "ok": True,
                    "latency_ms": timer.ms(),
                }
            )
            return completion
        except Exception as exc:
            log_event(
                self.request_id,
                event_label,
                latency_ms=timer.ms(),
                tool="groq",
                ok=False,
                token_prompt_est=prompt_est,
                error=str(exc),
                extra={"model": use_model},
            )
            self._audit_tail.append(
                {
                    "tool": "groq",
                    "event": event_label,
                    "ok": False,
                    "latency_ms": timer.ms(),
                    "error": str(exc)[:500],
                }
            )
            raise

    def tavily_search(
        self,
        client: TavilyClient,
        *,
        query: str,
        search_depth: str = "advanced",
        max_results: int = 8,
        timeout_sec: float | None = None,
    ) -> dict[str, Any]:
        to = timeout_sec if timeout_sec is not None else TAVILY_SEARCH_TIMEOUT_SEC
        timer = LatencyTimer()

        def _call() -> dict[str, Any]:
            return client.search(query=query, search_depth=search_depth, max_results=max_results)

        try:
            raw = _run_with_timeout(_call, to)
            log_event(
                self.request_id,
                "tavily.search",
                latency_ms=timer.ms(),
                tool="tavily",
                ok=True,
                extra={"query_len": len(query)},
            )
            self._audit_tail.append({"tool": "tavily", "ok": True, "latency_ms": timer.ms()})
            return raw
        except Exception as exc:
            log_event(
                self.request_id,
                "tavily.search",
                latency_ms=timer.ms(),
                tool="tavily",
                ok=False,
                error=str(exc),
            )
            self._audit_tail.append(
                {"tool": "tavily", "ok": False, "latency_ms": timer.ms(), "error": str(exc)[:500]}
            )
            raise

    def groq_search_seed(
        self,
        client: Groq,
        *,
        system: str,
        user: str,
        timeout_sec: float | None = None,
    ) -> Any:
        to = timeout_sec if timeout_sec is not None else GROQ_SEARCH_SEED_TIMEOUT_SEC
        return self.groq_chat_completions_create(
            client,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            max_tokens=120,
            timeout_sec=to,
            event_label="groq.search_seed",
        )


def default_registry(request_id: str) -> ToolRegistry:
    return ToolRegistry(request_id=request_id)
