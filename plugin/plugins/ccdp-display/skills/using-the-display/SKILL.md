---
name: using-the-display
description: Use whenever a task involves viewing, testing, navigating, filling in, or interacting with a website, web app, browser, or any graphical UI — or reproducing a visual/UI bug. This project has a real virtual display with a browser that you can see (screenshots) and drive with human-like mouse and keyboard input via the display tools (open_url, screenshot, click, type_text, press_key, scroll).
---

# Using the display

This project has a **real virtual display** with a browser running on it, provided by the
Claude Code Display Plugin. You can see it and drive it. Reach for it whenever a task
touches a web page or GUI: checking that a page renders, testing a login or a form, reading
a rendered dashboard, walking through a web flow, or reproducing a UI bug.

> **This display is your workspace — stay on it.** The virtual display these tools drive is
> yours and is isolated from the **human's real screen**. Do everything GUI-related here,
> through these tools. Do **not** try to reach or drive the human's actual desktop, and do
> **not** use other browser-automation or GUI tools — Playwright, Selenium, `xdotool`
> directly, or launching a browser from the shell — to do this work. Those act on the
> human's real machine and will take over their screen. If a task needs a browser or any
> GUI, it lives here, on your display, via `open_url` / `screenshot` / `click` / etc.

## How to use it

Work in a **see → act → see** loop. The display is stateful, so look before and after each
step:

1. **Navigate:** `open_url("https://example.com")` — this types the URL into the address bar
   like a person and loads the page. (The display is created automatically the first time.)
2. **Look:** `screenshot()` — returns the current display as an image. **All coordinates you
   pass to input tools are pixels in this image**, top-left origin, 1:1 with what you see.
3. **Act:** `click(x, y)`, `double_click` via `click(x, y, double=true)`, `move(x, y)`,
   `scroll(x, y, amount)` (negative = up), `type_text("...")` into the focused field,
   `press_key("Return" | "Escape" | "ctrl+a" | "ctrl+l" | ...)`.
4. **Verify:** call `screenshot()` again to confirm the result before the next action. Don't
   fire several blind actions in a row — read the screen between them.

## What to keep in mind

- **Read the pixels, then aim.** Take a screenshot, find the target in the image, and click
  its center in that image's coordinates. Don't guess coordinates without a fresh screenshot.
- **It's driven like a human.** Input is real OS-level mouse/keyboard, so pages that block
  automated browsers generally behave normally here.
- **Only ever use *this* display.** Never reach for Playwright/Selenium or a shell-launched
  browser to accomplish a GUI task — those drive the human's real screen. This display is
  the only sanctioned place to use a browser or GUI.
- **The display is shared and persistent** across sessions in this directory — another
  session may have left a page open. Screenshot first to see the current state.
- **The user can watch live** in the dashboard app (`ccdp ui`), and take control if needed.
- **If a display tool fails or misbehaves, call `record_bug`** with a clear summary and what
  you were doing. That report goes to the developer to fix.

## When NOT to use it

For things you can do directly — reading files, running commands, calling an HTTP API — use
your normal tools. The display is for when a task genuinely needs a rendered UI a human would
look at.
