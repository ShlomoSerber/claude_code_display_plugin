# ccdp-display

Part of the **Claude Code Display Plugin**. When enabled, every Claude Code session
in a project directory gets a sandboxed virtual display it can see and drive.

## Tools this exposes to the session
- `open_url(url)` — open a page (types the URL into the address bar, human-like)
- `screenshot()` — capture the display as an image; coordinates below are pixels in it
- `click(x, y, button?, double?)`, `move(x, y)`, `scroll(x, y, amount)`
- `type_text(text)`, `press_key(keys)`
- `list_surfaces()` — the displays being managed
- `record_bug(summary, details?, severity?)` — file a bug when a display tool misbehaves

The display is created lazily on first use and shared by all sessions in the same
directory. Watch it live in the dashboard: run `ccdp ui`.

The MCP server is the `ccdp mcp` command (installed by the .deb). If tools are
missing, run `ccdp doctor`.
