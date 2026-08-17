# Claude Code Display Plugin

Gives every Claude Code session, **per project directory, a sandboxed virtual display
it can see and drive the way a human would** — screenshots out, real mouse/keyboard
input in, no app-specific channels (no CDP, no DOM, no accessibility tree). The first
session opened in a directory creates the display; later sessions in the same directory
share it; a new directory gets its own. A local dashboard app lets you watch every
display live and take control over VNC.

> The brand name is still pending. In code and docs this is just "the program" or its
> full name above.

---

## What you get

- A **display** (virtual X server via Xvfb) with a browser on it, created on demand.
- **Tools in every Claude Code session** to use it (pure-vision):
  `open_url`, `screenshot`, `click`, `move`, `scroll`, `type_text`, `press_key`,
  `recover_display`, `list_surfaces`, `record_bug`, and `record_feedback`.
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
bash packaging/build-deb.sh        # -> dist/claude-code-display-plugin_0.2.0_all.deb
sudo apt install ./dist/claude-code-display-plugin_0.2.0_all.deb
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

- **One display per project directory**, keyed by `CLAUDE_PROJECT_DIR`. Because Claude
  Code runs a *separate* MCP server per session, shared state lives in a registry file and
  the Xvfb/browser processes are started **detached** so they outlive any one session. A
  file lock serialises input so two sessions can't fight over the pointer. Idle displays are
  reaped after 30 minutes.
- **Launch recipe (important on Wayland hosts):** X apps are started with the Wayland
  environment scrubbed and `--ozone-platform=x11`, or Chrome renders to nothing and
  captures come back black; `x11vnc` needs the same. This is handled in `util.x_env()` and
  `surfaces.CHROME_FLAGS`.
- **Pure-vision by design:** `screenshot` returns the display at native resolution; all
  input coordinates are pixels in that image (1:1). Navigation types the URL into the
  address bar like a person. This was validated in testing: models ground clicks on these
  screenshots reliably.

## Sandboxing

Process isolation via **bubblewrap** is wired in but **off by default** and opt-in with
`CCDP_SANDBOX=1`, because it wasn't hardened/verified during initial testing. When enabled
(and `bwrap` present) apps get a private HOME with only the project directory bound in and
no D-Bus. Network namespacing and seccomp are follow-ups. Treat sandboxing as a work in
progress and enable it deliberately.

## Development

```
ccdp/            the runtime package
  paths.py         filesystem locations (XDG)
  registry.py      surface registry (flock-guarded JSON)
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
tools, the dashboard (state/stream/apply), the bug tool, and the `.deb`. Known **pending**
work (by design — to be driven by real use and bug reports): sandbox hardening, the
multi-model "operator" loop, richer human take-over in-browser, and cross-platform
(this targets Linux first).

## Data locations
- State/registry/logs/reports/profiles: `~/.local/state/ccdp/`
- Bug reports: `~/.local/state/ccdp/bugs/*.json`
- Feedback: `~/.local/state/ccdp/feedback/*.json`
- Both, readably: `ccdp reports [all|bug|feedback]`. Dismissing one in the dashboard moves
  the file to an `archive/` subdirectory rather than deleting it.
