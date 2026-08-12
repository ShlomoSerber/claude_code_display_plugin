"""OS-level input via xdotool — trusted events, indistinguishable from a physical
device (the whole point of the human-like-only channel). All input targets the
surface's private display; a per-surface lock serialises it so two sessions can't
fight over the one pointer.
"""
import contextlib
import fcntl
import os

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


def scroll(display, x, y, amount):
    button = "4" if amount < 0 else "5"  # 4 = up, 5 = down
    args = ["mousemove",str(int(x)), str(int(y))]
    for _ in range(min(abs(int(amount)), 50)):
        args += ["click", button]
    _xdo(display, args)


def type_text(display, text):
    _xdo(display, ["type", "--delay", "12", "--", text])


def key(display, keys):
    # keys like "ctrl+l", "Return", "Escape", "ctrl+a"
    _xdo(display, ["key", "--", keys])


def open_url(display, url):
    """Human-like navigation: focus the address bar and type the URL."""
    key(display, "ctrl+l")
    type_text(display, url)
    key(display, "Return")
