"""stdio MCP server — the tools a Claude Code session uses to see and drive its
displays. Pure-vision: `screenshot` returns pixels, the input tools take pixel
coordinates from that screenshot.

Which display a call lands on:

* A session belongs to a **workspace** — its git worktree root, else its project
  directory (`paths.workspace_dir`). Two worktrees of one repository are two
  workspaces, so parallel agent lanes get a display each instead of fighting over
  one.
* With no `display` argument a call uses this session's display: the one it has
  already claimed, else the workspace's, created on first use. A lone agent never
  has to name an id.
* Passing `display` addresses a specific one and *sticks* — later calls in this
  session keep using it until another is named. That is what stops two agents
  sharing a display from silently reading each other's page.
* Every response says which display it acted on, so a wrong display is visible
  rather than silent.

Protocol: JSON-RPC 2.0, newline-delimited, over stdin/stdout. stdout carries ONLY
protocol messages; everything else goes to stderr.
"""
import base64
import json
import os
import sys
import traceback

from . import paths, registry, reports, surfaces, util

WORKSPACE_DIR = paths.workspace_dir()
PROJECT_DIR = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
SESSION_ID = (os.environ.get("CCDP_SESSION_ID") or os.environ.get("CLAUDE_SESSION_ID")
              or f"pid{os.getpid()}")
DEFAULT_PROTOCOL = "2025-06-18"

# The display this session is working on, once it has named or created one. Set by
# passing `display` to any tool, or by new_display. The MCP server is one process
# per session, so holding it here is exactly per-session state.
ACTIVE_KEY = None

DISPLAY_ARG = {
    "type": "string",
    "description": "Which display to act on. Leave it out to use this session's own display — "
                   "that is the right answer when you are the only agent working here. Pass the "
                   "id from list_surfaces (e.g. '4147a3bbfbcb'), an X display (':101'), a label, "
                   "or a directory path when several displays exist, e.g. parallel agents in "
                   "different git worktrees. Once you pass one, this session keeps using it "
                   "until you name a different one.",
}


def _with_display(props, required=None):
    schema = {"type": "object", "properties": dict(props, display=DISPLAY_ARG)}
    if required:
        schema["required"] = list(required)
    return schema


