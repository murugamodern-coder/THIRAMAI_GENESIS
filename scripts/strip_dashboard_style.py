import re
from pathlib import Path

p = Path("templates/dashboard.html")
text = p.read_text(encoding="utf-8")
replacement = """  <link rel="stylesheet" href="/public/css/enterprise-theme.css"/>
  <link rel="stylesheet" href="/public/css/dashboard-layout.css"/>
"""
text2, n = re.subn(r"<style>.*?</style>\s*", replacement, text, count=1, flags=re.DOTALL)
if n != 1:
    raise SystemExit(f"expected 1 style block, replaced {n}")
p.write_text(text2, encoding="utf-8")
print("stripped style block, wrote dashboard.html")
