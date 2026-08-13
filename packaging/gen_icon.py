"""Render PNG fallbacks of the app icon (for launchers that don't read SVG).
Matches icon.svg: a solid Claude-orange rounded square with a centered white
mouse cursor. Usage: gen_icon.py <hicolor_dir>"""
import os
import sys

from PIL import Image, ImageDraw

ORANGE = (217, 119, 87, 255)   # Claude orange (#D97757)
WHITE = (255, 255, 255, 255)
BLACK = (0, 0, 0, 255)
# Canonical arrow cursor, bounding-box centered in the 512 square:
# vertical left edge, 45deg notch, 45deg top edge, a true parallelogram tail (no taper).
CURSOR = [(168, 112), (168, 368), (232, 304), (280, 400), (312, 384), (264, 288), (344, 288)]


def draw(size):
    S = 512
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([16, 16, 496, 496], radius=112, fill=ORANGE)
    d.polygon(CURSOR, fill=WHITE)
    d.line(CURSOR + [CURSOR[0]], fill=BLACK, width=12, joint="curve")  # black border
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
