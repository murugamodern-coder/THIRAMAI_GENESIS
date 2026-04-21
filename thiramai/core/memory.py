import json
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from thiramai.config import DATA_DIR, MEMORY_FILE


class MemoryStore:
    def __init__(self, file_path: Path = MEMORY_FILE) -> None:
        self.file_path = file_path
        self._lock = threading.Lock()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self.file_path.write_text(
                json.dumps(
                    {
                        "events": [],
                        "learning": {
                            "failures": [],
                            "success_patterns": [],
                            "learned_rules": [],
                        },
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

    def append(self, event_type: str, payload: dict[str, Any]) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "payload": payload,
        }
        with self._lock:
            store = self._read_store_unlocked()
            store["events"].append(entry)
            self._write_store_unlocked(store)

    def read_all(self) -> list[dict[str, Any]]:
        with self._lock:
            store = self._read_store_unlocked()
            return store["events"]

    def analyze_failures(self, events: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        items = events if events is not None else self.read_all()
        failure_events = [e for e in items if e.get("event_type") == "failure"]
        if not failure_events:
            return []

        command_counter: Counter[str] = Counter()
        error_counter: Counter[str] = Counter()
        blocked_counter: Counter[str] = Counter()

        for event in failure_events:
            payload = event.get("payload", {})
            if not isinstance(payload, dict):
                continue

            task = payload.get("task", {})
            if isinstance(task, dict):
                cmd = str(task.get("command", "")).strip().lower()
                if cmd:
                    command_counter[cmd] += 1

            reason = str(payload.get("reason", payload.get("initial_review", ""))).strip().lower()
            if reason:
                error_counter[reason[:120]] += 1

            if "blocked" in reason or str(payload.get("failure_type", "")).lower() == "blocked_command":
                blocked_key = str(task.get("command", "unknown_command")).strip().lower() if isinstance(task, dict) else "unknown_command"
                blocked_counter[blocked_key] += 1

        patterns: list[dict[str, Any]] = []
        for cmd, count in command_counter.most_common(5):
            if count >= 2:
                patterns.append(
                    {
                        "pattern": f"repeated_command_failure:{cmd}",
                        "frequency": count,
                        "recommendation": f"Avoid repeating `{cmd}` without alternate diagnostics.",
                    }
                )

        for err, count in error_counter.most_common(5):
            if count >= 2:
                patterns.append(
                    {
                        "pattern": f"repeated_error_pattern:{err}",
                        "frequency": count,
                        "recommendation": "Use safer fallback plan and tighten command criteria.",
                    }
                )

        for blocked, count in blocked_counter.most_common(5):
            if count >= 1:
                patterns.append(
                    {
                        "pattern": f"blocked_command_pattern:{blocked}",
                        "frequency": count,
                        "recommendation": "Replace blocked command with approved diagnostics.",
                    }
                )

        unique: dict[str, dict[str, Any]] = {}
        for pattern in patterns:
            unique[pattern["pattern"]] = pattern
        return list(unique.values())

    def update_learning(self) -> dict[str, Any]:
        with self._lock:
            store = self._read_store_unlocked()
            events = store["events"]
            patterns = self.analyze_failures(events=events)

            success_patterns: list[dict[str, Any]] = []
            success_commands: Counter[str] = Counter()
            for event in events:
                if event.get("event_type") != "result":
                    continue
                payload = event.get("payload", {})
                if not isinstance(payload, dict):
                    continue
                review = payload.get("review", {})
                task = payload.get("task", {})
                if isinstance(review, dict) and review.get("status") == "pass" and isinstance(task, dict):
                    command = str(task.get("command", "")).strip().lower()
                    if command:
                        success_commands[command] += 1
            for cmd, count in success_commands.most_common(10):
                success_patterns.append(
                    {
                        "command": cmd,
                        "frequency": count,
                        "strategy": "prefer_command_with_success_history",
                    }
                )

            learned_rules = [p["recommendation"] for p in patterns]
            learning_state = {
                "failures": patterns,
                "success_patterns": success_patterns,
                "learned_rules": learned_rules,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            store["learning"] = learning_state
            store["events"].append(
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "event_type": "learning_update",
                    "payload": learning_state,
                }
            )
            self._write_store_unlocked(store)
            return learning_state

    def get_learning_snapshot(self) -> dict[str, Any]:
        with self._lock:
            store = self._read_store_unlocked()
            learning = store.get("learning", {})
            if isinstance(learning, dict):
                return learning
            return {"failures": [], "success_patterns": [], "learned_rules": []}

    def search_past_solutions(self, query: str, *, limit: int = 8) -> list[dict[str, Any]]:
        """
        Keyword similarity over stored goals / outcomes (Jaccard on word sets).
        Surfaces recent ``plan``, ``result``, ``failure``, ``cycle_summary``, ``goal_job`` payloads.
        """
        q = (query or "").strip().lower()
        if not q:
            return []
        q_tokens = set(q.split())
        if not q_tokens:
            return []
        lim = max(1, min(int(limit), 50))
        scored: list[tuple[float, dict[str, Any]]] = []
        for event in self.read_all():
            et = str(event.get("event_type", ""))
            if et not in {"plan", "result", "failure", "cycle_summary", "goal_job", "self_heal"}:
                continue
            payload = event.get("payload", {})
            if not isinstance(payload, dict):
                continue
            blob = json.dumps(payload, ensure_ascii=True).lower()
            goal_txt = str(payload.get("goal", "")).lower()
            haystack = f"{goal_txt} {blob}"
            h_tokens = set(haystack.split())
            if not h_tokens:
                continue
            inter = len(q_tokens & h_tokens)
            union = len(q_tokens | h_tokens) or 1
            score = float(inter) / float(union)
            if score <= 0:
                continue
            scored.append(
                (
                    score,
                    {
                        "score": round(score, 4),
                        "event_type": et,
                        "ts": event.get("ts"),
                        "goal": payload.get("goal"),
                        "snippet": haystack[:400],
                    },
                )
            )
        scored.sort(key=lambda x: x[0], reverse=True)
        dedup: dict[str, dict[str, Any]] = {}
        for _s, row in scored:
            key = f"{row.get('event_type')}:{row.get('snippet', '')[:80]}"
            if key not in dedup:
                dedup[key] = row
            if len(dedup) >= lim:
                break
        return list(dedup.values())

    def record_goal_job_outcome(self, goal: str, summary: dict[str, Any]) -> None:
        """Persist API-triggered autonomous runs for reuse / analytics."""
        self.append(
            "goal_job",
            {"goal": goal, **summary},
        )

    def search_past_solutions_hybrid(self, query: str, *, limit: int = 8) -> list[dict[str, Any]]:
        """
        Keyword recall plus embedding similarity (cosine on hash/OpenAI embeddings).
        Deprioritizes payloads that resemble known failure-only patterns.
        """
        kw_hits = self.search_past_solutions(query, limit=limit)
        try:
            from thiramai.integrations.embeddings import embed_pair_score
        except ImportError:
            return kw_hits

        q = (query or "").strip()
        if not q:
            return kw_hits

        scored: dict[str, tuple[float, dict[str, Any]]] = {}
        for row in kw_hits:
            key = f"k:{row.get('event_type')}:{str(row.get('snippet', ''))[:64]}"
            scored[key] = (float(row.get("score", 0.5)), {**row, "source": "keyword"})

        failure_commands: set[str] = set()
        for event in self.read_all():
            if event.get("event_type") != "failure":
                continue
            pl = event.get("payload", {})
            if isinstance(pl, dict):
                t = pl.get("task", {})
                if isinstance(t, dict) and t.get("command"):
                    failure_commands.add(str(t.get("command")).strip().lower())

        for event in self.read_all():
            et = str(event.get("event_type", ""))
            if et not in {"plan", "result", "failure", "cycle_summary", "goal_job", "self_heal"}:
                continue
            payload = event.get("payload", {})
            if not isinstance(payload, dict):
                continue
            goal_txt = str(payload.get("goal", ""))
            blob = json.dumps(payload, ensure_ascii=True)
            doc = f"{goal_txt}\n{blob}"[:12000]
            sc = embed_pair_score(q, doc)
            if sc <= 0.05:
                continue
            key = f"e:{et}:{event.get('ts')}:{goal_txt[:40]}"
            cmd = ""
            task_o = payload.get("task")
            if isinstance(task_o, dict) and task_o.get("command"):
                cmd = str(task_o["command"]).strip().lower()
            if cmd and cmd in failure_commands:
                sc *= 0.5
            row = {
                "score": round(float(sc), 4),
                "event_type": et,
                "ts": event.get("ts"),
                "goal": payload.get("goal"),
                "snippet": doc[:400],
                "source": "embedding",
            }
            if key not in scored or sc > scored[key][0]:
                scored[key] = (float(sc), row)

        merged = sorted(scored.values(), key=lambda x: x[0], reverse=True)
        out = [m[1] for m in merged[: max(1, min(int(limit), 50))]]
        return out or kw_hits

    def _read_store_unlocked(self) -> dict[str, Any]:
        raw = self.file_path.read_text(encoding="utf-8").strip()
        if not raw:
            return {"events": [], "learning": {"failures": [], "success_patterns": [], "learned_rules": []}}
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            # Backward compatibility with older event-only memory format.
            return {"events": parsed, "learning": {"failures": [], "success_patterns": [], "learned_rules": []}}
        if isinstance(parsed, dict):
            events = parsed.get("events", [])
            learning = parsed.get("learning", {"failures": [], "success_patterns": [], "learned_rules": []})
            if not isinstance(events, list):
                events = []
            if not isinstance(learning, dict):
                learning = {"failures": [], "success_patterns": [], "learned_rules": []}
            return {"events": events, "learning": learning}
        return {"events": [], "learning": {"failures": [], "success_patterns": [], "learned_rules": []}}

    def _write_store_unlocked(self, store: dict[str, Any]) -> None:
        self.file_path.write_text(json.dumps(store, indent=2), encoding="utf-8")
