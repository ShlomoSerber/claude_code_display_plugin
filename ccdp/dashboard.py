"""The display dashboard — a local web app to watch every managed display and to
gate/apply the Claude Code plugin. Live view is MJPEG streamed straight from the
X display (no VNC client library needed); x11vnc is offered per-surface for full
interactive control. Pure stdlib HTTP server.
"""
import io
import json
import os
import subprocess
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__, applyplugin, bugs, claudecli, paths, registry, sandbox, surfaces

PREVIEW_WIDTH = 720
STREAM_FPS = 3


def _state():
    surf = []
    for r in registry.all_surfaces().values():
        surf.append(dict(key=r["key"], project_dir=r.get("project_dir"), display=r.get("display"),
                         pss_mb=surfaces.pss_mb(r) if surfaces._alive(r) else 0,
                         vnc_port=r.get("vnc_port"), alive=surfaces._alive(r)))
    return dict(program="Claude Code Display Plugin", version=__version__,
                claude=dict(installed=claudecli.installed(), version=claudecli.version()),
                sandbox=sandbox.enabled(),
                plugin=applyplugin.status(),
                surfaces=surf, bugs=len(bugs.list_bugs()))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # quiet
        pass

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _asset(self, name):
        base = os.path.join(paths.ASSETS_DIR, "dashboard")
        path = os.path.normpath(os.path.join(base, name))
        if not path.startswith(base) or not os.path.isfile(path):
            return self._send(404, {"error": "not found"})
        ctype = {"html": "text/html", "css": "text/css", "js": "application/javascript"}.get(
            name.rsplit(".", 1)[-1], "application/octet-stream")
        with open(path, "rb") as f:
            self._send(200, f.read(), ctype)

    # ---- GET ----
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            return self._asset("index.html")
        if path.startswith("/static/"):
            return self._asset(path[len("/static/"):])
        if path == "/api/state":
            return self._send(200, _state())
        if path.startswith("/surface/") and path.endswith("/stream.mjpeg"):
            return self._mjpeg(path.split("/")[2])
        if path.startswith("/surface/") and path.endswith("/frame.png"):
            return self._frame(path.split("/")[2])
        return self._send(404, {"error": "not found"})

    # ---- POST ----
    def do_POST(self):
        path = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw) if raw else {}
        except ValueError:
            body = {}
        try:
            if path == "/api/apply-plugin":
                return self._send(200, applyplugin.apply())
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "surface":
                key, action = parts[2], parts[3]
                if action == "close":
                    surfaces.close(key)
                    return self._send(200, {"ok": True})
                if action == "open":
                    surfaces.open_url(key, body.get("url", "about:blank"))
                    return self._send(200, {"ok": True})
                if action == "vnc":
                    port = surfaces.start_vnc(key)
                    return self._send(200, {"ok": True, "port": port})
            return self._send(404, {"error": "not found"})
        except Exception as e:
            return self._send(500, {"error": str(e)})

    def _frame(self, key):
        rec = registry.get(key)
        if not rec or not surfaces._alive(rec):
            return self._send(404, {"error": "no such surface"})
        img = surfaces.screenshot_image(key)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        self._send(200, buf.getvalue(), "image/png")

    def _mjpeg(self, key):
        rec = registry.get(key)
        if not rec or not surfaces._alive(rec):
            return self._send(404, {"error": "no such surface"})
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        interval = 1.0 / STREAM_FPS
        try:
            while True:
                rec = registry.get(key)
                if not rec or not surfaces._alive(rec):
                    break
                img = surfaces.screenshot_image(key)
                if img.width > PREVIEW_WIDTH:
                    s = PREVIEW_WIDTH / img.width
                    img = img.resize((PREVIEW_WIDTH, round(img.height * s)))
                buf = io.BytesIO()
                img.convert("RGB").save(buf, "JPEG", quality=70)
                data = buf.getvalue()
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n"
                                 + f"Content-Length: {len(data)}\r\n\r\n".encode() + data + b"\r\n")
                self.wfile.flush()
                time.sleep(interval)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            pass


UI_PROFILE = os.path.join(paths.STATE_DIR, "ui-window")


def _open_window(url):
    """Open the dashboard as a standalone app window (chromium --app) so it looks
    and behaves like a real program rather than a browser tab. Returns True if an
    app window was launched, False on fallback to a normal browser tab."""
    browser = surfaces.find_browser()
    if browser:
        os.makedirs(UI_PROFILE, exist_ok=True)
        try:
            subprocess.Popen(
                [browser, f"--app={url}", "--class=ccdp", f"--user-data-dir={UI_PROFILE}",
                 "--window-size=1200,840", "--no-first-run", "--no-default-browser-check"],
                start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            pass
    try:
        webbrowser.open(url)
    except Exception:
        pass
    return False


def _window_open():
    """True while any browser process is using the dedicated UI profile — a robust
    way to track the app window's lifetime across Chrome's many child processes."""
    needle = UI_PROFILE.encode()
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/cmdline", "rb") as f:
                if needle in f.read():
                    return True
        except OSError:
            continue
    return False


def _watch_window(httpd):
    # wait for the window to actually appear, then quit when it's gone
    for _ in range(40):
        if _window_open():
            break
        time.sleep(0.3)
    misses = 0
    while True:
        time.sleep(1.5)
        misses = 0 if _window_open() else misses + 1
        if misses >= 2:
            httpd.shutdown()
            return


def serve(port=8776, open_browser=True):
    paths.ensure_dirs()
    url = f"http://127.0.0.1:{port}/"
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:
        # a dashboard is already running on this port — just surface a window at it
        print(f"Dashboard already running at {url}")
        if open_browser:
            _open_window(url)
        return
    print(f"Claude Code Display Plugin — dashboard at {url}")
    launched = _open_window(url) if open_browser else False
    if launched:
        # closing the app window quits the program, like a normal desktop app
        threading.Thread(target=_watch_window, args=(httpd,), daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()
