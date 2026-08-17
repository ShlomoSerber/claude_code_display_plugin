"""Register the bundled plugin with Claude Code. The plugin ships as a local
marketplace (paths.PLUGIN_SRC_DIR); applying it adds that marketplace and installs
the plugin. Claude Code's plugin CLI has moved around across versions, so this is
best-effort and reports exactly what it ran — easy to adjust as the user iterates.
"""
import os

from . import claudecli, paths, util

MARKETPLACE_NAME = "ccdp"
PLUGIN_REF = "ccdp-display@ccdp"
MARKER = os.path.join(paths.STATE_DIR, "plugin-applied")


def _mark(applied):
    paths.ensure_dirs()
    if applied:
        open(MARKER, "w").close()
    elif os.path.exists(MARKER):
        os.remove(MARKER)


def status():
    return {
        "claude_installed": claudecli.installed(),
        "claude_version": claudecli.version(),
        "plugin_applied": os.path.exists(MARKER),
        "marketplace_dir": paths.PLUGIN_SRC_DIR,
        "marketplace_present": os.path.exists(
            os.path.join(paths.PLUGIN_SRC_DIR, ".claude-plugin", "marketplace.json")),
    }


def apply():
    claude = claudecli.find()
    if not claude:
        return {"ok": False, "reason": "claude-not-installed",
                "message": "Claude Code is not installed. Install it first, then apply the plugin."}
    if not os.path.exists(os.path.join(paths.PLUGIN_SRC_DIR, ".claude-plugin", "marketplace.json")):
        return {"ok": False, "reason": "marketplace-missing",
                "message": f"Plugin marketplace not found at {paths.PLUGIN_SRC_DIR}."}

    steps = []

    def step(cmd):
        try:
            rc, out, err = util.run(cmd, timeout=120)
        except Exception as e:
            rc, out, err = 1, "", str(e)
        steps.append({"cmd": " ".join(cmd), "rc": rc,
                      "out": (out or "").strip()[-600:], "err": (err or "").strip()[-600:]})
        return rc

    # Claude Code caches the plugin per version, so a first-time `add` + `install`
    # is a no-op once anything is installed — after a .deb upgrade that silently
    # leaves sessions on the old skill and tool list. Refresh the marketplace from
    # its source and update the plugin too; each step is a no-op when it's already
    # current, so this is also the right sequence for a first install.
    step([claude, "plugin", "marketplace", "add", paths.PLUGIN_SRC_DIR])
    step([claude, "plugin", "marketplace", "update", MARKETPLACE_NAME])
    rc = step([claude, "plugin", "install", PLUGIN_REF])
    rc_update = step([claude, "plugin", "update", PLUGIN_REF])

    ok = rc == 0 or rc_update == 0
    if ok:
        _mark(True)
    return {
        "ok": ok,
        "message": ("Plugin applied. Open a new Claude Code session in a project directory "
                    "and the display tools will be available (restart any session that is "
                    "already open — it keeps the plugin it started with)." if ok else
                    "The plugin CLI returned an error — see steps. You may need to run "
                    f"'/plugin marketplace add {paths.PLUGIN_SRC_DIR}' inside Claude Code, "
                    "then '/plugin install ccdp-display'."),
        "steps": steps,
    }


def remove():
    claude = claudecli.find()
    steps = []

    def step(cmd):
        try:
            rc, out, err = util.run(cmd, timeout=120)
        except Exception as e:
            rc, out, err = 1, "", str(e)
        steps.append({"cmd": " ".join(cmd), "rc": rc,
                      "out": (out or "").strip()[-600:], "err": (err or "").strip()[-600:]})
        return rc

    if claude:
        step([claude, "plugin", "uninstall", "ccdp-display"])
        step([claude, "plugin", "marketplace", "remove", MARKETPLACE_NAME])
    _mark(False)
    return {"ok": True,
            "message": "Plugin removed. New Claude Code sessions won't load the display tools.",
            "steps": steps}
