# Claude Code Display Plugin

Gives every Claude Code session **a sandboxed virtual display it can see and drive the
way a human would** — screenshots out, real mouse/keyboard input in, no app-specific
channels (no CDP, no DOM, no accessibility tree). The first session in a working
directory creates the display; later sessions there share it; another directory — or
another git worktree of the same repository — gets its own. An agent that needs a
browser to itself asks for an extra one. A local dashboard app lets you watch every
display live and take control over VNC.

> The brand name is still pending. In code and docs this is just "the program" or its
> full name above.

---

## What you get

- A **display** (virtual X server via Xvfb) with a browser on it, created on demand.
- **Tools in every Claude Code session** to use it (pure-vision):
  `open_url`, `screenshot`, `click`, `move`, `drag`, `mouse_down`, `mouse_up`,
  `scroll`, `type_text`, `press_key`, `attach_file`, `recover_display`,
  `list_surfaces`, `new_display`, `release_display`, `record_bug`, and
  `record_feedback`.
  Every one of the acting tools takes an optional `display`, and every response says
  which display it acted on.
- A **dashboard** (`ccdp ui`) that shows every live display as a stream, with per-display
  memory, a full-control (VNC) button, a per-display **Recover** button, the reports
  sessions have filed, and — if Claude Code isn't installed yet — a prompt to install it and
  a button to apply the plugin once it is.
- **A way back to the developer.** If a display tool fails mid-session, Claude calls
  `record_bug`; if the program merely *could be better* — friction, a missing capability, a
  misleading tool description — Claude calls `record_feedback`. Both write reports under
  `~/.local/state/ccdp/` for you to hand over (`ccdp reports` prints them). The agent using
  the program is the one best placed to say what's wrong with it, so it's given a channel.

## Install

Build produces a single `.deb`:

```bash
bash packaging/build-deb.sh        # -> dist/claude-code-display-plugin_0.4.1_all.deb
sudo apt install ./dist/claude-code-display-plugin_0.4.1_all.deb
```

