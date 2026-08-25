"""stdio MCP server — the tools a Claude Code session uses to see and drive its
project's display. Pure-vision: `screenshot` returns pixels, the input tools take
pixel coordinates from that screenshot. One surface per project directory (keyed
by CLAUDE_PROJECT_DIR), created lazily on first use and shared across sessions.

Protocol: JSON-RPC 2.0, newline-delimited, over stdin/stdout. stdout carries ONLY
protocol messages; everything else goes to stderr.
"""
import base64
import json
import os
import sys
import traceback

from . import paths, registry, reports, surfaces, util

PROJECT_DIR = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
SESSION_ID = os.environ.get("CCDP_SESSION_ID") or os.environ.get("CLAUDE_SESSION_ID")
DEFAULT_PROTOCOL = "2025-06-18"

TOOLS = [
    dict(name="open_url",
         description="Open a web page on this project's display by typing the URL into the "
                     "browser address bar (human-like). Creates the display if needed. The "
                     "browser reaches the network directly; to send it through a proxy or "
                     "tunnel, the display must be created with CCDP_PROXY (e.g. "
                     "socks5://127.0.0.1:1080) or CCDP_BROWSER_FLAGS set in the environment.",
         inputSchema={"type": "object", "properties": {"url": {"type": "string"}},
                      "required": ["url"]}),
    dict(name="screenshot",
         description="Capture the current display and return it as an image. All click/move "
                     "coordinates are pixels in THIS image (top-left origin).",
         inputSchema={"type": "object", "properties": {}}),
    dict(name="click",
         description="Click at pixel (x, y) on the display. button: 1=left,2=middle,3=right. "
                     "Set double=true for a double-click.",
         inputSchema={"type": "object", "properties": {
             "x": {"type": "integer"}, "y": {"type": "integer"},
             "button": {"type": "integer", "default": 1}, "double": {"type": "boolean", "default": False}},
             "required": ["x", "y"]}),
    dict(name="move",
         description="Move the mouse to pixel (x, y) without clicking (e.g. to reveal a hover state).",
         inputSchema={"type": "object", "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
                      "required": ["x", "y"]}),
    dict(name="drag",
         description="Press the mouse at (x1, y1), move to (x2, y2), release — the gesture "
                     "click cannot express: drag-and-drop, moving or resizing a window by its "
                     "title bar or edge, dragging a slider or a selection. It travels in small "
                     "steps, which HTML5 drag-and-drop and pointermove handlers need in order "
                     "to fire at all. Use mouse_down/mouse_up instead when you need to see the "
                     "screen mid-drag or pass over several targets.",
         inputSchema={"type": "object", "properties": {
             "x1": {"type": "integer", "description": "Where the press starts."},
             "y1": {"type": "integer"},
             "x2": {"type": "integer", "description": "Where the release happens."},
             "y2": {"type": "integer"},
             "button": {"type": "integer", "default": 1},
             "steps": {"type": "integer", "default": 24,
                       "description": "Intermediate moves between press and release (2-200). "
                                      "More steps = slower, smoother drag."}},
             "required": ["x1", "y1", "x2", "y2"]}),
    dict(name="mouse_down",
         description="Press a mouse button at (x, y) and HOLD it. The button stays down across "
                     "later calls, so you can move, screenshot the drag in progress (drop "
                     "guides, highlights, the window ghost), pass over several targets, then "
                     "release with mouse_up. Always finish with mouse_up — a button left down "
                     "makes everything afterwards behave strangely; recover_display releases it.",
         inputSchema={"type": "object", "properties": {
             "x": {"type": "integer"}, "y": {"type": "integer"},
             "button": {"type": "integer", "default": 1}},
             "required": ["x", "y"]}),
    dict(name="mouse_up",
         description="Release a held mouse button, optionally moving to (x, y) first. Pairs with "
                     "mouse_down.",
         inputSchema={"type": "object", "properties": {
             "x": {"type": "integer"}, "y": {"type": "integer"},
             "button": {"type": "integer", "default": 1}}}),
    dict(name="scroll",
         description="Scroll at (x, y). amount negative = up, positive = down (number of wheel steps).",
         inputSchema={"type": "object", "properties": {
             "x": {"type": "integer"}, "y": {"type": "integer"}, "amount": {"type": "integer"}},
             "required": ["x", "y", "amount"]}),
    dict(name="type_text",
         description="Type text into whatever is currently focused on the display.",
         inputSchema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}),
    dict(name="press_key",
         description="Press a key or chord on the display. The argument is named 'keys' and takes "
                     "xdotool syntax: 'Return', 'Escape', 'ctrl+a', 'ctrl+l', 'F5' — or a sequence "
                     "separated by spaces, e.g. 'ctrl+l Return'.",
         inputSchema={"type": "object", "properties": {
             "keys": {"type": "string",
                      "description": "Key or chord, xdotool syntax, e.g. 'Return' or 'ctrl+l'."}},
             "required": ["keys"]}),
    dict(name="recover_display",
         description="Unstick the display when it stops responding: input seems to do nothing, the "
                     "screenshot never changes, or a stray window/menu has taken over. Dismisses "
                     "anything modal, puts focus back on the browser's main window and forces a full "
                     "repaint. Set restart_browser=true only if that didn't help — it reloads the "
                     "browser and loses page state. Also fixes a page that is painting stale pixels.",
         inputSchema={"type": "object", "properties": {
             "restart_browser": {"type": "boolean", "default": False,
                                 "description": "Last resort: restart the browser on this display."}}}),
    dict(name="list_surfaces",
         description="List the active displays this program is managing and their status.",
         inputSchema={"type": "object", "properties": {}}),
    dict(name="record_bug",
         description="Record a bug against this program when a display tool fails or misbehaves, "
                     "so the user can hand it to the developer. Use when something here breaks.",
         inputSchema={"type": "object", "properties": {
             "summary": {"type": "string"}, "details": {"type": "string"},
             "severity": {"type": "string", "enum": ["low", "normal", "high"], "default": "normal"}},
             "required": ["summary"]}),
    dict(name="record_feedback",
         description="Leave feedback on this display program itself — not on the site you're looking "
                     "at. Use it when nothing is broken but something could be better: friction you "
                     "worked around, a capability you wished existed, a tool description that misled "
                     "you, or something that worked well and should stay. Stored locally next to bug "
                     "reports for the developer to act on; you are the one using these tools, so your "
                     "view is the point. Use record_bug instead when something is actually broken.",
         inputSchema={"type": "object", "properties": {
             "summary": {"type": "string", "description": "One line: what would be better, and why."},
             "details": {"type": "string",
                         "description": "What you were doing, what you expected, what you'd suggest."},
             "category": {"type": "string",
                          "enum": ["friction", "feature_request", "docs", "performance", "praise", "other"],
                          "default": "other"}},
             "required": ["summary"]}),
]

