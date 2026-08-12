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
