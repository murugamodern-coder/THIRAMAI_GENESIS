"""Legacy helper: extract triple-quoted prompts from a monolithic brain module into prompts_v1.md.

THIRAMAI v2 stores prompts in core/policies/prompts_v1.md; run this only if reviving an old single-file brain.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
text = (ROOT / "brain.py").read_text(encoding="utf-8")
pat = re.compile(
    r'^([A-Z][A-Z0-9_]*)\s*=\s*"""(.*?)"""',
    re.MULTILINE | re.DOTALL,
)
want_prefix = ("PROMPT_", "SYNTHESIS_", "SYSTEM_PROMPT_")
special = {
    "SEARCH_QUERY_SUMMARIZER_SYSTEM_PROMPT",
    "ANTI_REPEAT",
    "PLANNING_NOTE",
}
out_lines: list[str] = ["# THIRAMAI policy prompts v1 (generated from brain.py)\n"]
for m in pat.finditer(text):
    name, body = m.group(1), m.group(2)
    if not (
        name.startswith(want_prefix)
        or name in special
    ):
        continue
    out_lines.append(f"\n## {name}\n\n")
    out_lines.append(body.rstrip() + "\n")

out_path = ROOT / "core" / "policies" / "prompts_v1.md"
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text("".join(out_lines), encoding="utf-8")
print("Wrote", out_path, "sections:", len([l for l in out_lines if l.startswith("## ")]))
