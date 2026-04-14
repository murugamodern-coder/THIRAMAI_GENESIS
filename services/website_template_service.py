"""Static HTML/CSS/JS bundles for auto-generated business sites (Part E).

Placeholders use ``__NAME__`` tokens (not ``{{}}``) so CSS braces stay valid.
"""

from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger("thiramai.website_template")

TEMPLATE_TYPES: frozenset[str] = frozenset({"shop", "manufacturing", "services"})

_BASE_CSS = """
:root {
  --bg: #0f172a;
  --card: #1e293b;
  --accent: #38bdf8;
  --accent2: #f59e0b;
  --text: #f8fafc;
  --muted: #94a3b8;
  --font: system-ui, -apple-system, "Segoe UI", Roboto, "Noto Sans Tamil", sans-serif;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: var(--font);
  background: var(--bg);
  color: var(--text);
  line-height: 1.55;
}
a { color: var(--accent); }
header {
  padding: 1rem 1.25rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #334155;
  position: sticky;
  top: 0;
  background: rgba(15, 23, 42, 0.92);
  backdrop-filter: blur(8px);
  z-index: 20;
}
.brand { font-weight: 800; letter-spacing: -0.02em; font-size: 1.15rem; }
.nav-toggle {
  display: none;
  background: var(--card);
  color: var(--text);
  border: 1px solid #475569;
  padding: 0.4rem 0.75rem;
  border-radius: 8px;
  cursor: pointer;
}
nav ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  gap: 1.25rem;
}
nav a { text-decoration: none; color: var(--muted); font-weight: 500; }
nav a:hover { color: var(--text); }
.hero {
  padding: 3rem 1.25rem 2.5rem;
  text-align: center;
  background: radial-gradient(ellipse at top, #1e3a5f 0%, var(--bg) 55%);
}
.hero h1 { font-size: clamp(1.8rem, 4vw, 2.6rem); margin: 0 0 0.75rem; }
.hero p { color: var(--muted); max-width: 40rem; margin: 0 auto 1.5rem; }
.cta-row { display: flex; gap: 0.75rem; justify-content: center; flex-wrap: wrap; }
.btn {
  display: inline-block;
  padding: 0.65rem 1.2rem;
  border-radius: 10px;
  font-weight: 600;
  text-decoration: none;
  border: none;
  cursor: pointer;
}
.btn-primary { background: var(--accent); color: #0f172a; }
.btn-secondary { background: transparent; color: var(--text); border: 1px solid #475569; }
section { padding: 2.5rem 1.25rem; max-width: 960px; margin: 0 auto; }
section h2 { font-size: 1.35rem; margin: 0 0 1rem; }
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 1rem;
}
.card {
  background: var(--card);
  border-radius: 12px;
  padding: 1rem 1.1rem;
  border: 1px solid #334155;
}
.card h3 { margin: 0 0 0.35rem; font-size: 1rem; }
.card .meta { color: var(--muted); font-size: 0.85rem; }
.about { color: var(--muted); }
.contact-box {
  background: var(--card);
  border-radius: 12px;
  padding: 1.25rem;
  border: 1px solid #334155;
}
footer {
  padding: 2rem 1.25rem;
  text-align: center;
  color: var(--muted);
  font-size: 0.9rem;
  border-top: 1px solid #334155;
}
@media (max-width: 720px) {
  .nav-toggle { display: block; }
  nav ul {
    display: none;
    flex-direction: column;
    position: absolute;
    right: 1rem;
    top: 3.5rem;
    background: var(--card);
    padding: 1rem;
    border-radius: 10px;
    border: 1px solid #475569;
  }
  nav.open ul { display: flex; }
}
"""

_BASE_JS = """
(function () {
  var btn = document.querySelector('.nav-toggle');
  var nav = document.querySelector('header nav');
  if (btn && nav) {
    btn.addEventListener('click', function () { nav.classList.toggle('open'); });
  }
})();
"""