_MISSING = object()


def _arg(args, *names, default=_MISSING, cast=None):
    """Read an argument, accepting the obvious aliases for its name.

    Clients don't always send the exact key from the schema (filed bug: every
    press_key call failed with a bare KeyError on 'keys'). Taking the synonym is
    better than failing the action, and when nothing matches the error says what
    arrived instead of just naming the key that didn't."""
    for n in names:
        if isinstance(args, dict) and args.get(n) is not None:
            v = args[n]
            return cast(v) if cast else v
    if default is not _MISSING:
        return default
    got = ", ".join(sorted(args)) if args else "no arguments"
    raise ValueError(f"missing required argument {names[0]!r} (got: {got})")


def _int(v):
    return int(round(float(str(v).strip())))


def _bool(v):
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


def _key():
    return paths.project_key(PROJECT_DIR)


def _text(s):
    return {"content": [{"type": "text", "text": s}]}


def _err(s):
    return {"content": [{"type": "text", "text": s}], "isError": True}


STUCK_HINT = ("\n\n⚠ The display has not changed at all across the last {n} input actions. It is "
              "probably stuck (a stray window or menu holding focus, or a wedged browser). Call "
              "recover_display, then screenshot again, before sending more input.")


def call_tool(name, args):
    key = _key()
    if name == "open_url":
        url = _arg(args, "url", "uri", "address", "link", "href")
        surfaces.ensure(PROJECT_DIR, url=url)
        return _text(f"Opened {url}. Call screenshot to see the page.")
    if name == "screenshot":
        surfaces.ensure(PROJECT_DIR)
        png, w, h, _, stale = surfaces.screenshot_png(key, track=True)
        text = f"Display is {w}x{h}px. Coordinates for click/move are pixels here."
        if stale >= 3:
            text += STUCK_HINT.format(n=stale)
        return {"content": [
            {"type": "text", "text": text},
            {"type": "image", "data": base64.b64encode(png).decode(), "mimeType": "image/png"}]}
    if name == "click":
        x, y = _arg(args, "x", cast=_int), _arg(args, "y", cast=_int)
        surfaces.ensure(PROJECT_DIR)
        surfaces.click(key, x, y, _arg(args, "button", default=1, cast=_int),
                       _arg(args, "double", "double_click", default=False, cast=_bool))
        return _text(f"Clicked ({x},{y}). Call screenshot to see the result.")
    if name == "move":
        x, y = _arg(args, "x", cast=_int), _arg(args, "y", cast=_int)
        surfaces.ensure(PROJECT_DIR)
        surfaces.move(key, x, y)
        return _text(f"Moved to ({x},{y}).")
    if name == "drag":
        x1 = _arg(args, "x1", "from_x", "start_x", "sx", cast=_int)
        y1 = _arg(args, "y1", "from_y", "start_y", "sy", cast=_int)
        x2 = _arg(args, "x2", "to_x", "end_x", "ex", cast=_int)
        y2 = _arg(args, "y2", "to_y", "end_y", "ey", cast=_int)
        button = _arg(args, "button", default=1, cast=_int)
        steps = _arg(args, "steps", "n_steps", default=24, cast=_int)
        surfaces.ensure(PROJECT_DIR)
        surfaces.drag(key, x1, y1, x2, y2, button, steps)
        return _text(f"Dragged ({x1},{y1}) → ({x2},{y2}) with button {button} in {steps} steps. "
                     "Call screenshot to see the result.")
    if name == "mouse_down":
        x, y = _arg(args, "x", cast=_int), _arg(args, "y", cast=_int)
        button = _arg(args, "button", default=1, cast=_int)
        surfaces.ensure(PROJECT_DIR)
        surfaces.mouse_down(key, x, y, button)
        return _text(f"Button {button} is now held down at ({x},{y}). Move, screenshot the drag "
                     "in progress, then release it with mouse_up.")
    if name == "mouse_up":
        x = _arg(args, "x", default=None, cast=_int)
        y = _arg(args, "y", default=None, cast=_int)
        button = _arg(args, "button", default=1, cast=_int)
        surfaces.ensure(PROJECT_DIR)
        surfaces.mouse_up(key, x, y, button)
        where = f" at ({x},{y})" if x is not None and y is not None else ""
        return _text(f"Released button {button}{where}. Call screenshot to see the result.")
    if name == "scroll":
        x, y = _arg(args, "x", cast=_int), _arg(args, "y", cast=_int)
        amount = _arg(args, "amount", "clicks", "steps", "delta", "dy", cast=_int)
        surfaces.ensure(PROJECT_DIR)
        surfaces.scroll(key, x, y, amount)
        return _text("Scrolled. Call screenshot to see the result.")
    if name == "type_text":
        text = _arg(args, "text", "string", "value", "content")
        surfaces.ensure(PROJECT_DIR)
        surfaces.type_text(key, text)
        return _text("Typed. Call screenshot to see the result.")
    if name == "press_key":
        keys = _arg(args, "keys", "key", "combo", "chord", "shortcut", "keysym", "key_combination")
        surfaces.ensure(PROJECT_DIR)
        surfaces.press_key(key, keys)
        pressed = " ".join(k for k in (keys if isinstance(keys, (list, tuple)) else [keys]))
        return _text(f"Pressed {pressed}. Call screenshot to see the result.")
    if name == "recover_display":
        surfaces.ensure(PROJECT_DIR)
        info = surfaces.recover(key, restart_browser=_arg(args, "restart_browser", "restart",
                                                          default=False, cast=_bool))
        return _text("Recovery on " + info["display"] + ":\n- " + "\n- ".join(info["steps"])
                     + "\n\nCall screenshot to see the display now."
                     + ("" if info["restarted"] else
                        " If it is still stuck, call recover_display with restart_browser=true."))
    if name == "list_surfaces":
        data = registry.all_surfaces()
        lines = []
        for r in data.values():
            line = f"{r['key']} {r['display']} {r['project_dir']} (pss {surfaces.pss_mb(r)}MB)"
            if r.get("browser_flags"):
                line += " browser flags: " + " ".join(r["browser_flags"])
            if r.get("buttons_down"):
                line += " ⚠ mouse button(s) held down: " + \
                        ", ".join(str(b) for b in r["buttons_down"])
            lines.append(line)
        return _text("Active displays:\n" + ("\n".join(lines) if lines else "(none)"))
    if name == "record_bug":
        info = reports.BUGS.record(
            _arg(args, "summary", "title"),
            details=_arg(args, "details", "description", "body", default=None),
            severity=_arg(args, "severity", default="normal"), tool="mcp",
            session_id=SESSION_ID, project_dir=PROJECT_DIR, surface=registry.get(key))
        return _text(f"Recorded bug {info['id']} at {info['path']}. The user can pass this to the developer.")
    if name == "record_feedback":
        info = reports.FEEDBACK.record(
            _arg(args, "summary", "title", "feedback"),
            details=_arg(args, "details", "description", "body", default=None),
            category=_arg(args, "category", "kind", "type", default="other"), tool="mcp",
            session_id=SESSION_ID, project_dir=PROJECT_DIR, surface=registry.get(key))
        return _text(f"Recorded feedback {info['id']} at {info['path']}. It goes to the developer "
                     "alongside the bug reports — thanks.")
    return _err(f"unknown tool: {name}")


