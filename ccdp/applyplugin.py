"""Register the bundled plugin with Claude Code. The plugin ships as a local
marketplace (paths.PLUGIN_SRC_DIR); applying it adds that marketplace and installs
the plugin. Claude Code's plugin CLI has moved around across versions, so this is
best-effort and reports exactly what it ran — easy to adjust as the user iterates.
"""
import os

from . import claudecli, paths, util

MARKETPLACE_NAME = "ccdp"
PLUGIN_REF = "ccdp-display@ccdp"


def status():
    return {
        "claude_installed": claudecli.installed(),
        "claude_version": claudecli.version(),
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

    step([claude, "plugin", "marketplace", "add", paths.PLUGIN_SRC_DIR])
    rc = step([claude, "plugin", "install", PLUGIN_REF])

    ok = rc == 0
    return {
        "ok": ok,
        "message": ("Plugin applied. Open a new Claude Code session in a project directory "
                    "and the display tools will be available." if ok else
                    "The plugin CLI returned an error — see steps. You may need to run "
                    f"'/plugin marketplace add {paths.PLUGIN_SRC_DIR}' inside Claude Code, "
                    "then '/plugin install ccdp-display'."),
        "steps": steps,
    }
