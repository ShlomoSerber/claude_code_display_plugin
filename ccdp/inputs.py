"""OS-level input via xdotool — trusted events, indistinguishable from a physical
device (the whole point of the human-like-only channel). All input targets the
surface's private display; a per-surface lock serialises it so two sessions can't
fight over the one pointer.

There is deliberately **no window manager** on these displays, so anything that
needs EWMH (`xdotool windowactivate`, `wmctrl`) does not work here. Window
focus/raise/resize go through the plain X calls (`windowfocus`, `windowraise`,
`windowsize`), which do work without a WM.
"""
import contextlib
import fcntl
import os
import time

from . import paths, util


@contextlib.contextmanager
def input_lock(key):
    paths.ensure_dirs()
    path = os.path.join(paths.RUNTIME_DIR, f"input-{key}.lock")
    f = open(path, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def _xdo(display, args, timeout=15):
    return util.run(["xdotool", *args], env=util.x_env(display), timeout=timeout)


def move(display, x, y):
    _xdo(display, ["mousemove",str(int(x)), str(int(y))])


def click(display, x, y, button=1):
    _xdo(display, ["mousemove",str(int(x)), str(int(y)), "click", str(button)])


def double_click(display, x, y, button=1):
    _xdo(display, ["mousemove",str(int(x)), str(int(y)),
                   "click", "--repeat", "2", "--delay", "80", str(button)])


# ---- press-and-hold gestures (drag-and-drop, moving/resizing a window) ----
# A press that outlives one call: `xdotool mousedown` leaves the button held in
# the X server after the process exits, so mouse_down/mouse_up bracket any number
# of moves and screenshots. Whoever presses must release — surfaces.py records the
# held buttons in the registry and recover() releases them.

def mouse_down(display, x=None, y=None, button=1):
    args = []
    if x is not None and y is not None:
        args += ["mousemove", str(int(x)), str(int(y)), "sleep", "0.05"]
    args += ["mousedown", str(int(button))]
    _xdo(display, args)


def mouse_up(display, x=None, y=None, button=1):
    args = []
    if x is not None and y is not None:
        args += ["mousemove", str(int(x)), str(int(y)), "sleep", "0.05"]
    args += ["mouseup", str(int(button))]
    _xdo(display, args)


def release_buttons(display, buttons=(1, 2, 3)):
    args = []
    for b in buttons:
        args += ["mouseup", str(int(b))]
    if args:
        _xdo(display, args)


def drag(display, x1, y1, x2, y2, button=1, steps=24, hold=0.12, settle=0.25):
    """Press at (x1,y1), travel to (x2,y2) in `steps` intermediate moves, release.

    The intermediate moves are the point: HTML5 drag-and-drop and pointermove
    gestures only fire dragover/dragenter when the pointer actually moves between
    the press and the release, so a single jump to the target drops nothing. The
    pause before the release lets the drop target's handlers run."""
    x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
    steps = max(2, min(int(steps), 200))
    args = ["mousemove", str(x1), str(y1), "sleep", "0.05",
            "mousedown", str(int(button)), "sleep", f"{max(0.0, float(hold)):.3f}"]
    for i in range(1, steps + 1):
        t = i / steps
        args += ["mousemove", str(round(x1 + (x2 - x1) * t)), str(round(y1 + (y2 - y1) * t)),
                 "sleep", "0.02"]
    args += ["sleep", f"{max(0.0, float(settle)):.3f}", "mouseup", str(int(button))]
    _xdo(display, args, timeout=int(20 + steps * 0.2))


def scroll(display, x, y, amount):
    button = "4" if amount < 0 else "5"  # 4 = up, 5 = down
    args = ["mousemove",str(int(x)), str(int(y))]
    for _ in range(min(abs(int(amount)), 50)):
        args += ["click", button]
    _xdo(display, args)


def type_text(display, text):
    _xdo(display, ["type", "--delay", "12", "--", text])


def key_sequence(keys):
    """Normalise a key argument into the list xdotool expects. Accepts a chord
    ('ctrl+l'), a whitespace-separated sequence ('ctrl+l Return'), or a list."""
    if isinstance(keys, (list, tuple)):
        seq = [str(k).strip() for k in keys]
    else:
        seq = str(keys).split()
    seq = [k for k in seq if k]
    if not seq:
        raise ValueError("no key given — e.g. 'Return', 'Escape', 'ctrl+l'")
    return seq


def key(display, keys):
    # keys like "ctrl+l", "Return", "Escape", "ctrl+a", or "ctrl+l Return"
    _xdo(display, ["key", "--", *key_sequence(keys)])


def open_url(display, url):
    """Human-like navigation: focus the address bar and type the URL."""
    key(display, "ctrl+l")
    type_text(display, url)
    key(display, "Return")


# ---- window plumbing (recovery: a stuck/obscured display, stale raster) ----
def window_ids(display):
    """Visible top-level windows on the display, in stacking order as reported."""
    rc, out, _ = _xdo(display, ["search", "--onlyvisible", "--name", ""])
    if rc != 0:
        return []
    return [ln.strip() for ln in out.splitlines() if ln.strip().isdigit()]


def _geometry(display, wid):
    rc, out, _ = _xdo(display, ["getwindowgeometry", "--shell", str(wid)])
    geo = {}
    if rc == 0:
        for ln in out.splitlines():
            if "=" in ln:
                k, _, v = ln.partition("=")
                geo[k.strip().lower()] = v.strip()
    def _n(k):
        try:
            return int(geo.get(k, ""))
        except ValueError:
            return None
    return dict(x=_n("x"), y=_n("y"), width=_n("width"), height=_n("height"))


def window_info(display, wid):
    name = _xdo(display, ["getwindowname", str(wid)])[1].strip()
    pid_out = _xdo(display, ["getwindowpid", str(wid)])[1].strip()
    info = dict(id=str(wid), name=name,
                pid=int(pid_out) if pid_out.isdigit() else None)
    info.update(_geometry(display, wid))
    return info


def windows(display, limit=12):
    return [window_info(display, wid) for wid in window_ids(display)[:limit]]


def focused_window(display):
    rc, out, _ = _xdo(display, ["getwindowfocus"])
    wid = out.strip()
    return wid if rc == 0 and wid.isdigit() else None


def focus_window(display, wid):
    """Raise and focus a window. No WM here, so these are the plain X calls."""
    _xdo(display, ["windowraise", str(wid)])
    _xdo(display, ["windowfocus", str(wid)])


def resize_window(display, wid, width, height):
    _xdo(display, ["windowsize", str(wid), str(int(width)), str(int(height))])


def move_window(display, wid, x, y):
    _xdo(display, ["windowmove", str(wid), str(int(x)), str(int(y))])


def repaint_window(display, wid, width, height, *, settle=0.35):
    """Force a full re-raster by nudging the window's size and putting it back.

    Chrome's compositor reuses previously rastered tile content; when that content
    goes stale (observed: a layer painting an old CSS custom-property value, fixed
    by changing the window geometry and surviving a hard reload) only a geometry
    change reliably repaints everything."""
    resize_window(display, wid, max(200, int(width) - 2), max(200, int(height) - 2))
    time.sleep(0.2)
    resize_window(display, wid, width, height)
    time.sleep(settle)
