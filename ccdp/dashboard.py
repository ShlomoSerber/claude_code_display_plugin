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
from urllib.parse import parse_qs, urlparse

from . import (__version__, applyplugin, claudecli, paths, registry, reports, sandbox,
               surfaces, util)

PREVIEW_WIDTH = 720
STREAM_FPS = 3


def _state():
    surf = []
    for r in registry.all_surfaces().values():
        surf.append(dict(key=r["key"], project_dir=r.get("project_dir"), display=r.get("display"),
                         label=r.get("label"), url=r.get("last_url"), session=r.get("session"),
                         width=r.get("width", 1280), height=r.get("height", 800),
                         pss_mb=surfaces.pss_mb(r) if surfaces._alive(r) else 0,
                         vnc_port=r.get("vnc_port"), alive=surfaces._alive(r)))
    surf.sort(key=lambda s: (s["project_dir"] or "", s["key"]))
    return dict(program="Claude Code Display Plugin", version=__version__,
                max_displays=surfaces.MAX_DISPLAYS,
                claude=dict(installed=claudecli.installed(), version=claudecli.version()),
                sandbox=sandbox.enabled(),
                plugin=applyplugin.status(),
                surfaces=surf, reports=reports.counts())


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
        ctype = {"html": "text/html", "css": "text/css", "js": "application/javascript",
                 "svg": "image/svg+xml", "png": "image/png", "ico": "image/x-icon"}.get(
            name.rsplit(".", 1)[-1], "application/octet-stream")
        with open(path, "rb") as f:
            self._send(200, f.read(), ctype)

    # ---- GET ----
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            return self._asset("index.html")
        if path.startswith("/static/"):
            return self._asset(path[len("/static/"):])
        if path == "/api/state":
            return self._send(200, _state())
        if path == "/api/reports":
            q = parse_qs(parsed.query)
            kind = (q.get("kind") or ["all"])[0]
            if kind == "all":
                return self._send(200, {"reports": reports.all_reports(100)})
            try:
                return self._send(200, {"reports": reports.store(kind).list(100)})
            except ValueError as e:
                return self._send(400, {"error": str(e)})
        if path.startswith("/surface/") and path.endswith("/stream.mjpeg"):
            q = parse_qs(parsed.query)
            try:
                w = int(q.get("w", [PREVIEW_WIDTH])[0])
            except ValueError:
                w = PREVIEW_WIDTH
            return self._mjpeg(path.split("/")[2], width=w)
        if path.startswith("/surface/") and path.endswith("/frame.png"):
            q = parse_qs(parsed.query)
            w = None
            if q.get("w"):
                try:
                    w = int(q["w"][0])
                except ValueError:
                    w = None
            return self._frame(path.split("/")[2], width=w)
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
            if path == "/api/remove-plugin":
                return self._send(200, applyplugin.remove())
            parts = path.strip("/").split("/")
            # /api/reports/<kind>/<id>/archive — dismiss, keeping the file
            if len(parts) == 5 and parts[:2] == ["api", "reports"] and parts[4] == "archive":
                try:
                    ok = reports.store(parts[2]).archive(parts[3])
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
                return self._send(200 if ok else 404, {"ok": ok})
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "surface":
                key, action = parts[2], parts[3]
                key = surfaces.resolve(key)
                if action == "close":
                    surfaces.close(key)
                    return self._send(200, {"ok": True})
                if action == "open":
                    surfaces.open_url(key, body.get("url", "about:blank"))
                    return self._send(200, {"ok": True})
                if action == "input":
                    a = body.get("action")
                    if a == "click":
                        surfaces.click(key, body["x"], body["y"],
                                       body.get("button", 1), bool(body.get("double")))
                    elif a == "scroll":
                        surfaces.scroll(key, body["x"], body["y"], int(body.get("amount", 1)))
                    elif a == "type":
                        surfaces.type_text(key, body.get("text", ""))
                    elif a == "key" and body.get("keys"):
                        surfaces.press_key(key, body["keys"])
                    return self._send(200, {"ok": True})
                if action == "recover":
                    return self._send(200, dict(ok=True, **surfaces.recover(
                        key, restart_browser=bool(body.get("restart_browser")))))
                if action == "control":
                    url = surfaces.start_control(key)
                    return self._send(200, {"ok": True, "url": url})
            return self._send(404, {"error": "not found"})
        except Exception as e:
            return self._send(500, {"error": str(e)})

    def _frame(self, key, width=None):
        rec = registry.get(key)
        if not rec or not surfaces._alive(rec):
            return self._send(404, {"error": "no such surface"})
        img = surfaces.screenshot_image(key)
        if width:
            width = max(240, min(int(width), img.width))
            if img.width > width:
                s = width / img.width
                img = img.resize((width, round(img.height * s)))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=75)
        self._send(200, buf.getvalue(), "image/jpeg")

    def _mjpeg(self, key, width=PREVIEW_WIDTH):
        rec = registry.get(key)
        if not rec or not surfaces._alive(rec):
            return self._send(404, {"error": "no such surface"})
        width = max(240, min(int(width), rec.get("width", PREVIEW_WIDTH)))
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
                if img.width > width:
                    s = width / img.width
                    img = img.resize((width, round(img.height * s)))
                buf = io.BytesIO()
                img.convert("RGB").save(buf, "JPEG", quality=75)
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


def _wait_window_closed():
    # wait for the window to appear, then block until it's gone
    for _ in range(40):
        if _window_open():
            break
        time.sleep(0.3)
    misses = 0
    while True:
        time.sleep(1.0)
        misses = 0 if _window_open() else misses + 1
        if misses >= 2:
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

    if not open_browser:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            httpd.shutdown()
        return

    # serve in the background; the main thread owns the window lifecycle
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    used_shell = False
    if not os.environ.get("CCDP_NO_SHELL"):
        try:
            from . import shell
            if shell.available():
                shell.run_gtk(url)          # native GTK+WebKit window; blocks until closed
                used_shell = True
        except Exception as e:
            util.log(f"native shell failed, falling back to app window: {e}", component="ui")

    if not used_shell:
        if _open_window(url):
            _wait_window_closed()           # Chrome app window; block until closed
        else:
            try:
                while True:
                    time.sleep(3600)        # fallback browser tab: run until interrupted
            except KeyboardInterrupt:
                pass

    httpd.shutdown()