_HTML_SHELL = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>__PAGE_TITLE__</title>
  <meta name="description" content="__META_DESCRIPTION__" />
  <link rel="stylesheet" href="styles.css" />
</head>
<body>
  <header>
    <div class="brand">__BUSINESS_NAME__</div>
    <button type="button" class="nav-toggle" aria-label="Menu">Menu</button>
    <nav>
      <ul>
        <li><a href="#hero">Home</a></li>
        <li><a href="#catalog">__CATALOG_NAV__</a></li>
        <li><a href="#about">About</a></li>
        <li><a href="#contact">Contact</a></li>
      </ul>
    </nav>
  </header>
  <section id="hero" class="hero">
    <h1>__HERO_HEADLINE__</h1>
    <p>__HERO_SUB__</p>
    <div class="cta-row">
      <a class="btn btn-primary" href="#contact">Get in touch</a>
      <a class="btn btn-secondary" href="#catalog">Explore</a>
    </div>
  </section>
  <section id="catalog">
    <h2>__CATALOG_TITLE__</h2>
    <div class="grid">
__PRODUCTS_BLOCK__
    </div>
  </section>
  <section id="about">
    <h2>About</h2>
    <p class="about">__ABOUT_TEXT__</p>
  </section>
  <section id="contact">
    <h2>Contact</h2>
    <div class="contact-box">__CONTACT_BLOCK__</div>
  </section>
  <footer>
    <p>__FOOTER_LINE__</p>
  </footer>
  <script src="app.js"></script>
</body>
</html>
"""


def _shop_copy() -> dict[str, str]:
    return {
        "PAGE_TITLE": "__BUSINESS_NAME__ — Shop",
        "META_DESCRIPTION": "Quality products and service.",
        "HERO_HEADLINE": "Everything you need, under one roof",
        "HERO_SUB": "Trusted local supply for hardware, agro inputs, and daily essentials.",
        "CATALOG_NAV": "Products",
        "CATALOG_TITLE": "Featured products",
        "ABOUT_TEXT": "We serve farmers, contractors, and households with dependable stock and fair pricing.",
    }


def _manufacturing_copy() -> dict[str, str]:
    return {
        "PAGE_TITLE": "__BUSINESS_NAME__ — Manufacturing",
        "META_DESCRIPTION": "Production capacity and quality assurance.",
        "HERO_HEADLINE": "Built for scale. Engineered for quality.",
        "HERO_SUB": "From raw material to finished goods — disciplined processes and on-time delivery.",
        "CATALOG_NAV": "Capabilities",
        "CATALOG_TITLE": "Capabilities & output",
        "ABOUT_TEXT": "Our facility focuses on repeatable quality, safety, and traceability across every batch.",
    }


def _services_copy() -> dict[str, str]:
    return {
        "PAGE_TITLE": "__BUSINESS_NAME__ — Services",
        "META_DESCRIPTION": "Professional services you can rely on.",
        "HERO_HEADLINE": "Expertise that moves your business forward",
        "HERO_SUB": "Consulting, implementation, and ongoing support tailored to your goals.",
        "CATALOG_NAV": "Services",
        "CATALOG_TITLE": "What we offer",
        "ABOUT_TEXT": "We combine domain knowledge with practical execution so outcomes land on time.",
    }


def get_template_bundle(template_type: str) -> dict[str, Any]:
    """Return ``html``, ``css``, ``js`` strings for a supported template."""
    t = (template_type or "shop").strip().lower()
    if t not in TEMPLATE_TYPES:
        _log.warning("unknown template %s, falling back to shop", template_type)
        t = "shop"
    copy = {"shop": _shop_copy, "manufacturing": _manufacturing_copy, "services": _services_copy}[t]()
    html = _HTML_SHELL
    for k, v in copy.items():
        html = html.replace(f"__{k}__", v)
    return {"template_type": t, "html": html, "css": _BASE_CSS.strip(), "js": _BASE_JS.strip()}
