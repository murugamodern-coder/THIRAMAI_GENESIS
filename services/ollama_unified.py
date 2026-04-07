"""
HTTP client for local Ollama ``/api/chat`` — unified brain (non-stream + stream).

Requires Ollama running (default ``http://127.0.0.1:11434``). Optional: set ``OLLAMA_HOST``.
"""

from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator

import httpx


class OllamaUnavailableError(RuntimeError):
    pass


def ollama_base_url() -> str:
    return (os.getenv("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")


def ollama_chat_sync(
    model: str,
    user_message: str,
    *,
    system: str | None = None,
    timeout: float = 120.0,
) -> str:
    """Blocking single response (for asyncio.to_thread)."""
    url = f"{ollama_base_url()}/api/chat"
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user_message})
    payload: dict[str, Any] = {"model": model, "messages": messages, "stream": False}
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(url, json=payload)
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as e:
        raise OllamaUnavailableError(str(e)) from e
    msg = data.get("message") if isinstance(data, dict) else None
    if isinstance(msg, dict):
        return str(msg.get("content") or "").strip()
    return ""


async def ollama_chat_async(
    model: str,
    user_message: str,
    *,
    system: str | None = None,
    timeout: float = 120.0,
) -> str:
    url = f"{ollama_base_url()}/api/chat"
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user_message})
    payload: dict[str, Any] = {"model": model, "messages": messages, "stream": False}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as e:
        raise OllamaUnavailableError(str(e)) from e
    msg = data.get("message") if isinstance(data, dict) else None
    if isinstance(msg, dict):
        return str(msg.get("content") or "").strip()
    return ""


async def ollama_chat_stream(
    model: str,
    user_message: str,
    *,
    system: str | None = None,
    timeout: float = 300.0,
) -> AsyncIterator[str]:
    """Yield incremental text chunks from Ollama streaming API."""
    url = f"{ollama_base_url()}/api/chat"
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user_message})
    payload: dict[str, Any] = {"model": model, "messages": messages, "stream": True}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    line = (line or "").strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    msg = obj.get("message") if isinstance(obj, dict) else None
                    piece = ""
                    if isinstance(msg, dict):
                        piece = str(msg.get("content") or "")
                    if piece:
                        yield piece
                    if isinstance(obj, dict) and obj.get("done") is True:
                        break
    except httpx.HTTPError as e:
        raise OllamaUnavailableError(str(e)) from e