TOOLS = [
    dict(name="open_url",
         description="Open a web page on a display by typing the URL into the browser address "
                     "bar (human-like). Creates this session's display if it doesn't exist yet. "
                     "The browser reaches the network directly; to send it through a proxy or "
                     "tunnel, the display must be created with CCDP_PROXY (e.g. "
                     "socks5://127.0.0.1:1080) or CCDP_BROWSER_FLAGS set in the environment.",
         inputSchema=_with_display({"url": {"type": "string"}}, ["url"])),
    dict(name="screenshot",
         description="Capture a display and return it as an image. All click/move coordinates "
                     "are pixels in THIS image (top-left origin). The reply names the display "
                     "and the page it captured — check that against your own lane before you "
                     "draw a conclusion from it.",
         inputSchema=_with_display({})),
    dict(name="click",
         description="Click at pixel (x, y) on the display. button: 1=left,2=middle,3=right. "
                     "Set double=true for a double-click.",
         inputSchema=_with_display({
             "x": {"type": "integer"}, "y": {"type": "integer"},
             "button": {"type": "integer", "default": 1},
             "double": {"type": "boolean", "default": False}}, ["x", "y"])),
    dict(name="move",
         description="Move the mouse to pixel (x, y) without clicking (e.g. to reveal a hover state).",
         inputSchema=_with_display({"x": {"type": "integer"}, "y": {"type": "integer"}}, ["x", "y"])),
    dict(name="drag",
         description="Press the mouse at (x1, y1), move to (x2, y2), release — the gesture "
                     "click cannot express: drag-and-drop, moving or resizing a window by its "
                     "title bar or edge, dragging a slider or a selection. It travels in small "
                     "steps, which HTML5 drag-and-drop and pointermove handlers need in order "
                     "to fire at all. Use mouse_down/mouse_up instead when you need to see the "
                     "screen mid-drag or pass over several targets.",
         inputSchema=_with_display({
             "x1": {"type": "integer", "description": "Where the press starts."},
             "y1": {"type": "integer"},
             "x2": {"type": "integer", "description": "Where the release happens."},
             "y2": {"type": "integer"},
             "button": {"type": "integer", "default": 1},
             "steps": {"type": "integer", "default": 24,
                       "description": "Intermediate moves between press and release (2-200). "
                                      "More steps = slower, smoother drag."}},
             ["x1", "y1", "x2", "y2"])),
    dict(name="mouse_down",
         description="Press a mouse button at (x, y) and HOLD it. The button stays down across "
                     "later calls, so you can move, screenshot the drag in progress (drop "
                     "guides, highlights, the window ghost), pass over several targets, then "
                     "release with mouse_up. Always finish with mouse_up — a button left down "
                     "makes everything afterwards behave strangely; recover_display releases it.",
         inputSchema=_with_display({
             "x": {"type": "integer"}, "y": {"type": "integer"},
             "button": {"type": "integer", "default": 1}}, ["x", "y"])),
    dict(name="mouse_up",
         description="Release a held mouse button, optionally moving to (x, y) first. Pairs with "
                     "mouse_down.",
         inputSchema=_with_display({
             "x": {"type": "integer"}, "y": {"type": "integer"},
             "button": {"type": "integer", "default": 1}})),
    dict(name="scroll",
         description="Scroll at (x, y). amount negative = up, positive = down (number of wheel steps).",
         inputSchema=_with_display({
             "x": {"type": "integer"}, "y": {"type": "integer"}, "amount": {"type": "integer"}},
             ["x", "y", "amount"])),
    dict(name="type_text",
         description="Type text into whatever is currently focused on the display.",
         inputSchema=_with_display({"text": {"type": "string"}}, ["text"])),
    dict(name="press_key",
         description="Press a key or chord on the display. The argument is named 'keys' and takes "
                     "xdotool syntax: 'Return', 'Escape', 'ctrl+a', 'ctrl+l', 'F5' — or a sequence "
                     "separated by spaces, e.g. 'ctrl+l Return'.",
         inputSchema=_with_display({
             "keys": {"type": "string",
                      "description": "Key or chord, xdotool syntax, e.g. 'Return' or 'ctrl+l'."}},
             ["keys"])),
    dict(name="recover_display",
         description="Unstick a display when it stops responding: input seems to do nothing, the "
                     "screenshot never changes, or a stray window/menu has taken over. Dismisses "
                     "anything modal, puts focus back on the browser's main window and forces a full "
                     "repaint. Set restart_browser=true only if that didn't help — it reloads the "
                     "browser and loses page state. Also fixes a page that is painting stale pixels. "
                     "Only the addressed display is touched; other displays keep running.",
         inputSchema=_with_display({
             "restart_browser": {"type": "boolean", "default": False,
                                 "description": "Last resort: restart the browser on this display."}})),
    dict(name="attach_file",
         description="Pick a local file in the native file chooser that is open on the display — "
                     "the OS dialog a page opens when you click an <input type=\"file\">, an "
                     "'Upload' or a 'Choose file' control. Click that control first, then call "
                     "this with the file's absolute path: it types the path into the dialog and "
                     "confirms it, the way a person would. This is how upload and import flows "
                     "are done here. The chooser is an OS window, not part of the page, so "
                     "clicking around inside it from a screenshot is slow and it opens larger "
                     "than the display; this handles both. press_key('Escape') cancels it.",
         inputSchema=_with_display({
             "path": {"type": "string",
                      "description": "Absolute path of the file to attach, on this machine. "
                                     "The browser reads it directly, so it must exist."}},
             ["path"])),
    dict(name="new_display",
         description="Create an ADDITIONAL display, with its own id, and make it this session's "
                     "display from now on. Use it when you need a browser of your own: another "
                     "agent is already working on this project's display, or you want a second "
                     "page open beside the first to compare. Displays are expensive (each is a "
                     "browser, roughly 0.9GB), so create one when you need it and call "
                     "release_display when you're done with it.",
         inputSchema={"type": "object", "properties": {
             "url": {"type": "string", "description": "Page to open on it straight away."},
             "label": {"type": "string",
                       "description": "Short name to recognise it by later, e.g. the branch or "
                                      "lane you're testing ('board-shifts'). Shown by "
                                      "list_surfaces and usable as the display argument."}}}),
    dict(name="release_display",
         description="Close a display and give its memory back — a whole browser, roughly 0.9GB. "
                     "Call it when you're finished with a display you created. With no argument "
                     "it releases this session's display. Other displays are untouched.",
         inputSchema=_with_display({})),
    dict(name="list_surfaces",
         description="List the displays this program is managing: id, X display, workspace "
                     "directory, the page each one currently has open, which session is using it, "
                     "and memory. '*' marks the one this session's calls go to. Use it to pick the "
                     "display argument for the other tools, and to confirm you are looking at your "
                     "own work rather than another agent's.",
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


def _selector(args):
    return _arg(args, "display", "surface", "display_id", "surface_id", "id", "key",
                default=None)


def _target(args, *, create=True, url=None):
    """Resolve the display a call should act on, and remember it for this session.

    An explicit selector sticks: a lane that names its display once keeps using it
    for every later call, which is what makes two agents in one directory safe.
    """
    global ACTIVE_KEY
    sel = _selector(args)
    if sel:
        key = surfaces.resolve(sel, WORKSPACE_DIR, SESSION_ID)
        ACTIVE_KEY = key
    else:
        key = ACTIVE_KEY or surfaces.default_key(WORKSPACE_DIR, SESSION_ID)
    if create:
        rec = surfaces.ensure(WORKSPACE_DIR, key=key, url=url, session=SESSION_ID)
        ACTIVE_KEY = rec["key"]
        return rec
    rec = registry.get(key)
    if not rec:
        raise surfaces.NoSuchSurface(
            f"no display {key} — call screenshot or open_url to create one, or list_surfaces "
            "to see what is running.")
    ACTIVE_KEY = key
    return rec


def _text(s):
    return {"content": [{"type": "text", "text": s}]}


def _err(s):
    return {"content": [{"type": "text", "text": s}], "isError": True}


_selector_used = False


def _tag(rec, *, always=False):
    """One line naming the display a response acted on, and the page on it.

    Attribution, not prevention: when two agents end up on one display the wrong
    result stops being silent, which is the failure worth killing first. Shown
    whenever more than one display exists or this session has addressed one
    explicitly — a lone agent on a lone display doesn't need reminding.
    """
    if not always:
        others = sum(1 for r in registry.all_surfaces().values() if surfaces._alive(r))
        if others <= 1 and not _selector_used:
            return ""
    page = rec.get("last_url") or "about:blank"
    label = f' "{rec["label"]}"' if rec.get("label") else ""
    owner = rec.get("session")
    whose = " — ANOTHER SESSION'S DISPLAY" if owner and owner != SESSION_ID else ""
    return (f"\n[display {rec['key']}{label} {rec.get('display')} — {page} — "
            f"{os.path.basename(rec.get('project_dir') or '')}{whose}]")


STUCK_HINT = ("\n\n⚠ The display has not changed at all across the last {n} input actions. It is "
              "probably stuck (a stray window or menu holding focus, or a wedged browser). Call "
              "recover_display, then screenshot again, before sending more input.")

DIALOG_HINT = ("\n\n📎 A native dialog is open on this display: \"{name}\". It is an OS window the "
               "browser opened, not part of the page — the page underneath will not react to "
               "anything until it is dealt with. If it is a file chooser, call attach_file with "
               "the absolute path of the file you want instead of clicking through it; "
               "press_key('Escape') cancels it.")


def call_tool(name, args):
    global ACTIVE_KEY, _selector_used
    if _selector(args):
        _selector_used = True

    if name == "list_surfaces":
        data = registry.all_surfaces()
        live = [r for r in data.values() if surfaces._alive(r)]
        mine = ACTIVE_KEY or surfaces.default_key(WORKSPACE_DIR, SESSION_ID)
        if not live:
            return _text("No displays are running. open_url or screenshot creates one for this "
                         f"workspace ({WORKSPACE_DIR}); new_display creates an extra one.")
        body = "\n".join(surfaces.describe(r, active=(r["key"] == mine), session=SESSION_ID)
                         for r in live)
        return _text(f"Active displays ({len(live)} of a maximum {surfaces.MAX_DISPLAYS}). "
                     "'*' marks the one this session's calls go to; pass any id, ':NN' or label "
                     "as the 'display' argument to act on another.\n\n" + body)

    if name == "attach_file":
        path = _arg(args, "path", "file", "filename", "file_path", "filepath", "local_path")
        rec = _target(args)
        info = surfaces.attach_file(rec["key"], path)
        head = (f"Attached {info['path']} to the file chooser." if info["confirmed"] else
                f"Typed {info['path']} into the file chooser, but it is still open.")
        tail = ("\n\nCall screenshot to confirm the page picked the file up."
                if info["confirmed"] else
                "\n\nScreenshot the display and confirm it by clicking its Open button, or "
                "press_key('Escape') to cancel and try again.")
        return _text(head + "\n- " + "\n- ".join(info["steps"]) + tail
                     + _tag(registry.get(rec["key"]) or rec))

    if name == "new_display":
        url = _arg(args, "url", "uri", "address", default=None)
        label = _arg(args, "label", "name", "title", default=None)
        rec = surfaces.create(WORKSPACE_DIR, url=url, label=label, session=SESSION_ID)
        ACTIVE_KEY = rec["key"]
        _selector_used = True
        return _text(f"Created display {rec['key']} on {rec['display']}"
                     + (f' labelled "{label}"' if label else "")
                     + f" for {rec['project_dir']}. This session's calls now go to it; pass "
                     f"display='{rec['key']}' explicitly if you also drive another one. Call "
                     "release_display when you're done with it." + _tag(rec, always=True))

    if name == "release_display":
        rec = _target(args, create=False)
        surfaces.release(rec["key"])
        if ACTIVE_KEY == rec["key"]:
            ACTIVE_KEY = None
        left = sum(1 for r in registry.all_surfaces().values() if surfaces._alive(r))
        return _text(f"Released display {rec['key']} ({rec.get('display')}) and freed its browser. "
                     f"{left} display(s) still running. Calls with no display argument will now "
                     "use this workspace's display, creating one if needed.")

    if name == "record_bug":
        rec = registry.get(ACTIVE_KEY) if ACTIVE_KEY else None
        info = reports.BUGS.record(
            _arg(args, "summary", "title"),
            details=_arg(args, "details", "description", "body", default=None),
            severity=_arg(args, "severity", default="normal"), tool="mcp",
            session_id=SESSION_ID, project_dir=WORKSPACE_DIR, surface=rec,
            claude_project_dir=PROJECT_DIR)
        return _text(f"Recorded bug {info['id']} at {info['path']}. The user can pass this to the developer.")

    if name == "record_feedback":
        rec = registry.get(ACTIVE_KEY) if ACTIVE_KEY else None
        info = reports.FEEDBACK.record(
            _arg(args, "summary", "title", "feedback"),
            details=_arg(args, "details", "description", "body", default=None),
            category=_arg(args, "category", "kind", "type", default="other"), tool="mcp",
            session_id=SESSION_ID, project_dir=WORKSPACE_DIR, surface=rec,
            claude_project_dir=PROJECT_DIR)
        return _text(f"Recorded feedback {info['id']} at {info['path']}. It goes to the developer "
                     "alongside the bug reports — thanks.")

    if name == "open_url":
        url = _arg(args, "url", "uri", "address", "link", "href")
        rec = _target(args, url=url)
        return _text(f"Opened {url}. Call screenshot to see the page." + _tag(rec))

    if name == "screenshot":
        rec = _target(args)
        key = rec["key"]
        png, w, h, _, stale = surfaces.screenshot_png(key, track=True)
        text = f"Display is {w}x{h}px. Coordinates for click/move are pixels here."
        text += _tag(rec, always=True)
        dialog = surfaces.pending_dialog(rec)
        if dialog:
            text += DIALOG_HINT.format(name=dialog)
        if stale >= 3:
            text += STUCK_HINT.format(n=stale)
        return {"content": [
            {"type": "text", "text": text},
            {"type": "image", "data": base64.b64encode(png).decode(), "mimeType": "image/png"}]}

    if name == "click":
        x, y = _arg(args, "x", cast=_int), _arg(args, "y", cast=_int)
        rec = _target(args)
        surfaces.click(rec["key"], x, y, _arg(args, "button", default=1, cast=_int),
                       _arg(args, "double", "double_click", default=False, cast=_bool))
        return _text(f"Clicked ({x},{y}). Call screenshot to see the result." + _tag(rec))

    if name == "move":
        x, y = _arg(args, "x", cast=_int), _arg(args, "y", cast=_int)
        rec = _target(args)
        surfaces.move(rec["key"], x, y)
        return _text(f"Moved to ({x},{y})." + _tag(rec))

    if name == "drag":
        x1 = _arg(args, "x1", "from_x", "start_x", "sx", cast=_int)
        y1 = _arg(args, "y1", "from_y", "start_y", "sy", cast=_int)
        x2 = _arg(args, "x2", "to_x", "end_x", "ex", cast=_int)
        y2 = _arg(args, "y2", "to_y", "end_y", "ey", cast=_int)
        button = _arg(args, "button", default=1, cast=_int)
        steps = _arg(args, "steps", "n_steps", default=24, cast=_int)
        rec = _target(args)
        surfaces.drag(rec["key"], x1, y1, x2, y2, button, steps)
        return _text(f"Dragged ({x1},{y1}) → ({x2},{y2}) with button {button} in {steps} steps. "
                     "Call screenshot to see the result." + _tag(rec))

    if name == "mouse_down":
        x, y = _arg(args, "x", cast=_int), _arg(args, "y", cast=_int)
        button = _arg(args, "button", default=1, cast=_int)
        rec = _target(args)
        surfaces.mouse_down(rec["key"], x, y, button)
        return _text(f"Button {button} is now held down at ({x},{y}). Move, screenshot the drag "
                     "in progress, then release it with mouse_up." + _tag(rec))

    if name == "mouse_up":
        x = _arg(args, "x", default=None, cast=_int)
        y = _arg(args, "y", default=None, cast=_int)
        button = _arg(args, "button", default=1, cast=_int)
        rec = _target(args)
        surfaces.mouse_up(rec["key"], x, y, button)
        where = f" at ({x},{y})" if x is not None and y is not None else ""
        return _text(f"Released button {button}{where}. Call screenshot to see the result." + _tag(rec))

    if name == "scroll":
        x, y = _arg(args, "x", cast=_int), _arg(args, "y", cast=_int)
        amount = _arg(args, "amount", "clicks", "steps", "delta", "dy", cast=_int)
        rec = _target(args)
        surfaces.scroll(rec["key"], x, y, amount)
        return _text("Scrolled. Call screenshot to see the result." + _tag(rec))

    if name == "type_text":
        text = _arg(args, "text", "string", "value", "content")
        rec = _target(args)
        surfaces.type_text(rec["key"], text)
        return _text("Typed. Call screenshot to see the result." + _tag(rec))

    if name == "press_key":
        keys = _arg(args, "keys", "key", "combo", "chord", "shortcut", "keysym", "key_combination")
        rec = _target(args)
        surfaces.press_key(rec["key"], keys)
        pressed = " ".join(k for k in (keys if isinstance(keys, (list, tuple)) else [keys]))
        return _text(f"Pressed {pressed}. Call screenshot to see the result." + _tag(rec))

    if name == "recover_display":
        rec = _target(args)
        info = surfaces.recover(rec["key"], restart_browser=_arg(args, "restart_browser", "restart",
                                                                default=False, cast=_bool))
        return _text("Recovery on " + info["display"] + ":\n- " + "\n- ".join(info["steps"])
                     + "\n\nCall screenshot to see the display now."
                     + ("" if info["restarted"] else
                        " If it is still stuck, call recover_display with restart_browser=true.")
                     + _tag(registry.get(rec["key"]) or rec, always=True))

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
        except surfaces.PreconditionError as e:
            # The caller asked for something that isn't there, asked out of order,
            # or asked for one display too many. Answers, not malfunctions — so no
            # record_bug nudge, which would fill the queue with non-bugs.
            result = _err(str(e))
        except Exception as e:
            # Log the arguments too: without them a failure like a bare KeyError
            # names the key that was missing but never what the client actually sent.
            try:
                shown = json.dumps(args)[:600]
            except (TypeError, ValueError):
                shown = repr(args)[:600]
            util.log(f"tool {name} failed: {e!r} args={shown}\n{traceback.format_exc()}",
                     component="mcp")
            result = _err(f"{name} failed: {str(e).rstrip('.')}. "
                          "You can call record_bug to report this.")
        return {"jsonrpc": "2.0", "id": mid, "result": result}
    if method in ("shutdown", "exit"):
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601, "message": f"method not found: {method}"}}


def main():
    paths.ensure_dirs()
    util.log(f"mcp server up for workspace {WORKSPACE_DIR} "
             f"(key {paths.project_key(WORKSPACE_DIR)}, session {SESSION_ID})", component="mcp")
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
