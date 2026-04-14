"""Build static HTML sites from org + inventory data (Part E)."""

from __future__ import annotations

import html
import logging
import os
import re
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.database import get_session_factory
from core.db.models import GeneratedWebsite, InventoryItem, Organization, User, UserOrganizationMembership
from core.security.org_access import verify_org_membership
from services.website_template_service import TEMPLATE_TYPES, get_template_bundle

_log = logging.getLogger("thiramai.website_builder")


def _sites_root() -> Path:
    raw = (os.getenv("THIRAMAI_SITES_ROOT") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.cwd() / "var" / "thiramai-sites").resolve()


def _public_domain() -> str:
    return (os.getenv("THIRAMAI_PUBLIC_SITE_DOMAIN") or "thiramai.co.in").strip().lower()


def slugify_org_name(name: str, organization_id: int) -> str:
    """DNS-safe slug; always suffix org id to avoid collisions."""
    base = re.sub(r"[^a-z0-9]+", "-", (name or "site").lower()).strip("-")[:40] or "site"
    base = base.strip("-") or "site"
    if not re.match(r"^[a-z0-9]", base):
        base = f"o{base}"
    return f"{base}-{int(organization_id)}"


def _escape(s: str | None) -> str:
    return html.escape((s or "").strip(), quote=True)


def _products_html(items: list[InventoryItem], *, empty_label: str) -> str:
    if not items:
        return f'      <div class="card"><h3>{_escape(empty_label)}</h3><p class="meta">Add products in THIRAMAI inventory to list them here.</p></div>'
    chunks: list[str] = []
    for it in items[:18]:
        price = it.unit_price
        price_s = f"₹{float(price):,.0f}" if price is not None else "Ask for price"
        unit = _escape(it.unit or "unit")
        chunks.append(
            "      <div class=\"card\">"
            f"<h3>{_escape(it.sku_name)}</h3>"
            f"<p class=\"meta\">{price_s} / {unit}</p>"
            f"<p class=\"meta\">Available: {float(it.quantity or 0):g}</p>"
            "</div>"
        )
    return "\n".join(chunks)


def _contact_block(org: Organization, contact_email: str | None) -> str:
    lines = []
    if contact_email:
        safe = _escape(contact_email)
        lines.append(f"<p><strong>Email:</strong> <a href=\"mailto:{safe}\">{safe}</a></p>")
    if org.gst_number:
        lines.append(f"<p><strong>GST:</strong> {_escape(org.gst_number)}</p>")
    if org.industry:
        lines.append(f"<p><strong>Sector:</strong> {_escape(org.industry)}</p>")
    if not lines:
        lines.append("<p>Contact us through your THIRAMAI business profile.</p>")
    return "\n    ".join(lines)


def _pick_contact_email(session: Session, organization_id: int) -> str | None:
    mems = list(
        session.scalars(
            select(UserOrganizationMembership)
            .where(
                UserOrganizationMembership.organization_id == int(organization_id),
                UserOrganizationMembership.is_active.is_(True),
            )
            .order_by(UserOrganizationMembership.joined_at.asc())
            .limit(24)
        ).all()
    )
    for m in mems:
        u = session.get(User, int(m.user_id))
        if u and (u.email or "").strip():
            return str(u.email).strip()
    return None


def assert_user_can_manage_org(session: Session, *, user_id: int, organization_id: int) -> bool:
    return verify_org_membership(session, user_id=int(user_id), organization_id=int(organization_id))


def user_can_access_org_sync(*, user_id: int, organization_id: int) -> bool:
    fac = get_session_factory()
    if fac is None:
        return False
    with fac() as session:
        return assert_user_can_manage_org(session, user_id=int(user_id), organization_id=int(organization_id))


def read_site_index_html_sync(organization_id: int, *, user_id: int | None = None) -> dict[str, Any]:
    """Return last built ``index.html`` for an org (membership enforced when ``user_id`` set)."""
    oid = int(organization_id)
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "database not configured"}
    with factory() as session:
        if user_id is not None and int(user_id) > 0:
            if not assert_user_can_manage_org(session, user_id=int(user_id), organization_id=oid):
                return {"ok": False, "error": "forbidden"}
        row = session.execute(select(GeneratedWebsite).where(GeneratedWebsite.organization_id == oid).limit(1)).scalar_one_or_none()
    if row is None or not (row.disk_path or "").strip():
        return {"ok": False, "error": "no published site on disk"}
    site_dir = Path(row.disk_path).expanduser().resolve()
    root = _sites_root().resolve()
    if not str(site_dir).startswith(str(root)):
        return {"ok": False, "error": "invalid stored path"}
    p = site_dir / "index.html"
    if not p.is_file():
        return {"ok": False, "error": "index.html missing"}
    try:
        html_content = p.read_text(encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "html": html_content,
        "slug": row.slug,
        "public_url": row.public_url,
        "site_dir": str(site_dir),
    }


