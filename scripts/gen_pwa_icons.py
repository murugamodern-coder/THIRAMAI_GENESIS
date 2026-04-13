"""Generate THIRAMAI PWA icons (dark blue + white T). Run from repo root: python scripts/gen_pwa_icons.py"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "command_center" / "public"
BG = (15, 17, 23)  # #0f1117


def draw_t(size: int) -> Image.Image:
    img = Image.new("RGB", (size, size), BG)
    draw = ImageDraw.Draw(img)
    # Bold "T" — try Arial/DejaVu, fallback to polygon
    font_size = int(size * 0.62)
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except OSError:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
        except OSError:
            font = ImageFont.load_default()
    text = "T"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (size - tw) // 2
    y = (size - th) // 2 - int(size * 0.04)
    draw.text((x, y), text, fill=(255, 255, 255), font=font)
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    draw_t(192).save(OUT / "thiramai-icon-192.png", "PNG")
    draw_t(512).save(OUT / "thiramai-icon-512.png", "PNG")
    print("Wrote", OUT / "thiramai-icon-192.png", OUT / "thiramai-icon-512.png")


if __name__ == "__main__":
    main()
