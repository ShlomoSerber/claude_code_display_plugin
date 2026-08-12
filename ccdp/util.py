"""Small shared helpers: logging, subprocess, process liveness."""
import os
import subprocess
import sys
import time

from . import paths


def log(msg, *, component="ccdp"):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {component}: {msg}"
    print(line, file=sys.stderr, flush=True)
    try:
        paths.ensure_dirs()
        with open(os.path.join(paths.LOG_DIR, f"{component}.log"), "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def run(cmd, *, env=None, timeout=30, check=False, capture=True):
    """Run a command, return (rc, stdout, stderr)."""
    p = subprocess.run(cmd, env=env, timeout=timeout,
                       stdout=subprocess.PIPE if capture else None,
                       stderr=subprocess.PIPE if capture else None, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"{cmd!r} failed ({p.returncode}): {(p.stderr or '')[:300]}")
    return p.returncode, (p.stdout or ""), (p.stderr or "")


def pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def x_env(display):
    """Environment for X clients targeting our Xvfb — the key Wayland-host fix:
    scrub the compositor env so Chrome/x11vnc use the X display, not Wayland."""
    e = dict(os.environ, DISPLAY=display, XDG_SESSION_TYPE="x11")
    e.pop("WAYLAND_DISPLAY", None)
    return e


def terminate(pid, *, grace=3.0):
    if not pid_alive(pid):
        return
    try:
        os.kill(int(pid), 15)  # SIGTERM
    except OSError:
        return
    t0 = time.time()
    while time.time() - t0 < grace:
        if not pid_alive(pid):
            return
        time.sleep(0.1)
    try:
        os.kill(int(pid), 9)  # SIGKILL
    except OSError:
        pass
