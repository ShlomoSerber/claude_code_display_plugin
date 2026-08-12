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

from . import bugs, paths, registry, surfaces, util

PROJECT_DIR = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
SESSION_ID = os.environ.get("CCDP_SESSION_ID") or os.environ.get("CLAUDE_SESSION_ID")
DEFAULT_PROTOCOL = "2025-06-18"

TOOLS = [
    dict(name="open_url",
         description="Open a web page on this project's display by typing the URL into the "
                     "browser address bar (human-like). Creates the display if needed.",
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
    dict(name="scroll",
         description="Scroll at (x, y). amount negative = up, positive = down (number of wheel steps).",
         inputSchema={"type": "object", "properties": {
             "x": {"type": "integer"}, "y": {"type": "integer"}, "amount": {"type": "integer"}},
             "required": ["x", "y", "amount"]}),
    dict(name="type_text",
         description="Type text into whatever is currently focused on the display.",
         inputSchema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}),
    dict(name="press_key",
         description="Press a key or chord, xdotool syntax (e.g. 'Return', 'Escape', 'ctrl+a', 'ctrl+l').",
         inputSchema={"type": "object", "properties": {"keys": {"type": "string"}}, "required": ["keys"]}),
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
]


def _key():
    return paths.project_key(PROJECT_DIR)


def _text(s):
    return {"content": [{"type": "text", "text": s}]}


def _err(s):
    return {"content": [{"type": "text", "text": s}], "isError": True}


def call_tool(name, args):
    key = _key()
    if name == "open_url":
        surfaces.ensure(PROJECT_DIR, url=args["url"])
        return _text(f"Opened {args['url']}. Call screenshot to see the page.")
    if name == "screenshot":
        surfaces.ensure(PROJECT_DIR)
        png, w, h, _ = surfaces.screenshot_png(key)
        return {"content": [
            {"type": "text", "text": f"Display is {w}x{h}px. Coordinates for click/move are pixels here."},
            {"type": "image", "data": base64.b64encode(png).decode(), "mimeType": "image/png"}]}
    if name == "click":
        surfaces.ensure(PROJECT_DIR)
        surfaces.click(key, args["x"], args["y"], args.get("button", 1), bool(args.get("double")))
        return _text(f"Clicked ({args['x']},{args['y']}). Call screenshot to see the result.")
    if name == "move":
        from . import inputs
        surfaces.ensure(PROJECT_DIR)
        rec = registry.get(key)
        with inputs.input_lock(key):
            inputs.move(rec["display"], args["x"], args["y"])
        return _text(f"Moved to ({args['x']},{args['y']}).")
    if name == "scroll":
        surfaces.ensure(PROJECT_DIR)
        surfaces.scroll(key, args["x"], args["y"], args["amount"])
        return _text("Scrolled. Call screenshot to see the result.")
    if name == "type_text":
        surfaces.ensure(PROJECT_DIR)
        surfaces.type_text(key, args["text"])
        return _text("Typed. Call screenshot to see the result.")
    if name == "press_key":
        surfaces.ensure(PROJECT_DIR)
        surfaces.press_key(key, args["keys"])
        return _text(f"Pressed {args['keys']}.")
    if name == "list_surfaces":
        data = registry.all_surfaces()
        lines = [f"{r['key']} {r['display']} {r['project_dir']} "
                 f"(pss {surfaces.pss_mb(r)}MB)" for r in data.values()]
        return _text("Active displays:\n" + ("\n".join(lines) if lines else "(none)"))
    if name == "record_bug":
        info = bugs.record(args["summary"], details=args.get("details"),
                           severity=args.get("severity", "normal"), tool="mcp",
                           session_id=SESSION_ID, project_dir=PROJECT_DIR,
                           surface=registry.get(key))
        return _text(f"Recorded bug {info['id']} at {info['path']}. The user can pass this to the developer.")
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
            util.log(f"tool {name} failed: {e}\n{traceback.format_exc()}", component="mcp")
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
