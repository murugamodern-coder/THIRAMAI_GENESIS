from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class LocalKnowledgeBase:
    """
    Vector-lite local retrieval over JSON/Markdown knowledge files.
    Uses keyword overlap scoring with optional tag boosts.
    """

    def __init__(self, knowledge_dir: str | Path | None = None) -> None:
        root = Path(knowledge_dir) if knowledge_dir else Path.cwd() / "knowledge"
        self.knowledge_dir = root.resolve()
        self._entries: list[dict[str, Any]] = []

    def load(self) -> None:
        self._entries = []
        if not self.knowledge_dir.exists():
            return
        patterns = ("*.json", "*.md", "*.markdown")
        for pattern in patterns:
            for path in sorted(self.knowledge_dir.glob(pattern)):
                entry = self._load_file(path)
                if entry:
                    self._entries.append(entry)

    def retrieve(self, query: str, *, limit: int = 4) -> list[dict[str, Any]]:
        if not self._entries:
            self.load()
        q = str(query or "").strip().lower()
        if not q:
            return []
        q_tokens = self._tokens(q)
        scored: list[tuple[float, dict[str, Any]]] = []
        for e in self._entries:
            text = str(e.get("text", "")).lower()
            if not text:
                continue
            t_tokens = self._tokens(text)
            overlap = len(q_tokens.intersection(t_tokens))
            if overlap <= 0:
                continue
            score = float(overlap)
            tags = [str(t).lower() for t in e.get("tags", [])]
            for t in tags:
                if t in q:
                    score += 1.5
            if "tiruvannamalai" in q and "tiruvannamalai" in text:
                score += 2.0
            scored.append((score, e))
        scored.sort(key=lambda x: x[0], reverse=True)
        out: list[dict[str, Any]] = []
        for score, e in scored[: max(1, min(limit, 6))]:
            snippet = self._snippet_for_query(e.get("text", ""), q_tokens)
            out.append(
                {
                    "source": e.get("source", ""),
                    "title": e.get("title", ""),
                    "score": round(score, 2),
                    "snippet": snippet,
                    "tags": e.get("tags", []),
                }
            )
        return out

    def summarize(self, snippets: list[dict[str, Any]]) -> str:
        if not snippets:
            return "No relevant local knowledge found."
        lines: list[str] = []
        for idx, item in enumerate(snippets[:5], start=1):
            title = str(item.get("title", "knowledge")).strip() or "knowledge"
            snippet = str(item.get("snippet", "")).replace("\n", " ").strip()
            if len(snippet) > 220:
                snippet = snippet[:217] + "..."
            lines.append(f"{idx}. [{title}] {snippet}")
        return "\n".join(lines)

    def _load_file(self, path: Path) -> dict[str, Any] | None:
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None
        suffix = path.suffix.lower()
        if suffix == ".json":
            return self._from_json(path, raw)
        return self._from_markdown(path, raw)

    def _from_json(self, path: Path, raw: str) -> dict[str, Any] | None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        title = str(data.get("title") or path.stem).strip()
        tags = data.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        text = json.dumps(data, ensure_ascii=False)
        return {"source": path.name, "title": title, "tags": tags, "text": text}

    def _from_markdown(self, path: Path, raw: str) -> dict[str, Any]:
        lines = raw.splitlines()
        title = path.stem.replace("_", " ").title()
        for ln in lines[:8]:
            if ln.strip().startswith("#"):
                title = ln.strip().lstrip("#").strip() or title
                break
        return {"source": path.name, "title": title, "tags": self._infer_tags(raw), "text": raw}

    def _snippet_for_query(self, text: str, q_tokens: set[str]) -> str:
        if not text:
            return ""
        compact = re.sub(r"\s+", " ", text).strip()
        if len(compact) <= 260:
            return compact
        low = compact.lower()
        for tok in q_tokens:
            idx = low.find(tok)
            if idx >= 0:
                start = max(0, idx - 90)
                end = min(len(compact), idx + 170)
                return compact[start:end]
        return compact[:260]

    def _infer_tags(self, raw: str) -> list[str]:
        text = raw.lower()
        dictionary = [
            "agro-industrial",
            "jaggery",
            "biomass",
            "drip irrigation",
            "maraseku",
            "wood-pressed oil",
            "inventory",
            "land",
            "tiruvannamalai",
            "crop cycles",
        ]
        return [t for t in dictionary if t in text]

    def _tokens(self, text: str) -> set[str]:
        cleaned = re.sub(r"[^a-z0-9\s]", " ", text.lower())
        return {w for w in cleaned.split() if len(w) >= 3}
