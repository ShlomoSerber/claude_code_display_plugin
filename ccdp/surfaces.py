"""Surface lifecycle: one sandboxed virtual display + browser per project
directory, shared by every session in that directory, created lazily and torn
down when idle. Processes are started detached so they outlive the ephemeral
MCP server that spawned them; the registry file is the shared source of truth.
"""
import hashlib
import os
import shlex
import shutil
import socket
import subprocess
import sys
import time

from . import capture, inputs, paths, registry, sandbox, util

NOVNC_DIR = os.environ.get("CCDP_NOVNC_DIR", "/usr/share/novnc")

WIDTH = int(os.environ.get("CCDP_WIDTH", "1280"))
HEIGHT = int(os.environ.get("CCDP_HEIGHT", "800"))
IDLE_REAP_S = int(os.environ.get("CCDP_IDLE_REAP_S", str(30 * 60)))

# Everything here is perceived by screenshotting the whole framebuffer, so the
# compositor's "only repaint what changed" optimisations are all downside: when
# they get the damage rect wrong we read stale pixels and believe them. The
# raster flags below trade a little redraw work for a framebuffer that always
# tells the truth (filed bug: a bar kept painting the *other* theme's CSS custom
# property value — deterministic by viewport width, surviving a hard reload).
CHROME_FLAGS = [
    "--ozone-platform=x11", "--disable-gpu",
    f"--window-size={WIDTH},{HEIGHT}", "--window-position=0,0",
    "--no-first-run", "--no-default-browser-check",
    "--disable-background-networking", "--password-store=basic",
    "--disable-features=Translate,TranslateUI",
    "--disable-partial-raster",      # never reuse a tile's previous content
    "--disable-checker-imaging",     # no placeholder-then-fix-up image raster
    "--ui-disable-partial-swap",     # browser UI: always swap the full frame
]


def extra_browser_flags():
    """Opt-in extra flags for the managed browser, from the environment.

    The browser otherwise talks to the network directly, which leaves out any app
    whose backend only exists behind a tunnel or VPN (filed feedback: an API
    reachable solely through a SOCKS5 tunnel, with remote DNS). A second browser
    of your own is not an option — these displays have no window manager, so a
    second Chrome starts but never maps a window.

    - `CCDP_PROXY=socks5://127.0.0.1:1080` — proxy every request. For a SOCKS
      proxy it also forces DNS through the tunnel (Chrome resolves locally
      otherwise, which fails for names that only exist on the far side), while
      leaving localhost resolving normally.
    - `CCDP_BROWSER_FLAGS="--flag=a --flag=b"` — appended verbatim, shell-quoted.

    Both are read when the display is created; the flags are stored on the surface
    record so a later relaunch or recover() keeps them.
    """
    flags = []
    proxy = (os.environ.get("CCDP_PROXY") or "").strip()
    if proxy:
        flags.append(f"--proxy-server={proxy}")
        if proxy.lower().startswith("socks"):
            # Resolve names through the tunnel, not locally, and keep localhost local.
            # --test-type only suppresses Chrome's "unsupported command-line flag"
            # infobar: that bar pushes the page down ~44px and would silently break
            # the 1:1 pixel contract between a screenshot and a click.
            flags += ["--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE localhost", "--test-type"]
    extra = (os.environ.get("CCDP_BROWSER_FLAGS") or "").strip()
    if extra:
        try:
            flags += shlex.split(extra)
        except ValueError as e:
            util.log(f"ignoring CCDP_BROWSER_FLAGS ({e}): {extra!r}", component="surfaces")
    return flags


# Chrome refuses to reuse a profile whose singleton lock looks live; after a hard
# kill these can linger and block the relaunch in recover().
_SINGLETON_FILES = ("SingletonLock", "SingletonCookie", "SingletonSocket")


class SurfaceError(RuntimeError):
    pass


def find_browser():
    for b in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        p = shutil.which(b)
        if p:
            return p
    return None


def _free_display():
    used = registry.used_displays()
    for n in range(101, 200):
        disp = f":{n}"
        if disp in used:
            continue
        if os.path.exists(f"/tmp/.X{n}-lock"):
            continue
        return disp
    raise SurfaceError("no free X display number found")


