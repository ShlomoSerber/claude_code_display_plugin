"""Render PNG fallbacks of the app icon (for launchers that don't read SVG).

Matches icon.svg: a solid Claude-orange rounded square with a free cursor icon
(Material Design Icons "cursor-default", Apache-2.0) composited in the middle.
The cursor is pre-rasterised (white fill + black border) as cursor.png next to
this script, so this stays Pillow-only at build time. Usage: gen_icon.py <hicolor_dir>
"""
import os
import sys

from PIL import Image, ImageDraw

ORANGE = (217, 119, 87, 255)   # Claude orange (#D97757)
HERE = os.path.dirname(os.path.abspath(__file__))
CURSOR_PNG = os.path.join(HERE, "cursor.png")
TARGET_H = 300                 # cursor height within the 512 canvas (~62% of the square)


def draw(size):
    S = 512
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([16, 16, 496, 496], radius=112, fill=ORANGE)
    cur = Image.open(CURSOR_PNG).convert("RGBA")
    w = round(cur.width * TARGET_H / cur.height)
    cur = cur.resize((w, TARGET_H), Image.LANCZOS)
    im.alpha_composite(cur, ((S - w) // 2, (S - TARGET_H) // 2))
    if size != S:
        im = im.resize((size, size), Image.LANCZOS)
    return im


def main():
    base = sys.argv[1]
    for size in (48, 128, 256, 512):
        out = os.path.join(base, f"{size}x{size}", "apps")
        os.makedirs(out, exist_ok=True)
        draw(size).save(os.path.join(out, "ccdp.png"))
    print("icons written under", base)


if __name__ == "__main__":
    main()