def handle(msg):
    mid = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}

    if method == "initialize":
        proto = params.get("protocolVersion") or DEFAULT_PROTOCOL
        from . import __version__
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": proto,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "ccdp-display", "version": __version__}}}
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            result = call_tool(name, args)
        except Exception as e:
            # Log the arguments too: without them a failure like a bare KeyError
            # names the key that was missing but never what the client actually sent.
            try:
                shown = json.dumps(args)[:600]
            except (TypeError, ValueError):
                shown = repr(args)[:600]
            util.log(f"tool {name} failed: {e!r} args={shown}\n{traceback.format_exc()}",
                     component="mcp")
            result = _err(f"{name} failed: {e}. You can call record_bug to report this.")
        return {"jsonrpc": "2.0", "id": mid, "result": result}
    if method in ("shutdown", "exit"):
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601, "message": f"method not found: {method}"}}


def main():
    paths.ensure_dirs()
    util.log(f"mcp server up for project {PROJECT_DIR}", component="mcp")
    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        try:
            resp = handle(msg)
        except Exception as e:
            resp = {"jsonrpc": "2.0", "id": msg.get("id"),
                    "error": {"code": -32603, "message": str(e)}}
        if resp is not None:
            out.write(json.dumps(resp) + "\n")
            out.flush()


if __name__ == "__main__":
    main()
