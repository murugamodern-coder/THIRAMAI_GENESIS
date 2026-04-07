"""
Knowledge Vault: index files under /vault and build retrieval context for Groq (local only).
PDF support via pypdf when installed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
VAULT_DIR = ROOT / "vault"
RD_CORE_DIR = VAULT_DIR / "rd_core"
BUSINESS_CURRENT_NAME = "business_current.txt"


def tenant_vault_root(organization_id: int) -> Path:
    """Per-tenant files live under vault/tenants/<organization_id>/ (never read sibling tenants)."""
    return VAULT_DIR / "tenants" / str(int(organization_id))

# Skip structured state (injected via executive_core, not full-text index)
SKIP_NAMES = frozenset({"agenda_state.json", "user_profile.json"})
TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".log"}
PDF_EXTENSION = ".pdf"


def _read_text_file(path: Path, max_bytes: int = 400_000) -> str:
    try:
        raw = path.read_bytes()[:max_bytes]
        return raw.decode("utf-8", errors="replace")
    except OSError:
        return ""


def _read_pdf_file(path: Path, max_pages: int = 8, max_chars: int = 12_000) -> str:
    try:
        from pypdf import PdfReader  # type: ignore[import-untyped]
    except ImportError:
        return f"[PDF {path.name}: install pypdf to extract text]"
    try:
        reader = PdfReader(str(path))
        parts: list[str] = []
        n = min(len(reader.pages), max_pages)
        for i in range(n):
            t = reader.pages[i].extract_text() or ""
            parts.append(t)
        blob = "\n".join(parts)
        if len(blob) > max_chars:
            blob = blob[:max_chars] + "\n[... truncated ...]"
        return blob
    except Exception as exc:
        return f"[PDF {path.name}: extract error {type(exc).__name__}]"


def index_vault() -> list[dict[str, Any]]:
    """Scan vault/ and return index entries with text excerpts."""
    if not VAULT_DIR.is_dir():
        VAULT_DIR.mkdir(parents=True, exist_ok=True)
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(VAULT_DIR.rglob("*")):
        if not path.is_file():
            continue
        name = path.name
        if name in SKIP_NAMES:
            continue
        if name == "daily_log.txt" and path.parent == VAULT_DIR:
            # Included via executive_core tail; still index short head for search
            pass
        rel = path.relative_to(VAULT_DIR)
        ext = path.suffix.lower()
        text = ""
        if ext in TEXT_EXTENSIONS:
            max_b = 32_000 if name == "daily_log.txt" else 400_000
            text = _read_text_file(path, max_bytes=max_b)
        elif ext == PDF_EXTENSION:
            text = _read_pdf_file(path)
        else:
            continue
        text = re.sub(r"\s+", " ", text).strip()
        excerpt = text[:2500] if text else ""
        out.append(
            {
                "path": str(rel).replace("\\", "/"),
                "ext": ext,
                "chars": len(text),
                "excerpt": excerpt,
            }
        )
    return out


TOOL_EXTENSIONS = frozenset({".py", ".ts", ".js", ".mjs", ".yaml", ".yml"})


def business_current_loaded(*, min_chars: int = 40) -> bool:
    """True when vault/business_current.txt exists and has substantive text (routes Strategy Brief off agri-default)."""
    path = VAULT_DIR / BUSINESS_CURRENT_NAME
    if not path.is_file():
        return False
    try:
        text = _read_text_file(path, max_bytes=48_000)
    except OSError:
        return False
    core = re.sub(r"\s+", " ", (text or "").strip())
    return len(core) >= min_chars


def next_research_task_for_brief(*, organization_id: int | None = None) -> str:
    """
    Autonomous R&D nudge from humanoid roadmap (morning brief + CEO pack).

    When organization_id is set, only reads `vault/tenants/<id>/rd_core/` (tenant-safe).
    When None, legacy global `vault/rd_core/` (e.g. executive_core / single-tenant hosts).
    """
    rd_core = RD_CORE_DIR if organization_id is None else tenant_vault_root(int(organization_id)) / "rd_core"
    loc = "vault/rd_core/" if organization_id is None else f"vault/tenants/{int(organization_id)}/rd_core/"
    path = rd_core / "humanoid_robotics_roadmap.md"
    design = rd_core / "humanoid_design_v1.md"
    design_hint = ""
    if design.is_file():
        design_hint = (
            f" **Specs:** follow **`{loc}humanoid_design_v1.md`** (bushing OD 32 mm, clevis 48×24×36 mm, guard half ~220×180 mm). "
            "Run **`python factory/design_engine.py`** for the PE100 suitability report."
        )
    if not path.is_file():
        return (
            f"**Next research task:** Create `{loc}humanoid_robotics_roadmap.md`, then execute the first milestone. "
            "**Default first build:** design a **3D-printable joint** (clevis or revolute) for a humanoid chassis segment using **HDPE/PVC factory scrap** "
            "routed toward **shred → filament** for a single proof bracket."
        ) + (design_hint if design_hint else "")
    return (
        f"**Next research task (from `{loc}humanoid_robotics_roadmap.md`):** Execute **Q1–Q2 — Materials lab & CAD library** — "
        "publish wall thickness and rib rules, then **CAD + print one joint** for the humanoid chassis using **extrusion-grade HDPE/PVC**; "
        "validate **factory scrap → shred → filament → bracket** on a sovereign fixture before scaling."
    ) + design_hint


def pack_build_robot_go_no_go(*, max_chars: int = 2200, organization_id: int | None = None) -> str:
    """
    Go/No-Go for "Can we build the robot now?" using HQRS, AI training, and fab queue shortage flag.

    Skipped when organization_id is set: factory/vault sim paths are not tenant-isolated on disk.
    """
    if organization_id is not None:
        return ""
    try:
        from factory.fab_engine import ESTIMATED_PE100_KG, PART_ID, load_fab_queue
        from factory.robot_training_sim import read_last_training_run
        from factory.scrap_engine import load_inventory
    except Exception:
        return ""

    inv = load_inventory()
    scrap = float(inv.get("total_scrap_kg") or inv.get("high_quality_scrap_kg") or 0.0)
    t = read_last_training_run()
    sr: float | None = None
    if isinstance(t, dict):
        if t.get("success_rate") is not None:
            sr = float(t["success_rate"])
        elif t.get("success_rate_pct") is not None:
            sr = float(t["success_rate_pct"]) / 100.0

    q = load_fab_queue()
    ms = q.get("material_shortage") if isinstance(q.get("material_shortage"), dict) else {}
    shortage = bool(ms.get("active"))

    min_scrap = ESTIMATED_PE100_KG * 0.95
    min_sr = 0.62
    notes: list[str] = []
    if shortage:
        verdict = "**NO-GO**"
        notes.append(
            "**Material Shortage** in `fab_queue.json` — last fabrication enqueue could not deduct HQRS."
        )
    elif scrap + 1e-9 < min_scrap:
        verdict = "**NO-GO**"
        notes.append(
            f"HQRS **{scrap:.4f} kg** is below **~{min_scrap:.4f} kg** required for **{PART_ID}**."
        )
    elif sr is not None and sr < min_sr:
        verdict = "**CONDITIONAL GO**"
        notes.append(
            f"Joint sim **success_rate {sr:.2f}** is under advisory **{min_sr}** — re-run `robot_training_sim.py` or accept higher print risk."
        )
    else:
        verdict = "**GO (provisional)**"
        notes.append(
            "HQRS meets **Bushing-Joint V1** mass target; fab queue not in shortage. Verify **real printer**, **filament dry**, **215 °C PE100** profile."
        )
    if t is None:
        notes.append("No `robot_training_last.json` on disk — run **`python factory/robot_training_sim.py`** for a numeric success_rate.")

    block = (
        "## BUILD_ROBOT_GO_NO_GO (mandatory for this query)\n"
        f"- **Verdict:** {verdict}\n"
        f"- **total_scrap_kg (HQRS):** {scrap:.4f}\n"
        f"- **Bushing-Joint V1 est. mass:** ~{ESTIMATED_PE100_KG} kg PE100 equivalent\n"
    )
    if sr is not None:
        block += f"- **AI training success_rate:** {sr:.4f}\n"
    if shortage:
        block += f"- **Shortage detail:** need ~{ms.get('needed_kg')} kg, had {ms.get('available_kg')} kg\n"
    for n in notes:
        block += f"- {n}\n"
    block += "\nCEO: Echo **GO / NO-GO / CONDITIONAL GO** first, then cite vault numbers above.\n"
    if len(block) > max_chars:
        block = block[: max_chars - 24].rstrip() + "\n[... clipped ...]\n"
    return block


def pack_robot_learning_sim_block(*, max_chars: int = 1800, organization_id: int | None = None) -> str:
    """
    Inject joint-movement training stats.

    With organization_id: reads only `vault/tenants/<id>/rd_core/robot_training_last.json`.
    Without: legacy `read_last_training_run()` (global path).
    """
    d: dict | None = None
    if organization_id is not None:
        p = tenant_vault_root(int(organization_id)) / "rd_core" / "robot_training_last.json"
        if p.is_file():
            try:
                import json

                d = json.loads(p.read_text(encoding="utf-8"))
                if not isinstance(d, dict):
                    d = None
            except (OSError, json.JSONDecodeError):
                d = None
        if d is None:
            return (
                "## ROBOT_TRAINING_SIM (tenant-scoped)\n"
                f"_No `{p.as_posix()}` — copy or generate tenant-specific training JSON here._\n"
            )
    else:
        try:
            from factory.robot_training_sim import read_last_training_run
        except Exception:
            return ""
        d = read_last_training_run()
    if not d:
        if organization_id is not None:
            p = tenant_vault_root(int(organization_id)) / "rd_core" / "robot_training_last.json"
            return (
                "## ROBOT_TRAINING_SIM (mandatory for this query)\n"
                f"_No `{p.as_posix()}` — add tenant training JSON or run sim and copy output here._\n"
            )
        return (
            "## ROBOT_TRAINING_SIM (mandatory for this query)\n"
            "_No `vault/rd_core/robot_training_last.json` yet._ "
            "Run **`python factory/robot_training_sim.py`** to generate **1000-trial** joint-movement stats.\n"
        )
    ic = d.get("iteration_count")
    if ic is None:
        ic = d.get("trials")
    sr = d.get("success_rate")
    if sr is None and d.get("success_rate_pct") is not None:
        sr = round(float(d["success_rate_pct"]) / 100.0, 4)
    line = (
        f"- **success_rate:** **{sr}** ({d.get('success_rate_pct')}%)\n"
        f"- **iteration_count:** {ic} (bushing-joint sim)\n"
        f"- **failure_point_newtons** (mean of failed trials): **{d.get('failure_point_newtons')}**\n"
        f"- **Successes / trials:** {d.get('successes')}/{d.get('trials')}\n"
        f"- **PE100 mean criterion score:** {d.get('mean_pe100_criterion_score')}\n"
        f"- **Modelled per-trial p(success):** {d.get('per_trial_p_success_model')}\n"
        f"- **Last run (UTC):** {d.get('run_utc')}\n"
        f"- **Disclaimer:** {d.get('disclaimer', '')}\n"
    )
    block = "## ROBOT_TRAINING_SIM (latest vault snapshot)\n" + line
    if len(block) > max_chars:
        block = block[: max_chars - 20].rstrip() + "\n[... clipped ...]\n"
    return block


def pack_humanoid_design_next_step_block(*, max_chars: int = 2800, organization_id: int) -> str:
    """
    When the user asks for the next R&D / CAD step, inject specs from this tenant's
    vault/tenants/<organization_id>/rd_core/humanoid_design_v1.md only.
    """
    path = tenant_vault_root(int(organization_id)) / "rd_core" / "humanoid_design_v1.md"
    if not path.is_file():
        return ""
    body = _read_text_file(path, max_bytes=min(120_000, max_chars * 3))
    body = (body or "").replace("\r\n", "\n").strip()
    if not body:
        return ""
    m = re.search(
        r"(## Next physical step[^\n]*\n+(.*?))(?=\n## |\Z)",
        body,
        flags=re.DOTALL | re.IGNORECASE,
    )
    snippet = (m.group(1).strip() if m else body[:max_chars])
    if len(snippet) > max_chars:
        snippet = snippet[: max_chars - 24].rstrip() + "\n[... truncated ...]"
    rel = path.relative_to(VAULT_DIR).as_posix()
    return (
        "## HUMANOID_DESIGN_V1 (mandatory concrete specs for this query)\n"
        "The user asked for the **next R&D step**. **Quote** these tenant-scoped dimensions, materials, and checks "
        f"(from `{rel}`):\n\n"
        f"{snippet}\n"
    )


def load_rd_core_context(max_chars: int = 2800, *, organization_id: int) -> str:
    """
    R&D markdown under vault/tenants/<organization_id>/rd_core/ only (no global rd_core).
    """
    names = (
        "humanoid_robotics_roadmap.md",
        "humanoid_design_v1.md",
        "solar_agri_integration.md",
    )
    rd_dir = tenant_vault_root(int(organization_id)) / "rd_core"
    if not rd_dir.is_dir():
        return (
            f"**R&D Core (tenant {int(organization_id)})** — _No folder `{rd_dir.relative_to(ROOT).as_posix()}/`._\n"
            "_Add markdown there to include robotics/solar context in the brain._"
        )
    chunks: list[str] = []
    used = 0
    for name in names:
        path = rd_dir / name
        if not path.is_file():
            continue
        body = _read_text_file(path, max_bytes=min(48_000, max_chars + 500))
        body = (body or "").strip()
        if not body:
            continue
        rel = path.relative_to(VAULT_DIR).as_posix()
        block = f"### vault/{rel}\n```\n{body}\n```\n"
        if used + len(block) > max_chars:
            remain = max(0, max_chars - used - 120)
            if remain > 400:
                block = f"### vault/{rel}\n```\n{body[:remain]}\n[... truncated ...]\n```\n"
                chunks.append(block)
            break
        chunks.append(block)
        used += len(block)
    if not chunks:
        return ""
    return f"**R&D Core (tenant {int(organization_id)})** — under `vault/tenants/{int(organization_id)}/rd_core/`:\n\n" + "\n".join(
        chunks
    )


def index_tenant_vault(organization_id: int) -> list[dict[str, Any]]:
    """Like index_vault but only under vault/tenants/<organization_id>/ (recursive)."""
    root = tenant_vault_root(int(organization_id))
    if not root.is_dir():
        root.mkdir(parents=True, exist_ok=True)
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        name = path.name
        if name in SKIP_NAMES:
            continue
        rel = path.relative_to(VAULT_DIR)
        ext = path.suffix.lower()
        text = ""
        if ext in TEXT_EXTENSIONS:
            max_b = 32_000 if name == "daily_log.txt" else 400_000
            text = _read_text_file(path, max_bytes=max_b)
        elif ext == PDF_EXTENSION:
            text = _read_pdf_file(path)
        else:
            continue
        text = re.sub(r"\s+", " ", text).strip()
        excerpt = text[:2500] if text else ""
        out.append(
            {
                "path": str(rel).replace("\\", "/"),
                "ext": ext,
                "chars": len(text),
                "excerpt": excerpt,
            }
        )
    return out


def load_vault_txt_pdf_flat(max_chars: int = 4000, *, organization_id: int) -> str:
    """
    .txt / .pdf only under vault/tenants/<organization_id>/ (tenant boundary).
    """
    root = tenant_vault_root(int(organization_id))
    if not root.is_dir():
        root.mkdir(parents=True, exist_ok=True)
        return (
            f"_Tenant Knowledge Vault_: create **`{root.relative_to(ROOT).as_posix()}/`** and add .txt/.pdf files._"
        )
    chunks: list[str] = []
    used = 0
    paths: list[Path] = []
    for ext in (".txt", ".pdf"):
        paths.extend(root.rglob(f"*{ext}"))
    seen: set[Path] = set()
    for path in sorted(set(paths), key=lambda p: str(p).lower()):
        if not path.is_file() or path in seen:
            continue
        seen.add(path)
        if path.name in SKIP_NAMES:
            continue
        rel = path.relative_to(VAULT_DIR).as_posix()
        per_file_cap = 12_000 if path.name == "daily_log.txt" else 25_000
        if path.suffix.lower() == ".txt":
            body = _read_text_file(path, max_bytes=min(per_file_cap, 120_000))
        else:
            body = _read_pdf_file(path, max_pages=12, max_chars=min(per_file_cap, 14_000))
        body = re.sub(r"\s+", " ", (body or "").strip())
        if not body:
            continue
        block = f"### vault/{rel}\n```\n{body}\n```\n"
        if used + len(block) > max_chars:
            remain = max_chars - used - 80
            if remain > 200:
                block = f"### vault/{rel}\n```\n{body[:remain]}\n[... truncated ...]\n```\n"
                chunks.append(block)
            break
        chunks.append(block)
        used += len(block)
    if not chunks:
        return (
            f"_Tenant Knowledge Vault_: no .txt/.pdf under **`vault/tenants/{int(organization_id)}/`**._"
        )
    return f"**Knowledge Vault — tenant {int(organization_id)} (.txt / .pdf)**\n\n" + "\n".join(chunks)


def list_vault_tooling_seeds() -> list[str]:
    """Paths under vault/ that may seed future SaaS Factory mini-tools."""
    if not VAULT_DIR.is_dir():
        return []
    out: list[str] = []
    for path in sorted(VAULT_DIR.rglob("*")):
        if path.is_file() and path.suffix.lower() in TOOL_EXTENSIONS:
            out.append(path.relative_to(VAULT_DIR).as_posix())
    return out


def _score_relevance(query: str, excerpt: str) -> int:
    if not query or not excerpt:
        return 0
    q_tokens = set(re.findall(r"[a-zA-Z0-9]{3,}", query.lower()))
    e_low = excerpt.lower()
    return sum(1 for t in q_tokens if t in e_low)


def build_vault_context(user_query: str, max_chars: int = 3500, *, organization_id: int) -> str:
    """
    Indexed excerpts from vault/tenants/<organization_id>/ only (keyword-ranked).
    """
    entries = index_tenant_vault(int(organization_id))
    if not entries:
        return (
            f"_Tenant Knowledge Vault_: no indexed files under **`vault/tenants/{int(organization_id)}/`** "
            "(.txt, .md, .csv, .json, .pdf)._"
        )
    scored = sorted(
        entries,
        key=lambda e: _score_relevance(user_query, e.get("excerpt", "")),
        reverse=True,
    )
    lines = ["**Indexed vault files** (local, not web):"]
    buf: list[str] = []
    for e in scored:
        header = f"- `{e['path']}` ({e['ext']}, ~{e['chars']} chars)"
        chunk = f"{header}\n```\n{e.get('excerpt', '')}\n```"
        if len("\n\n".join(buf)) + len(chunk) + 200 > max_chars:
            if not buf:
                chunk = chunk[: max_chars - 200] + "\n[...]\n```"
            else:
                break
        buf.append(chunk)
    lines.append("\n\n".join(buf))
    return "\n".join(lines)


def main() -> None:
    """CLI: python vault_memory.py"""
    idx = index_vault()
    print(f"Vault dir: {VAULT_DIR}")
    print(f"Files indexed: {len(idx)}")
    for e in idx:
        print(f"  - {e['path']} ({e['ext']}) chars={e['chars']}")


if __name__ == "__main__":
    main()