`apt` pulls the runtime dependencies (Xvfb, xdotool, scrot, x11vnc, x11-utils,
python3-pil, xdg-utils). A Chromium/Chrome browser is *recommended* (install
`google-chrome-stable` or `chromium` if you don't have one).

Then:

```bash
ccdp doctor          # verify dependencies
ccdp ui              # open the dashboard
ccdp apply-plugin    # register the plugin with Claude Code (or click "Apply plugin" in the UI)
```

### If Claude Code isn't installed yet
The dashboard detects this and shows a prompt to install Claude Code first, with an
**Apply plugin** button that becomes meaningful once Claude is present. Nothing else
needs the plugin until then — the dashboard and displays work on their own.

## How it works

```
Claude Code session ──(stdio MCP: `ccdp mcp`)──┐
Claude Code session ──(stdio MCP: `ccdp mcp`)──┤
                                               ▼
                        shared registry file  +  detached processes
                        (~/.local/state/ccdp)     Xvfb + browser per directory
                                               ▲
                          dashboard (`ccdp ui`)─┘  live MJPEG view + controls
```

- **One display per workspace by default.** A workspace is the git worktree root of the
  session's working directory, falling back to `CLAUDE_PROJECT_DIR` outside a repository.
  Because Claude Code runs a *separate* MCP server per session, shared state lives in a
  registry file and the Xvfb/browser processes are started **detached** so they outlive any
  one session. A file lock serialises input so two sessions can't fight over the pointer.
  Idle displays are reaped after 30 minutes; the total is capped (`CCDP_MAX_DISPLAYS`,
  default 6) because each display is a whole browser.
- **Launch recipe (important on Wayland hosts):** X apps are started with the Wayland
  environment scrubbed and `--ozone-platform=x11`, or Chrome renders to nothing and
  captures come back black; `x11vnc` needs the same. `util.x_env()` also cuts the host's
  audio sockets and its D-Bus session bus, so the display has no sound card and no route to
  the human's desktop services — that last one is what keeps file dialogs on the virtual
  display instead of the portal. All of it lives in `util.x_env()` and
  `surfaces.CHROME_FLAGS`.
- **Press-and-hold gestures are first class:** `drag(x1,y1,x2,y2)` presses, travels in
  small steps and releases — the intermediate moves are what make HTML5 drag-and-drop and
  pointermove handlers fire at all. `mouse_down` / `mouse_up` hold the button across calls,
  so a screenshot taken mid-gesture shows the drop guide, the hover highlight and the window
  ghost. A button left down is released by `recover_display`.
- **Pure-vision by design:** `screenshot` returns the display at native resolution; all
  input coordinates are pixels in that image (1:1). Navigation types the URL into the
  address bar like a person. This was validated in testing: models ground clicks on these
  screenshots reliably.

## File uploads

Clicking an `<input type="file">` opens the operating system's file chooser, not a part of
the page. Two things used to make that a dead end, and both are fixed:

- **The dialog never appeared at all.** With the host's D-Bus session bus in its
  environment, Chrome asked `xdg-desktop-portal` for the chooser — a service running in the
  *human's* desktop session, so the dialog was drawn nowhere the virtual display could see
  it. The session bus is now scrubbed alongside Wayland and audio in `util.x_env()`, and
  Chrome draws its own GTK chooser on the display.
- **The dialog opened bigger than the screen.** GTK asks for ~1231x902; there is no window
  manager here to constrain it, so its Cancel/Open row fell off the bottom of every
  screenshot.

`attach_file(path)` does the whole gesture: it fits the dialog to the display, types the
absolute path into the location bar and confirms. Click the page's file control first, then
call it.

```
click(128, 227)                       # the page's "Choose File" button
attach_file("/home/you/data/import.csv")
screenshot()                          # the page has the file
```

It waits up to 6s for the chooser to appear, because the browser takes about a second to put
it up. `press_key("Escape")` cancels the dialog, and `screenshot` says when one is open.
Everything here is still ordinary pointer and keyboard input — there is no DOM channel that
sets the input's files directly, by design.

## Parallel agents: more than one display

Several agents working the same repository at once — one git worktree each, each with its
own stack on its own ports — need a browser each. Two things make that work.

**Worktrees key apart.** The display key is the *worktree root* of the session's working
directory (`git rev-parse --show-toplevel`), not the repository. Three lanes of one repo are
three workspaces and get three displays, even when the lanes live inside the main checkout
at `<repo>/.claude/worktrees/<lane>` and every session reports the same
`CLAUDE_PROJECT_DIR`. `--git-common-dir` deliberately resolves to the shared repository, so
it is not used here; nothing walks up looking for `.git` either. Override with
`CCDP_DISPLAY_DIR` when neither rule fits.

**Displays are addressable, and every answer says which one it came from.** Each acting tool
takes an optional `display`, which accepts the id `list_surfaces` prints (or an unambiguous
prefix), an X display (`:101`), a label, or a directory path:

```
Active displays (2 of a maximum 6). '*' marks the one this session's calls go to.

* 59613d0db7db  :102  pss 336.4MB
    dir:   /home/you/farmagram/.claude/worktrees/board-shifts
    page:  http://localhost:3011/  — "Farmagram · Board"
    used by: this session
  cc5f2dcd22e8  :103  pss 324.9MB  "order-priority"
    dir:   /home/you/farmagram/.claude/worktrees/order-priority
    page:  http://localhost:3021/  — "Farmagram · Orders"
    used by: another session (a1b2c3)
```

- **No `display` argument behaves exactly as before.** A lone agent in a directory never has
  to name an id, and later sessions in one directory still share the display that is there.
- **An explicit `display` sticks.** Name it once and every later call in that session goes
  to it, until a different one is named.
- **Every response ends with the display it acted on and the page on it**, and says so
  loudly when that display belongs to another session. Two agents sharing one display is
  still allowed — it is a supported way to work — but it can no longer happen silently,
  which was the failure worth killing: a screenshot of someone else's page read as your own.
- **`new_display(url?, label?)`** creates an extra display for the same directory, with its
  own id, and makes it that session's display. Use it when the project's display is already
  busy, or to keep before and after open side by side.
- **`release_display(display?)`** closes one and hands its ~0.9GB back. `list_surfaces`
  stops showing it. Other displays are untouched, as they are by `recover_display`.
- **The count is capped** at `CCDP_MAX_DISPLAYS` (default 6). Asking for one too many
  returns an error naming the cap instead of starting a browser the machine can't hold.

## Reaching a backend behind a proxy or VPN

The managed browser talks to the network directly. When the app under test needs a tunnel —
an internal API reachable only through SOCKS5, say — set these in the environment of the
session that *creates* the display:

```bash
export CCDP_PROXY=socks5://127.0.0.1:1080   # every request goes through the proxy
export CCDP_BROWSER_FLAGS="--lang=es"       # any extra browser flags, verbatim
```

For a SOCKS proxy `CCDP_PROXY` also sends DNS through the tunnel (Chrome resolves locally
otherwise, which fails for names that only exist on the far side) while leaving `localhost`
resolving normally, so an app on `127.0.0.1` still loads. It adds `--test-type` with it,
purely to suppress Chrome's unsupported-flag infobar — that bar would push every page down
~44px and quietly break the 1:1 match between a screenshot and a click.

The flags are read when the display is created and stored on the surface record, so a later
relaunch or `recover_display` keeps them. `list_surfaces` shows them. Starting a second
browser of your own on the display is not an option: these displays run no window manager,
so a second Chrome starts but never maps a window.

## Sandboxing

Process isolation via **bubblewrap** is wired in but **off by default** and opt-in with
`CCDP_SANDBOX=1`, because it wasn't hardened/verified during initial testing. When enabled
(and `bwrap` present) apps get a private HOME with only the project directory bound in and
no D-Bus. Network namespacing and seccomp are follow-ups. Treat sandboxing as a work in
progress and enable it deliberately.

## Development

```
ccdp/            the runtime package
  paths.py         filesystem locations (XDG) + which workspace a session belongs to
  registry.py      surface registry (flock-guarded JSON; atomic key + display allocation)
  surfaces.py      display lifecycle: Xvfb + browser, capture, input, reaper, PSS
  capture.py       screen grab (mss/scrot) + PIL encode/resize/diff
  inputs.py        xdotool wrappers + per-surface input lock
  sandbox.py       bubblewrap wrapper (opt-in)
  mcp_server.py    the stdio MCP server (tools for a session)
  dashboard.py     the local web UI (state API, MJPEG, apply-plugin, reports)
  applyplugin.py   register the plugin with Claude Code
  reports.py       bug + feedback store
  cli.py           `ccdp` entrypoint
assets/dashboard/  the UI (html/css/js)
plugin/            the Claude Code plugin, shipped as a local marketplace
packaging/         build-deb.sh
```

Run from source (no install):

```bash
PYTHONPATH="$PWD" python3 -m ccdp doctor
PYTHONPATH="$PWD" python3 -m ccdp ui --no-open
# MCP: pipe newline-delimited JSON-RPC into `python3 -m ccdp mcp`
```

## Status

Implemented and smoke-tested: display lifecycle, capture, input, the MCP server and its
tools, addressable displays for parallel agents, the dashboard (state/stream/apply), the bug
tool, and the `.deb`. Known **pending**
work (by design — to be driven by real use and bug reports): sandbox hardening, the
multi-model "operator" loop, richer human take-over in-browser, and cross-platform
(this targets Linux first).

## Data locations
- State/registry/logs/reports/profiles: `~/.local/state/ccdp/`
- Environment: `CCDP_MAX_DISPLAYS` (concurrent display cap, default 6),
  `CCDP_DISPLAY_DIR` (override which directory a session's displays are keyed by),
  `CCDP_PROXY` / `CCDP_BROWSER_FLAGS` (browser flags, read when a display is created),
  `CCDP_WIDTH` / `CCDP_HEIGHT`, `CCDP_IDLE_REAP_S`, `CCDP_SANDBOX`.
- Bug reports: `~/.local/state/ccdp/bugs/*.json`
- Feedback: `~/.local/state/ccdp/feedback/*.json`
- Both, readably: `ccdp reports [all|bug|feedback]`.
- Once a report has been actioned, clear it — `ccdp archive <id>`, `ccdp archive --all`, or
  the dashboard's **Dismiss** button. All three move the file to an `archive/` subdirectory
  rather than deleting it, so the queue shows only what still needs attention.
