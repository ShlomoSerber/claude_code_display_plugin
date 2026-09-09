"""Screen capture off a virtual display. Fast raw grab when python-mss is present
(~2 ms, measured), otherwise scrot (a declared package dependency). PIL is used
for encode/resize/diff — all validated in Phase 0.
"""
import io
import os
import subprocess
import tempfile

from . import util

try:
    from PIL import Image, ImageChops
    _HAVE_PIL = True
except Exception:  # pragma: no cover
    _HAVE_PIL = False


def grab(display, width, height):
    """Return a PIL RGB Image of the whole display."""
    # fast path: mss (raw grab, no encode)
    try:
        import mss
        os.environ["DISPLAY"] = display
        os.environ["XDG_SESSION_TYPE"] = "x11"
        os.environ.pop("WAYLAND_DISPLAY", None)
        with mss.mss() as sct:
            raw = sct.grab({"top": 0, "left": 0, "width": width, "height": height})
            return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    except Exception:
        pass
    # portable path: scrot to a temp file
    fd, path = tempfile.mkstemp(suffix=".png", prefix="ccdp_cap_")
    os.close(fd)
    try:
        util.run(["scrot", "-o", path], env=util.x_env(display), timeout=15)
        return Image.open(path).convert("RGB")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def png_bytes(img, *, max_width=None):
    """Encode a PIL image to PNG bytes, optionally downscaling to max_width.
    Returns (bytes, sent_width, sent_height, scale) so callers can map coords."""
    scale = 1.0
    if max_width and img.width > max_width:
        scale = max_width / img.width
        img = img.resize((max_width, round(img.height * scale)))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue(), img.width, img.height, scale


# ---- scroll-and-stitch (full-page capture) ----
# A full-page shot has to be assembled from several viewport captures, because the
# only channel here is pixels: there is no CDP/DOM to ask the renderer for the
# whole document. So we scroll, capture, and work out how far the page actually
# moved by matching the two frames — the scroll distance is not knowable up front
# (wheel step size varies by page, and a page can refuse to scroll at all).

def row_hashes(img, *, right_crop=0):
    """One hash per pixel row, for matching two captures of the same page.

    `right_crop` drops the scrollbar column: its thumb moves with every scroll, so
    including it makes every row differ and no shift ever matches.
    """
    w = max(1, img.width - max(0, int(right_crop)))
    band = img.crop((0, 0, w, img.height)) if w != img.width else img
    raw = band.convert("L").tobytes()
    stride = w
    return [hash(raw[i * stride:(i + 1) * stride]) for i in range(band.height)]


def find_shift(prev_rows, rows, *, min_overlap=80):
    """How far the page scrolled between two frames, in pixels, or None.

    `rows[i]` is the row that was at `prev_rows[i + d]` before the scroll, so we
    look for the `d` at which the two frames line up. The test is the longest
    *contiguous* run of matching rows, not the fraction that match: a sticky
    header or footer stays put while the page moves underneath it, so a real
    scroll always mismatches at one end, and a fraction test rejects it. A run of
    near-identical rows is rejected too — flat background lines up at every offset
    and would invent a scroll that never happened.

    Largest `d` first, because a page of repeating rows also lines up at smaller
    offsets and the big one is the scroll that actually happened.
    """
    n = len(rows)
    if n != len(prev_rows) or n <= min_overlap:
        return None
    for d in range(n - min_overlap, 0, -1):
        best = end = run = 0
        for i in range(n - d):
            run = run + 1 if prev_rows[i + d] == rows[i] else 0
            if run > best:
                best, end = run, i + 1
        if best >= min_overlap and len(set(rows[end - best:end])) >= 3:
            return d
    return None


def stack(images):
    """Join same-width images top to bottom into one tall image."""
    images = [im for im in images if im.height]
    if not images:
        return None
    if len(images) == 1:
        return images[0]
    out = Image.new("RGB", (images[0].width, sum(im.height for im in images)))
    y = 0
    for im in images:
        out.paste(im, (0, y))
        y += im.height
    return out


def solid_bbox(img, rgb, *, tol=24):
    """Bounding box of the largest region of colour `rgb`, or None.

    This is how the program measures itself: a calibration page paints its
    viewport one flat colour, and the box that colour occupies in the capture is
    the page area in screen pixels — measured, not assumed from a Chrome version's
    toolbar height.
    """
    r, g, b = rgb
    bands = img.split()
    mask = None
    for band, want in zip(bands, (r, g, b)):
        near = band.point(lambda v, w=want: 255 if abs(v - w) <= tol else 0)
        mask = near if mask is None else ImageChops.multiply(mask, near)
    return mask.getbbox() if mask else None


def changed_fraction(a, b):
    """Fraction of pixels that differ between two same-size PIL images (0..1)."""
    if a.size != b.size:
        return 1.0
    bbox = ImageChops.difference(a, b).getbbox()
    if not bbox:
        return 0.0
    area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
    return area / float(a.width * a.height)


def available():
    return _HAVE_PIL
