"""Render PNG fallbacks of the app icon (for launchers that don't read SVG).

Matches icon.svg: a solid Claude-orange rounded square with a free cursor icon
(Material Design Icons "cursor-default", Apache-2.0) composited in the middle.
The cursor is pre-rasterised (white fill + black border) as cursor.png next to
this script, so this stays Pillow-only at build time.

Centering metric: the cursor is a diagonal arrow whose mass sits toward the
upper-left, so bounding-box centering looks left-heavy (dead space on the
right). We center on the **alpha-weighted centroid** (visual center of mass)
instead, which reads as balanced. Usage: gen_icon.py <hicolor_dir>
"""
import os
import sys

from PIL import Image, ImageDraw

ORANGE = (217, 119, 87, 255)   # Claude orange (#D97757)
HERE = os.path.dirname(os.path.abspath(__file__))
CURSOR_PNG = os.path.join(HERE, "cursor.png")
TARGET_H = 270                 # cursor height within the 512 canvas (~56% of the square)

_cursor = None                 # (image, centroid_x, centroid_y) cache


def _cursor_src():
    global _cursor
    if _cursor is None:
        im = Image.open(CURSOR_PNG).convert("RGBA")
        a = im.split()[3].load()
        w, h = im.size
        sx = sy = sw = 0.0
        for y in range(h):
            for x in range(w):
                p = a[x, y]
                if p:
                    sx += x * p; sy += y * p; sw += p
        _cursor = (im, sx / sw, sy / sw)
    return _cursor


def draw(size):
    S = 512
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle([16, 16, 496, 496], radius=112, fill=ORANGE)
    src, cx, cy = _cursor_src()
    s = TARGET_H / src.height
    cur = src.resize((round(src.width * s), TARGET_H), Image.LANCZOS)
    # place so the cursor's centroid lands at the canvas center
    im.alpha_composite(cur, (round(S / 2 - cx * s), round(S / 2 - cy * s)))
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
