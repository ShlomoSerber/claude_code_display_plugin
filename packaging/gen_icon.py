"""Render PNG fallbacks of the app icon (for launchers that don't read SVG).
Draws the same motif as icon.svg with Pillow. Usage: gen_icon.py <hicolor_dir>"""
import os
import sys

from PIL import Image, ImageDraw


def draw(size):
    S = 512
    # clean vertical gradient background through a rounded-rect mask
    top, bot = (31, 47, 57), (12, 19, 23)
    grad = Image.new("RGB", (1, S))
    for y in range(S):
        t = y / (S - 1)
        grad.putpixel((0, y), tuple(round(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
    grad = grad.resize((S, S))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([16, 16, 496, 496], radius=112, fill=255)
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    im.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(im)

    # monitor screen
    d.rounded_rectangle([104, 126, 408, 334], radius=22, fill=(230, 238, 242, 255))
    d.rounded_rectangle([104, 126, 408, 172], radius=22, fill=(201, 219, 226, 255))
    d.rectangle([104, 150, 408, 172], fill=(201, 219, 226, 255))
    d.ellipse([123, 141, 137, 155], fill=(156, 67, 16, 255))
    d.ellipse([147, 141, 161, 155], fill=(176, 193, 201, 255))
    # stand
    d.rectangle([234, 334, 278, 366], fill=(46, 67, 77, 255))
    d.rounded_rectangle([188, 362, 324, 384], radius=10, fill=(46, 67, 77, 255))
    # amber cursor 'driving' the screen
    cur = [(262, 196), (262, 322), (292, 292), (314, 340), (340, 328), (318, 282), (360, 282)]
    d.polygon(cur, fill=(245, 158, 11, 255))
    d.line(cur + [cur[0]], fill=(12, 19, 23, 255), width=8, joint="curve")

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
