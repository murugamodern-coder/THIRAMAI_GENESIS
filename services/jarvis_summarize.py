"""One-line Groq summaries for JARVIS email alerts (optional; no key → caller uses fallback)."""

from __future__ import annotations

import os

from groq import Groq

from core.policies.loader import GROQ_MODEL


def summarize_jarvis_emergency(
    *,
    subject: str,
    body_excerpt: str,
    category_label: str,
) -> str | None:
    """
    Return a single imperative sentence for the notification body, or ``None`` if Groq unavailable.
    """
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    if not key:
        return None
    excerpt = (body_excerpt or "")[:3500]
    sys = (
        "You are JARVIS, a concise ops assistant. Output exactly ONE short sentence (max 220 chars) "
        "telling the business owner what the email implies and the next action. No markdown, no quotes."
    )
    user = f"Category: {category_label}\nSubject: {subject}\n\nExcerpt:\n{excerpt}"
    try:
        client = Groq(api_key=key)
        comp = client.chat.completions.create(
            model=(os.getenv("GROQ_MODEL") or GROQ_MODEL),
            messages=[
                {"role": "system", "content": sys},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            max_tokens=120,
        )
        choice = comp.choices[0].message.content or ""
        line = " ".join(choice.strip().split())
        return line[:500] if line else None
    except Exception:
        return None
