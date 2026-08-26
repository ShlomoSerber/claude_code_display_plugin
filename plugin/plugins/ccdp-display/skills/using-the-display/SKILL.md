---
name: using-the-display
description: Use whenever a task involves viewing, testing, navigating, filling in, or interacting with a website, web app, browser, or any graphical UI — or reproducing a visual/UI bug. This project has a real virtual display with a browser that you can see (screenshots) and drive with human-like mouse and keyboard input via the display tools (open_url, screenshot, click, drag, type_text, press_key, scroll).
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
   To press and hold — drag-and-drop, moving or resizing a window by its title bar or edge,
   dragging a slider or a selection — use `drag(x1, y1, x2, y2)`; see below.
4. **Verify:** call `screenshot()` again to confirm the result before the next action. Don't
   fire several blind actions in a row — read the screen between them.

## Dragging and other press-and-hold gestures

`click` presses and releases at one point, so it can never express a drag. Two tools do:

- **`drag(x1, y1, x2, y2, button?, steps?)`** — the 90% case. It presses at the first point,
  travels to the second in small steps, then releases. Those intermediate moves matter:
  HTML5 drag-and-drop and pointermove gestures only fire `dragover` when the pointer really
  moves between the press and the release, so a single jump drops nothing.
- **`mouse_down(x, y)` … `mouse_up(x, y)`** — for multi-leg gestures and, above all, for
  *looking mid-drag*. The button stays held across calls, so you can `mouse_down`, `move`
  over a target, `screenshot` the drop guide / highlight / window ghost, move on to another
  target, and only then `mouse_up`. Those intermediate states are invisible to `drag`.

**Always release what you press.** A button left down captures the pointer and makes
everything afterwards behave strangely. If you lose track, `recover_display()` releases it,
and `list_surfaces()` shows a warning while a button is still held.

## Working alongside other agents

Most of the time there is one display and you never think about it: call the tools with no
`display` argument and they act on this working directory's display.

It matters when several agents work the same repository at once. Each git worktree is its
own workspace and gets its own display, so lanes don't collide by accident. Two things keep
it honest when they do share a directory:

- **Every response names the display it acted on** and the page on it, like
  `[display 59613d0db7db :102 — http://localhost:3011/ — board-shifts]`. **Read that line
  before you trust a screenshot.** If it shows a URL that isn't your lane's, you are looking
  at another agent's work — a wrong answer that looks right. The line says
  `ANOTHER SESSION'S DISPLAY` when the display was created by someone else.
- **`list_surfaces()`** shows every display with its id, its directory, the page it has open
  and who is using it. `*` marks the one your calls go to.

To take a display of your own: **`new_display(url?, label?)`**. It creates an extra one with
its own id and points your calls at it — label it with your lane or branch so it is
recognisable. To act on a specific display without changing which one is yours, pass
`display=` (the id, an unambiguous prefix of it, `:102`, a label, or a directory path); an
explicit `display` then sticks for your later calls until you name another.

Displays are expensive — each is a real browser, roughly 0.9GB, and the total is capped.
Call **`release_display()`** when you're finished with one you created. `recover_display`
and `release_display` only ever touch the display you address; the others keep running.

## When the display stops responding

Occasionally input stops landing: clicks and keys do nothing, `open_url` reports success but
the page never changes, and every screenshot comes back identical. Usually a stray window or
an open menu has taken focus, or the browser has wedged. A screenshot warns you when it
notices this, and the fix is `recover_display()` — it dismisses anything modal, puts focus
back on the browser's main window and forces a full repaint. Screenshot again afterwards. If
it's *still* frozen, call `recover_display(restart_browser=true)`: that restarts the browser
on the same display (you lose page state, so try the plain call first).

`recover_display()` is also the fix when the page paints something visibly wrong — stale
colours, a region that didn't update — since it forces the browser to re-render everything.

## What to keep in mind

- **Read the pixels, then aim.** Take a screenshot, find the target in the image, and click
  its center in that image's coordinates. Don't guess coordinates without a fresh screenshot.
- **It's driven like a human.** Input is real OS-level mouse/keyboard, so pages that block
  automated browsers generally behave normally here.
- **Only ever use *this* display.** Never reach for Playwright/Selenium or a shell-launched
  browser to accomplish a GUI task — those drive the human's real screen. This display is
  the only sanctioned place to use a browser or GUI.
- **The browser goes straight out to the network.** If the app's backend only exists behind
  a tunnel or VPN, the display must be created with `CCDP_PROXY` (e.g.
  `socks5://127.0.0.1:1080`) or `CCDP_BROWSER_FLAGS` set in the environment — see the
  project README. Don't start a browser of your own on the display: there is no window
  manager here, so a second browser starts but never shows a window.
- **The display is shared and persistent** across sessions in this directory — another
  session may have left a page open. Screenshot first to see the current state, and read the
  `[display ...]` line in the reply to confirm it is showing your page and not someone
  else's. If another agent is driving it, take your own with `new_display`.
- **The user can watch live** in the dashboard app (`ccdp ui`), and take control if needed.
- **If a display tool fails or misbehaves, call `record_bug`** with a clear summary and what
  you were doing. That report goes to the developer to fix.
- **If something merely *could be better*, call `record_feedback`.** Not about the site you're
  looking at — about these display tools themselves: friction you had to work around, a
  capability you wished existed, a tool description that pointed you the wrong way, an
  awkward loop, or something that worked well and should stay. You are the one actually using
  this program, so your view is the whole point of the tool; the developer reads these
  alongside the bug reports. One line of specific feedback beats none — file it as you notice
  it rather than saving it for the end of the task.

## When NOT to use it

For things you can do directly — reading files, running commands, calling an HTTP API — use
your normal tools. The display is for when a task genuinely needs a rendered UI a human would
look at.
