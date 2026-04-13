"""Government schemes: Tavily + JSON extraction; persist ``govt_schemes``; optional Jarvis alerts."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import GovtScheme, Organization, UserOrganizationMembership
from services.research_common import groq_json_object_sync, snippets_blob_from_tavily, tavily_search_sync

_log = logging.getLogger("thiramai.research_schemes")

_SCHEME_SYSTEM = """From the snippets about Indian government schemes, output STRICT JSON:
{ "schemes": [ {
  "scheme_name": string,
  "eligibility": string,
  "subsidy_amount": string,
  "application_process": string,
  "deadline": string,
  "source_url": string or ""
} ] }
Use only facts supported by snippets; otherwise say "Verify on official portal". Empty schemes array if nothing relevant."""


def _norm_state(state: str) -> str:
    s = (state or "").strip()
    if len(s) <= 3:
        up = s.upper()
        if up == "TN":
            return "Tamil Nadu"
        return s
    return s


def find_schemes_sync(
    sector: str,
    state: str = "TN",
    *,
    user_id: int | None = None,
    organization_id: int | None = None,
    persist: bool = True,
    match_alerts: bool = True,
) -> dict[str, Any]:
    sec = (sector or "").strip()
    st = _norm_state(state)
    if not sec:
        return {"ok": False, "error": "sector required"}
    q = f"{st} India government subsidy scheme MSME {sec} 2025 2026 eligibility application how to apply"
    raw = tavily_search_sync(q, max_results=10)
    if isinstance(raw, dict) and raw.get("ok") is False:
        return {"ok": False, "error": raw.get("error") or "search failed"}
    blob = snippets_blob_from_tavily(raw)
    parsed = groq_json_object_sync(
        system=_SCHEME_SYSTEM,
        user_content=f"Sector: {sec}\nState focus: {st}\n\n{blob}",
        max_tokens=2500,
    )
    schemes_raw: list[dict[str, Any]] = []
    if isinstance(parsed, dict) and isinstance(parsed.get("schemes"), list):
        schemes_raw = [x for x in parsed["schemes"] if isinstance(x, dict)]
    normalized: list[dict[str, Any]] = []
    uid = int(user_id) if user_id and int(user_id) > 0 else None
    oid = int(organization_id) if organization_id and int(organization_id) > 0 else None

    fac = get_session_factory()
    default_url = ""
    if isinstance(raw, dict):
        for r in raw.get("results") or []:
            if isinstance(r, dict) and r.get("url"):
                default_url = str(r.get("url"))[:2000]
                break

    to_persist: list[GovtScheme] = []
    for item in schemes_raw[:12]:
        name = str(item.get("scheme_name") or "Scheme").strip()[:500]
        elig = str(item.get("eligibility") or "")[:4000]
        sub = str(item.get("subsidy_amount") or "")[:2000]
        proc = str(item.get("application_process") or "")[:4000]
        dl = str(item.get("deadline") or "")[:500]
        surl = str(item.get("source_url") or "").strip()[:2000] or default_url
        row_payload = {
            "scheme_name": name,
            "eligibility": elig,
            "subsidy_amount": sub,
            "application_process": proc,
            "deadline": dl,
            "application_url": surl,
        }
        normalized.append(row_payload)
        if persist and fac is not None:
            h = hashlib.sha256(f"{name}|{surl}|{sec}|{st}".encode()).hexdigest()[:32]
            to_persist.append(
                GovtScheme(
                    user_id=uid,
                    organization_id=oid,
                    sector=sec[:256],
                    state=st[:64],
                    scheme_name=name,
                    eligibility=elig or None,
                    subsidy_amount=sub or None,
                    application_process=proc or None,
                    deadline=dl or None,
                    source_url=surl or None,
                    content_json={"hash": h, "raw": item},
                )
            )

    if persist and fac is not None and to_persist:
        try:
            with fac() as session:
                with session.begin():
                    for row in to_persist:
                        existing = session.execute(
                            select(GovtScheme.id).where(
                                GovtScheme.scheme_name == row.scheme_name,
                                GovtScheme.sector == row.sector,
                                GovtScheme.state == row.state,
                            ).limit(1)
                        ).scalar_one_or_none()
                        if existing:
                            continue
                        session.add(row)
        except Exception as exc:
            _log.warning("persist govt_schemes batch: %s", exc)

    if match_alerts and uid and oid and fac is not None and normalized:
        try:
            _maybe_raise_scheme_alerts(uid, oid, sec, st, normalized)
        except Exception as exc:
            _log.debug("scheme alerts skipped: %s", exc)

    return {"ok": True, "sector": sec, "state": st, "schemes": normalized}


def _maybe_raise_scheme_alerts(
    user_id: int,
    organization_id: int,
    sector: str,
    state: str,
    schemes: list[dict[str, Any]],
) -> None:
    from services.jarvis_proactive_service import upsert_research_scheme_alert_sync

    fac = get_session_factory()
    if fac is None:
        return
    with fac() as session:
        org = session.get(Organization, int(organization_id))
        if org is None:
            return
        industry = (org.industry or "") + " " + (org.name or "")
        industry_l = industry.lower()
        sec_l = sector.lower()
        if sec_l and sec_l not in industry_l and not any(
            w in industry_l for w in sec_l.split() if len(w) > 3
        ):
            return
    top = schemes[0]
    msg = f"Scheme match for {sector} ({state}): {top.get('scheme_name', 'Program')[:120]}"
    upsert_research_scheme_alert_sync(
        user_id=user_id,
        organization_id=organization_id,
        message=msg,
        payload={"sector": sector, "state": state, "top_scheme": top},
    )


def list_org_industries_for_user_sync(user_id: int) -> list[tuple[int, str]]:
    uid = int(user_id)
    if uid <= 0:
        return []
    fac = get_session_factory()
    if fac is None:
        return []
    with fac() as session:
        mids = session.scalars(
            select(UserOrganizationMembership.organization_id).where(
                UserOrganizationMembership.user_id == uid,
                UserOrganizationMembership.is_active.is_(True),
            )
        ).all()
        oids = [int(m) for m in mids if m]
        out: list[tuple[int, str]] = []
        for oid in oids:
            org = session.get(Organization, oid)
            if org:
                label = (org.industry or org.name or "").strip()
                if label:
                    out.append((oid, label))
        return out
