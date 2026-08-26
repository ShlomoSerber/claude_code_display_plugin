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
- **`x_env()` cuts three inherited channels out of the sandbox** — Wayland, audio and the
  **D-Bus session bus** — and all three were bugs before they were policy. The bus is the
  subtlest: with it, Chrome routes the file chooser to `xdg-desktop-portal` in the *human's*
  session, so no dialog ever reaches the virtual display and uploads are impossible. Don't
  put it back. Note the fix only applies to browsers launched afterwards; an already-running
  display keeps its old environment until `recover_display(restart_browser=true)`.
- **No window manager has consequences beyond focus.** A dialog opens at whatever size GTK
  asks for (~1231x902 here, taller than the framebuffer) and nothing will ever resize it, and
  GTK will not activate a default button for a window no WM marked active — so Return in a
  file chooser does nothing and the gesture has to end in a click. `surfaces.attach_file()`
  handles both; if you touch it, re-test against a real chooser rather than reasoning about it.
- **Browser flags:** the base set lives in `surfaces.CHROME_FLAGS`; per-display extras come
  from the environment via `surfaces.extra_browser_flags()` (`CCDP_PROXY`,
  `CCDP_BROWSER_FLAGS`) and are stored on the surface record so a relaunch keeps them.
- **Held mouse buttons:** `mouse_down` without `mouse_up` leaves the pointer captured. The
  held buttons live in the registry (`buttons_down`) so `recover()` can release them.
- **Per-session MCP reality:** Claude Code spawns one MCP server per session, so shared
  state lives in the flock-guarded registry (`registry.py`) and surface processes are
  detached (`start_new_session=True`). Never assume a long-lived daemon. The one piece of
  genuinely per-session state is `mcp_server.ACTIVE_KEY` — which display this session's
  selectorless calls go to — and it lives in the process because the process *is* the
  session.
- **Workspace keying:** `paths.workspace_dir()` decides which display a session belongs to.
  It resolves the **git worktree root** of the cwd (`rev-parse --show-toplevel`), so parallel
  agent lanes key apart even when they are nested inside the main checkout and share one
  `CLAUDE_PROJECT_DIR`. Never key on `--git-common-dir` or on walking up to `.git`: both
  collapse every worktree of a repo onto one display, which is the bug this fixed.
- **Surface keys:** a workspace's first display is `project_key(dir)`; extras are
  `<key>-2`, `<key>-3`. `registry.reserve()` hands out the key, the X display number and the
  cap check in **one** locked operation — allocating them separately let two lanes creating
  a display at the same instant both pick `:101`.
- **Addressing and attribution:** every acting tool takes an optional `display`
  (id, prefix, `:NN`, label or path — `surfaces.resolve()`), and an explicit one sticks for
  the session. Every response carries `_tag()`, naming the display and its page, and shouting
  when the display belongs to another session. Keep that: a wrong screenshot that looks right
  is worse than a failure, and attribution is what makes it visible.
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

## Fixing reported bugs, reading feedback
Sessions file two kinds of report through the MCP tools, both stored by `reports.py` with
the session, project directory, and surface state attached:

- `record_bug` → `~/.local/state/ccdp/bugs/*.json` — something broke.
- `record_feedback` → `~/.local/state/ccdp/feedback/*.json` — it works, but here's friction,
  a missing capability, or a suggestion.

`ccdp reports` prints both. That's the intended feedback loop: the agent using the program
is the one best placed to say what's wrong with it, and the user hands those reports over.
Reports are written by the agent, not the user — read them as field notes, and check the
claim against the code before acting on it.

**Clear the queue as you action it.** A report that has been fixed, implemented, or
deliberately declined must stop being shown, or the queue silently turns into a pile of
stale garbage and nobody reads it. Archive it in the same task that actions it:

```bash
ccdp archive <id> [<id>...]     # ids come from `ccdp reports`
ccdp archive --all              # everything actioned in one go
```

Archiving moves the file to `archive/` — it is reversible and nothing is deleted, so the
history is still there. The dashboard's per-report **Dismiss** button does the same thing.