def inline_static_assets_for_iframe(html: str, site_dir: Path) -> str:
    """Embed ``styles.css`` / ``app.js`` so ``srcDoc`` preview works without a separate origin."""
    css_path = site_dir / "styles.css"
    js_path = site_dir / "app.js"
    css = css_path.read_text(encoding="utf-8") if css_path.is_file() else ""
    js = js_path.read_text(encoding="utf-8") if js_path.is_file() else ""
    out = html
    out = out.replace('<link rel="stylesheet" href="styles.css" />', f"<style>\n{css}\n</style>", 1)
    out = out.replace('<script src="app.js"></script>', f"<script>\n{js}\n</script>", 1)
    return out


def read_site_iframe_preview_sync(organization_id: int, *, user_id: int) -> dict[str, Any]:
    base = read_site_index_html_sync(int(organization_id), user_id=int(user_id))
    if not base.get("ok"):
        return base
    site_dir = Path(str(base.get("site_dir") or "")).resolve()
    root = _sites_root().resolve()
    if not str(site_dir).startswith(str(root)):
        return {"ok": False, "error": "invalid site path"}
    try:
        inlined = inline_static_assets_for_iframe(base["html"], site_dir)
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "html": inlined, "slug": base.get("slug"), "public_url": base.get("public_url")}


def build_website_sync(
    business_id: int,
    template_type: str,
    *,
    user_id: int | None = None,
    run_deploy: bool = False,
) -> dict[str, Any]:
    """
    Generate ``index.html``, ``styles.css``, ``app.js`` under ``THIRAMAI_SITES_ROOT/<slug>/``.

    When ``user_id`` is set, requires active membership on ``business_id``.
    """
    oid = int(business_id)
    if oid <= 0:
        return {"ok": False, "error": "invalid business_id"}

    tt = (template_type or "shop").strip().lower()
    if tt not in TEMPLATE_TYPES:
        return {"ok": False, "error": f"template_type must be one of {sorted(TEMPLATE_TYPES)}"}

    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "database not configured"}

    with factory() as session:
        if user_id is not None and int(user_id) > 0:
            if not assert_user_can_manage_org(session, user_id=int(user_id), organization_id=oid):
                return {"ok": False, "error": "forbidden: not a member of this organization"}
        org = session.get(Organization, oid)
        if org is None or bool(org.is_disabled):
            return {"ok": False, "error": "organization not found"}
        items = list(
            session.scalars(
                select(InventoryItem)
                .where(InventoryItem.organization_id == oid)
                .order_by(InventoryItem.sku_name.asc())
                .limit(40)
            ).all()
        )
        contact_email = _pick_contact_email(session, oid)

    slug = slugify_org_name(org.name, oid)
    root = _sites_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"ok": False, "error": f"cannot create sites root: {exc}"}

    site_dir = (root / slug).resolve()
    if not str(site_dir).startswith(str(root)):
        return {"ok": False, "error": "invalid site path"}
    try:
        site_dir.mkdir(parents=True, exist_ok=True)
        (site_dir / "assets").mkdir(exist_ok=True)
    except OSError as exc:
        return {"ok": False, "error": f"cannot write site directory: {exc}"}

    bundle = get_template_bundle(tt)
    biz = _escape(org.name)
    industry = _escape(org.industry or "your partner")
    products = _products_html(
        items,
        empty_label="Catalog coming soon",
    )
    contact = _contact_block(org, contact_email)
    year = __import__("datetime").datetime.now().year
    footer = f"&copy; {year} {biz}. Powered by THIRAMAI."

    html_out = bundle["html"]
    html_out = (
        html_out.replace("__BUSINESS_NAME__", biz)
        .replace("__PRODUCTS_BLOCK__", products)
        .replace("__CONTACT_BLOCK__", contact)
        .replace("__FOOTER_LINE__", footer)
    )
    if "__ABOUT_TEXT__" in html_out:
        html_out = html_out.replace("__ABOUT_TEXT__", f"We are <strong>{biz}</strong> — {industry}.")

    css_out = bundle["css"]
    js_out = bundle["js"]

    try:
        (site_dir / "index.html").write_text(html_out, encoding="utf-8")
        (site_dir / "styles.css").write_text(css_out, encoding="utf-8")
        (site_dir / "app.js").write_text(js_out, encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "error": f"write failed: {exc}"}

    public_url = f"https://{slug}.{_public_domain()}/"
    out: dict[str, Any] = {
        "ok": True,
        "organization_id": oid,
        "slug": slug,
        "template_type": bundle["template_type"],
        "disk_path": str(site_dir),
        "public_url": public_url,
        "index_html": html_out,
    }

    try:
        from services import website_db_service as wdb

        wdb.upsert_generated_website_sync(
            organization_id=oid,
            slug=slug,
            template_type=bundle["template_type"],
            public_url=public_url,
            disk_path=str(site_dir),
        )
    except Exception as exc:
        _log.debug("website metadata upsert skipped: %s", exc)

    if run_deploy:
        try:
            from services.website_deploy_service import deploy_site_sync

            dep = deploy_site_sync(slug, site_root=root)
            out["deploy"] = dep
        except Exception as exc:
            out["deploy"] = {"ok": False, "error": str(exc)}

    return out
