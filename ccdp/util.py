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
    """Environment for X clients targeting our Xvfb — keeps the virtual display a
    self-contained world instead of borrowing the host session. Two isolations:

    * Wayland-host fix: scrub the compositor env so Chrome/x11vnc use the X
      display, not Wayland (otherwise black captures / x11vnc refuses to start).
    * Audio isolation: the display is perceived purely as pixels — screenshots
      and VNC carry no audio — so a sandboxed app has no legitimate place to send
      sound. Detached apps otherwise inherit the host's PulseAudio/PipeWire
      sockets and leak page audio straight to the human's speakers (the
      "water-drip" noise). Point the audio-server vars at dead sockets so the
      display simply has no sound card, for every app on it, not just the browser.
    * D-Bus isolation: the host's session bus is the third inherited channel out
      of the sandbox, and the one that broke file uploads (filed feedback: the
      file picker never appeared, so no upload flow could be completed). With a
      bus, Chrome asks xdg-desktop-portal for the file chooser — a service running
      in the *human's* session, whose dialog therefore never reaches the virtual
      display. Cut the bus and Chrome draws its own GTK chooser on the display,
      where it can be seen and driven. GTK_USE_PORTAL=0 says so up front instead
      of waiting for a D-Bus call to time out.
    """
    e = dict(os.environ, DISPLAY=display, XDG_SESSION_TYPE="x11")
    e.pop("WAYLAND_DISPLAY", None)
    # No session bus in this sandbox: keep dialogs on this display, not the host's.
    for var in ("DBUS_SESSION_BUS_ADDRESS", "DBUS_SESSION_BUS_PID",
                "DBUS_STARTER_ADDRESS", "DBUS_STARTER_BUS_TYPE"):
        e.pop(var, None)
    e["GTK_USE_PORTAL"] = "0"
    # No sound card in this sandbox: sever the host audio servers. An explicit
    # (dead) PULSE_SERVER also stops the client from autospawning its own daemon.
    e["PULSE_SERVER"] = "unix:/nonexistent/ccdp-no-audio"
    e["PIPEWIRE_REMOTE"] = "ccdp-no-audio"
    e.pop("PULSE_SINK", None)
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
