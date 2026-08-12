"""Render PNG fallbacks of the app icon (for launchers that don't read SVG).
Matches icon.svg: a solid Claude-orange rounded square with a centered white
mouse cursor. Usage: gen_icon.py <hicolor_dir>"""
import os
import sys

from PIL import Image, ImageDraw

ORANGE = (217, 119, 87, 255)   # Claude orange (#D97757)
WHITE = (255, 255, 255, 255)
CURSOR = [(183, 148), (183, 337), (228, 292), (261, 364), (300, 346), (267, 277), (330, 277)]


def draw(size):
    S = 512
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([16, 16, 496, 496], radius=112, fill=ORANGE)
    d.polygon(CURSOR, fill=WHITE)
    d.line(CURSOR + [CURSOR[0]], fill=WHITE, width=10, joint="curve")  # white border
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
