"""Text embeddings for memory similarity — OpenAI when available; deterministic fallback otherwise."""

from __future__ import annotations

import hashlib
import math
from typing import Any


def _l2_normalize(vec: list[float]) -> list[float]:
    s = math.sqrt(sum(x * x for x in vec))
    if s <= 1e-12:
        return vec
    return [x / s for x in vec]


def hash_embedding(text: str, dim: int = 256) -> list[float]:
    """Cheap bag-of-hashes embedding (normalized), no network."""
    vec = [0.0] * dim
    for tok in text.lower().split():
        h = hashlib.sha256(tok.encode("utf-8")).digest()
        idx = int.from_bytes(h[:4], "big") % dim
        vec[idx] += 1.0
    return _l2_normalize(vec)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na <= 1e-12 or nb <= 1e-12:
        return 0.0
    return max(-1.0, min(1.0, dot / (na * nb)))


def embed_text(text: str, *, dim: int = 256) -> list[float]:
    """Prefer OpenAI embedding model when configured and mode allows; else hash_embedding."""
    raw = (text or "").strip()
    if not raw:
        return [0.0] * dim

    try:
        from thiramai.config import get_thiramai_mode

        if get_thiramai_mode() == "live":
            from openai import OpenAI

            from thiramai.config import OPENAI_API_KEY

            key = (OPENAI_API_KEY or "").strip()
            if key and key != "your_api_key_here":
                client = OpenAI(api_key=key)
                model = "text-embedding-3-small"
                resp = client.embeddings.create(model=model, input=raw[:8000])
                data = resp.data
                if data:
                    v = list(data[0].embedding)
                    return _l2_normalize(v)
    except Exception:
        pass

    return hash_embedding(raw, dim=dim)


def embed_pair_score(query: str, document: str) -> float:
    q = embed_text(query)
    d = embed_text(document)
    if len(q) != len(d):
        return cosine_similarity(q[: min(len(q), len(d))], d[: min(len(q), len(d))])
    return cosine_similarity(q, d)
