@README.md

# Working in this repo

> **Always commit and push after making code changes.** When a task involves editing code,
> finish by staging everything, committing with a clear message, and running `git push` to
> `origin main`. Don't leave the working tree dirty at the end of a task.

The README above describes the program. Notes specific to editing it:

- **Name:** the brand is pending. Refer to it as "Claude Code Display Plugin" or "the
  program" — never invent or reuse a codename.
- **Stack:** Python 3 standard library + Pillow only. Keep it dependency-light so the `.deb`
  stays `Architecture: all` and installs cleanly. `mss` is an optional speed-up (fast
  capture); `scrot` is the required fallback. Don't add heavy runtime deps without reason.
- **The pure-vision contract:** the program only ever perceives via `screenshot` (pixels)
  and acts via OS-level input (`xdotool`). Do **not** add CDP/DOM/accessibility channels —
  that's a deliberate design decision (anti-bot + reduced injection surface).
- **Coordinates:** `screenshot` returns the display at native pixels; input is 1:1 with it.
  If you ever downscale a returned frame, you must scale click coordinates back up.
- **Wayland-host launch recipe:** X clients (Chrome, x11vnc) must be started with
  `WAYLAND_DISPLAY` unset / `XDG_SESSION_TYPE=x11` and Chrome with `--ozone-platform=x11`,
  or you get black captures and x11vnc refuses to start. Centralised in `util.x_env()` and
  `surfaces.CHROME_FLAGS`; change them there, not per-call.
- **Per-session MCP reality:** Claude Code spawns one MCP server per session, so shared
  state lives in the flock-guarded registry (`registry.py`) and surface processes are
  detached (`start_new_session=True`). Never assume a long-lived daemon.
- **Adding an MCP tool:** add its schema to `TOOLS` and a branch in `call_tool()` in
  `ccdp/mcp_server.py`. Keep stdout for JSON-RPC only — log via `util.log` (stderr + file).
- **Sandbox** (`sandbox.py`) is opt-in (`CCDP_SANDBOX=1`) and not yet hardened; leave it
  best-effort and fail open to unsandboxed with a logged warning.

## Run & build
```bash
PYTHONPATH="$PWD" python3 -m ccdp doctor          # dependency check
PYTHONPATH="$PWD" python3 -m ccdp ui --no-open     # dashboard
bash packaging/build-deb.sh                        # -> dist/*.deb
```
MCP smoke test: pipe newline-delimited JSON-RPC (`initialize`, `tools/list`, `tools/call`)
into `python3 -m ccdp mcp` and read the responses on stdout.

## Fixing reported bugs
Bugs filed by the `record_bug` tool land in `~/.local/state/ccdp/bugs/*.json` with the
session, project directory, and surface state attached. That's the intended feedback loop:
the user hands those reports over for fixes.
