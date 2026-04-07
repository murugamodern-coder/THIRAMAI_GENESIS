import re
from pathlib import Path

p = Path("templates/dashboard.html")
text = p.read_text(encoding="utf-8")
m = re.search(r"<style>(.*?)</style>", text, re.DOTALL)
if not m:
    raise SystemExit("no style block")
css = m.group(1)

new_root = """    :root {
      --bg: #f5f6f7;
      --bg-elevated: #ffffff;
      --bg-mid: #f0f4f8;
      --slate: #6a6d70;
      --card: #ffffff;
      --card-solid: #ffffff;
      --text: #32363a;
      --muted: #6a6d70;
      --border: #d9d9d9;
      --accent: #0064d9;
      --accent-hover: #0052b3;
      --accent-dim: rgba(0, 100, 217, 0.08);
      --cta: #e9730c;
      --cta-hover: #d96500;
      --cta-dim: rgba(233, 115, 12, 0.12);
      --neon-cyan: #0064d9;
      --neon-orange: #e9730c;
      --neon-magenta: #bb0000;
      --glass-blur: none;
      --shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
      --radius: 4px;
      --glow: none;
      --glow-hover: 0 2px 8px rgba(0, 0, 0, 0.08);
      --font-cockpit: "72", "72full", Arial, Helvetica, sans-serif;
    }"""

css = re.sub(r":root\s*\{[^}]*\}", new_root, css, count=1, flags=re.DOTALL)

body_new = """    body {
      margin: 0;
      min-height: 100vh;
      font-family: var(--font-cockpit);
      background: var(--bg);
      color: var(--text);
      font-size: 13px;
      line-height: 1.5;
      -webkit-font-smoothing: antialiased;
    }"""
css = re.sub(r"body\s*\{[^}]*\}", body_new, css, count=1, flags=re.DOTALL)

css = css.replace("color: #b8c5d6;", "color: var(--text);")

out = Path("static/css/dashboard-layout.css")
out.write_text("/* Extracted from dashboard — enterprise light tokens */\n" + css, encoding="utf-8")
print("wrote", out, "chars", len(css))