def _wait_display(display, timeout=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        rc, _, _ = util.run(["xdpyinfo"], env=util.x_env(display), timeout=5)
        if rc == 0:
            return True
        time.sleep(0.3)
    return False


def _spawn(cmd, env, logname):
    paths.ensure_dirs()
    logf = open(os.path.join(paths.LOG_DIR, logname), "ab")
    p = subprocess.Popen(cmd, env=env, stdout=logf, stderr=logf,
                         start_new_session=True, close_fds=True)
    return p.pid


def _alive(rec):
    return bool(rec) and util.pid_alive(rec.get("xvfb_pid")) and util.pid_alive(rec.get("chrome_pid"))


def _port_listening(port, host="127.0.0.1"):
    s = socket.socket()
    s.settimeout(0.4)
    try:
        s.connect((host, int(port)))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _wait_port(port, timeout=8):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if _port_listening(port):
            return True
        time.sleep(0.2)
    return False


def _clear_singleton(profile):
    for name in _SINGLETON_FILES:
        p = os.path.join(profile, name)
        try:
            os.remove(p)
        except OSError:
            pass


def _launch_browser(browser, profile, project_dir, display, url, flags=None):
    os.makedirs(profile, exist_ok=True)
    _clear_singleton(profile)
    flags = list(flags if flags is not None else extra_browser_flags())
    if flags:
        util.log(f"browser on {display} gets extra flags: {' '.join(flags)}", component="surfaces")
    cmd = [browser, *CHROME_FLAGS, *flags, f"--user-data-dir={profile}", url or "about:blank"]
    cmd = sandbox.wrap(cmd, profile_dir=profile, project_dir=os.path.realpath(project_dir),
                       display=display)
    return _spawn(cmd, util.x_env(display), f"chrome{display[1:]}.log")


def ensure(project_dir, *, url=None):
    """Return a live surface record for project_dir, creating it if needed."""
    key = paths.project_key(project_dir)
    rec = registry.get(key)
    if _alive(rec):
        registry.touch(key)
        if url:
            open_url(key, url)
        return rec
    if rec:
        # Half-dead surface (e.g. the browser crashed but Xvfb is still up): tear
        # the remains down, or they leak an X server and a display number for the
        # rest of the login session.
        util.log(f"surface {key} on {rec.get('display')} was half-dead — cleaning up before recreating",
                 component="surfaces")
        close(key)

    browser = find_browser()
    if not browser:
        raise SurfaceError("no Chrome/Chromium found — install google-chrome-stable or chromium")

    display = _free_display()
    disp_n = display[1:]
    xvfb_pid = _spawn(["Xvfb", display, "-screen", "0", f"{WIDTH}x{HEIGHT}x24", "-nolisten", "tcp"],
                      dict(os.environ), f"xvfb{disp_n}.log")
    if not _wait_display(display):
        util.terminate(xvfb_pid)
        raise SurfaceError(f"Xvfb {display} did not come up")

    profile = paths.profile_dir(key)
    flags = extra_browser_flags()
    chrome_pid = _launch_browser(browser, profile, project_dir, display, url, flags)

    rec = registry.upsert(key, dict(
        key=key, project_dir=os.path.realpath(project_dir), display=display,
        xvfb_pid=xvfb_pid, chrome_pid=chrome_pid, vnc_port=None, browser=browser,
        browser_flags=flags,
        width=WIDTH, height=HEIGHT, created=time.time(), last_active=time.time(),
        last_url=url, input_seq=0, frame_seq=0, frame_hash=None))
    util.log(f"created surface {key} on {display} for {project_dir}", component="surfaces")
    time.sleep(2.0)  # let the browser paint
    return rec


def _require(key):
    rec = registry.get(key)
    if not _alive(rec):
        raise SurfaceError(f"surface {key} is not running")
    registry.touch(key)
    return rec


# ---- perception ----
def _digest(img):
    return hashlib.blake2b(img.tobytes(), digest_size=8).hexdigest()


def _note_frame(key, rec, img):
    """Track whether the display is actually *changing*.

    Returns the number of inputs sent since the last frame that looked different.
    A display that has swallowed several inputs without a single pixel moving is
    stuck (filed bug: after a popup/menu interaction the display froze — clicks,
    keys and open_url all silently did nothing while screenshots kept returning
    the same frame), and the caller can say so instead of acting blind."""
    dig = _digest(img)
    seq = int(rec.get("input_seq") or 0)
    if dig != rec.get("frame_hash"):
        registry.upsert(key, dict(frame_hash=dig, frame_seq=seq, frame_changed=time.time()))
        return 0
    return max(0, seq - int(rec.get("frame_seq") or 0))


def screenshot_image(key, *, track=False):
    rec = _require(key)
    img = capture.grab(rec["display"], rec["width"], rec["height"])
    if track:
        return img, _note_frame(key, rec, img)
    return img


def screenshot_png(key, *, max_width=None, track=False):
    """Returns (png, width, height, scale) — plus, with track=True, the count of
    inputs that have produced no visible change."""
    if track:
        img, stale = screenshot_image(key, track=True)
        return capture.png_bytes(img, max_width=max_width) + (stale,)
    return capture.png_bytes(screenshot_image(key), max_width=max_width)


# ---- actuation ----
def _bump_input(key, rec):
    registry.upsert(key, dict(input_seq=int(rec.get("input_seq") or 0) + 1))


def open_url(key, url):
    rec = _require(key)
    with inputs.input_lock(key):
        inputs.open_url(rec["display"], url)
    registry.upsert(key, dict(last_url=url))
    _bump_input(key, rec)


def click(key, x, y, button=1, double=False):
    rec = _require(key)
    with inputs.input_lock(key):
        (inputs.double_click if double else inputs.click)(rec["display"], x, y, button)
    _bump_input(key, rec)


def move(key, x, y):
    # Not counted as input for stuck-detection: captures carry no cursor, so a
    # bare pointer move legitimately changes nothing on screen.
    rec = _require(key)
    with inputs.input_lock(key):
        inputs.move(rec["display"], x, y)


def _held(rec):
    try:
        return [int(b) for b in (rec.get("buttons_down") or [])]
    except (TypeError, ValueError):
        return []


def mouse_down(key, x, y, button=1):
    """Press and hold. The button stays down across later calls, so screenshots
    taken mid-gesture show drag guides, hover highlights and drop targets."""
    rec = _require(key)
    with inputs.input_lock(key):
        inputs.mouse_down(rec["display"], x, y, button)
    registry.upsert(key, dict(buttons_down=sorted(set(_held(rec)) | {int(button)})))
    _bump_input(key, rec)


def mouse_up(key, x=None, y=None, button=1):
    rec = _require(key)
    with inputs.input_lock(key):
        inputs.mouse_up(rec["display"], x, y, button)
    registry.upsert(key, dict(buttons_down=[b for b in _held(rec) if b != int(button)]))
    _bump_input(key, rec)


def drag(key, x1, y1, x2, y2, button=1, steps=24):
    rec = _require(key)
    with inputs.input_lock(key):
        inputs.drag(rec["display"], x1, y1, x2, y2, button=button, steps=steps)
    registry.upsert(key, dict(buttons_down=[b for b in _held(rec) if b != int(button)]))
    _bump_input(key, rec)


def scroll(key, x, y, amount):
    rec = _require(key)
    with inputs.input_lock(key):
        inputs.scroll(rec["display"], x, y, amount)
    _bump_input(key, rec)


def type_text(key, text):
    rec = _require(key)
    with inputs.input_lock(key):
        inputs.type_text(rec["display"], text)
    _bump_input(key, rec)


def press_key(key, keys):
    rec = _require(key)
    with inputs.input_lock(key):
        inputs.key(rec["display"], keys)
    _bump_input(key, rec)


# ---- recovery ----
def _main_window(display, chrome_pid, wins):
    """The browser's main window: the biggest visible one belonging to the browser
    process tree (a stray popup or menu window is smaller and usually on top).
    The display also carries unnamed, unowned X windows the size of the screen —
    never focus one of those, or input goes nowhere."""
    pids = set(descendants(chrome_pid)) if chrome_pid else set()
    def area(w):
        return (w.get("width") or 0) * (w.get("height") or 0)
    owned = [w for w in wins if w.get("pid") in pids]
    candidates = owned or [w for w in wins if w.get("name")] or wins
    return max(candidates, key=area) if candidates else None


def recover(key, *, restart_browser=False):
    """Unstick a display, escalating as needed. Returns a report of what it did.

    Order matters: dismiss anything modal, put focus back on the browser's main
    window (no WM here, so a popup can quietly keep both focus and the top of the
    stack), force a full repaint, and only restart the browser if asked — that
    loses page state, so it's the last resort."""
    rec = registry.get(key)
    if not rec:
        raise SurfaceError(f"no surface {key} — call screenshot or open_url to create one")
    display, steps = rec["display"], []

    if not util.pid_alive(rec.get("xvfb_pid")):
        close(key)
        raise SurfaceError("the display's X server is gone — the surface was cleaned up; "
                           "call open_url or screenshot to create a fresh one")

    chrome_dead = not util.pid_alive(rec.get("chrome_pid"))
    if chrome_dead or restart_browser:
        steps.append("browser was not running" if chrome_dead else "restarting the browser")
        util.terminate(rec.get("chrome_pid"))
        pid = _launch_browser(rec.get("browser") or find_browser(), paths.profile_dir(key),
                              rec.get("project_dir") or os.getcwd(), display,
                              rec.get("last_url") or "about:blank",
                              rec.get("browser_flags"))
        registry.upsert(key, dict(chrome_pid=pid))
        time.sleep(2.5)
        steps.append(f"relaunched the browser (pid {pid}) at {rec.get('last_url') or 'about:blank'}")
        rec = registry.get(key)

    with inputs.input_lock(key):
        held = _held(rec)
        if held:
            # A mouse_down without its mouse_up wedges everything: the pointer
            # stays captured, so clicks land on the dragging widget, not the page.
            inputs.release_buttons(display, held)
            registry.upsert(key, dict(buttons_down=[]))
            steps.append("released mouse button(s) " + ", ".join(str(b) for b in held)
                         + " that were still held down from an unfinished drag")
        inputs.key(display, "Escape")
        steps.append("sent Escape to dismiss any open menu or dialog")
        wins = inputs.windows(display)
        focused = inputs.focused_window(display)
        main = _main_window(display, rec.get("chrome_pid"), wins)
        if main:
            extra = [w for w in wins if w["id"] != main["id"]]
            if extra:
                steps.append("other windows are on this display: "
                             + "; ".join(f"{w['name'] or '(unnamed)'} "
                                         f"{w.get('width')}x{w.get('height')}" for w in extra))
            if focused != main["id"]:
                steps.append(f"focus was on window {focused or 'nothing'} — moved it to the browser")
            inputs.focus_window(display, main["id"])
            steps.append("raised and focused the browser's main window")
            inputs.repaint_window(display, main["id"],
                                  main.get("width") or rec.get("width", WIDTH),
                                  main.get("height") or rec.get("height", HEIGHT))
            steps.append("forced a full repaint")
        else:
            steps.append("found no window on the display to focus")
    registry.upsert(key, dict(frame_hash=None, frame_seq=int(rec.get("input_seq") or 0)))
    registry.touch(key)
    util.log(f"recovered surface {key}: {' | '.join(steps)}", component="surfaces")
    return dict(key=key, display=display, steps=steps,
                windows=wins, restarted=bool(chrome_dead or restart_browser))


# ---- human observability: VNC + a noVNC web control panel ----
def start_vnc(key):
    rec = _require(key)
    if rec.get("vnc_port") and util.pid_alive(rec.get("vnc_pid")) and _port_listening(rec["vnc_port"]):
        return rec["vnc_port"]
    port = 5900 + int(rec["display"][1:])
    pid = _spawn(["x11vnc", "-display", rec["display"], "-localhost", "-rfbport", str(port),
                  "-nopw", "-forever", "-shared", "-noxdamage", "-quiet"],
                 util.x_env(rec["display"]), f"vnc{rec['display'][1:]}.log")
    registry.upsert(key, dict(vnc_port=port, vnc_pid=pid))
    _wait_port(port)  # so callers (websockify) find it ready
    return port


def _websockify_cmd():
    override = os.environ.get("CCDP_WEBSOCKIFY")
    if override:
        return override.split()
    if shutil.which("websockify"):
        return ["websockify"]
    return [sys.executable, "-m", "websockify"]


def start_control(key):
    """Start (or reuse) a noVNC web panel that gives full interactive control of
    the surface: x11vnc on the display, websockify bridging it to a WebSocket and
    serving the noVNC client. Returns the local URL to embed."""
    rec = _require(key)
    vncport = start_vnc(key)
    if rec.get("ws_port") and util.pid_alive(rec.get("ws_pid")) and _port_listening(rec["ws_port"]):
        return _novnc_url(rec["ws_port"])
    wsport = 6100 + int(rec["display"][1:])
    if not os.path.isdir(NOVNC_DIR):
        raise SurfaceError(f"noVNC not found at {NOVNC_DIR} — install the 'novnc' package")
    cmd = _websockify_cmd() + ["--web", NOVNC_DIR, f"127.0.0.1:{wsport}", f"localhost:{vncport}"]
    pid = _spawn(cmd, dict(os.environ), f"ws{rec['display'][1:]}.log")
    registry.upsert(key, dict(ws_port=wsport, ws_pid=pid))
    _wait_port(wsport)
    return _novnc_url(wsport)


def _novnc_url(wsport):
    return (f"http://127.0.0.1:{wsport}/vnc.html"
            "?autoconnect=true&resize=scale&reconnect=true&show_dot=true")


def stop_vnc(key):
    rec = registry.get(key)
    if not rec:
        return
    for p in ("ws_pid", "vnc_pid"):
        if rec.get(p):
            util.terminate(rec[p])
    registry.upsert(key, dict(vnc_port=None, vnc_pid=None, ws_port=None, ws_pid=None))


# ---- teardown & housekeeping ----
def close(key, *, purge_profile=False):
    rec = registry.get(key)
    if not rec:
        return
    for p in ("ws_pid", "vnc_pid", "chrome_pid", "xvfb_pid"):
        util.terminate(rec.get(p))
    registry.remove(key)
    if purge_profile:
        shutil.rmtree(paths.profile_dir(key), ignore_errors=True)
    util.log(f"closed surface {key}", component="surfaces")


def reap_idle(max_idle_s=IDLE_REAP_S):
    now = time.time()
    for key, rec in list(registry.all_surfaces().items()):
        if not _alive(rec):
            registry.remove(key)
            continue
        if now - rec.get("last_active", now) > max_idle_s:
            close(key)


def descendants(pid):
    """Every process in a surface's tree. `/proc/<pid>/task/<tid>/children` is a
    *file* of space-separated pids — reading it as a directory silently yielded
    only the process itself, which made pss_mb report the browser process alone
    and miss every renderer (i.e. most of the memory)."""
    out, stack, seen = [], [int(pid)], set()
    while stack:
        p = stack.pop()
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
        kids = []
        try:
            for tid in os.listdir(f"/proc/{p}/task"):
                try:
                    with open(f"/proc/{p}/task/{tid}/children") as f:
                        kids += f.read().split()
                except OSError:
                    continue
        except OSError:
            pass
        for k in kids:
            try:
                stack.append(int(k))
            except ValueError:
                continue
    return out


def pss_mb(rec):
    total = 0
    pids = set()
    for base in ("xvfb_pid", "chrome_pid", "vnc_pid", "ws_pid"):
        if rec.get(base):
            pids.update(descendants(rec[base]))
    for pid in pids:
        try:
            with open(f"/proc/{pid}/smaps_rollup") as f:
                for line in f:
                    if line.startswith("Pss:"):
                        total += int(line.split()[1]); break
        except OSError:
            continue
    return round(total / 1024.0, 1)
