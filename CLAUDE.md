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
  the keyboard cannot confirm it: Return in the location bar (or a double-click on a file)
  *closes* the chooser, but Chrome receives no file and the page's input never changes. So a
  closed dialog proves nothing, and the gesture has to end in a click on Open — never try
  Return first. `surfaces.attach_file()` handles both; if you touch it, re-test against a
  real chooser *and check the page got the file*, not that the dialog went away.
- **`open_url` waits for the address bar.** Chrome offers ctrl+L to the page before acting on
  it, so a busy page (a Flutter app) delays the focus change and the first typed characters
  land in the page: `http://host/#/x` became `//host/#/x`, which the omnibox opens as
  `file:///host/%23/x`. `_focus_address_bar()` watches the toolbar row change before typing.
  Don't replace it with a fixed sleep.
- **No sound reaches the host.** `x11vnc` runs with `-nobell` and the noVNC URL carries
  `bell=off`: the dashboard is a host process, so a bell there rings the human's speakers.
- **Browser flags:** the base set lives in `surfaces.CHROME_FLAGS`; per-display extras come
  from the environment via `surfaces.extra_browser_flags()` (`CCDP_PROXY`,
  `CCDP_BROWSER_FLAGS`) and are stored on the surface record so a relaunch keeps them.
  `--window-size` is deliberately *not* in `CHROME_FLAGS` — it is per surface and
  `set_viewport` changes it, so `_launch_browser` appends it.
- **Zoom is profile state, not a flag.** A reported "`--force-device-scale-factor=1` doesn't
  change devicePixelRatio" was Chrome *page zoom* at 110%, saved per origin in the profile
  (`partition.per_host_zoom_levels`) by one earlier `ctrl+plus` and inherited by every later
  session on that display. No flag can undo it: `_reset_zoom_prefs()` strips those keys
  before every launch, and `press_key` watches the zoom chords go past so `viewport_line()`
  can say the display is zoomed. Don't "simplify" this back to a flag.
- **The display measures itself.** `calibrate()` loads `CALIBRATION_HTML` — magenta page
  area, a 200-CSS-px scrolling box, a 100-CSS-px ruler — and reads the rectangle back out of
  the capture, which is the only way to know the page area, the scrollbar width and the
  scale without a DOM channel. Every marker must stay a *patch inside* the magenta, or the
  magenta bounding box stops being the page area (that was the first version's bug). Numbers
  are exact against the JS ground truth; if you touch the page, re-verify against a real
  `window.innerWidth`, don't reason about it.
- **`set_viewport` restarts the display.** Xvfb fixes its framebuffer at start — its RandR
  maximum *is* the launch size, `xrandr` cannot grow it — so `resize()` relaunches the X
  server and the browser. It measures, corrects once, and lands exactly; keep the correction
  loop rather than hardcoding the toolbar height.
- **Full-page capture is scroll-and-stitch, and both halves are load-bearing.** The wheel
  step is set by the page (measured at 120px on one test page, ~50 elsewhere), so a first
  scroll that overshoots the viewport leaves no overlap and the capture silently stops after
  one frame — hence `FIRST_SCROLL_TICKS = 2` and calibrating the step from the first real
  shift. And `capture.find_shift` tests the longest *contiguous* run of matching rows, not
  the fraction: a sticky header stays put while the page moves, which a ratio test reads as
  "no match". "Nothing moved" (bottom) is `changed_fraction == 0`, checked *before* the
  shift search — without it the shrink-and-retry path un-sticks the page and re-captures
  forever.
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
