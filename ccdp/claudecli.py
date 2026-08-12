"""Detect the Claude Code CLI. Used by the UI to gate the 'apply plugin' flow and
(optionally, later) by an operator loop that delegates to `claude -p`."""
import os
import shutil

from . import util


def find():
    p = shutil.which("claude")
    if p:
        return p
    cand = os.path.expanduser("~/.local/bin/claude")
    return cand if os.path.exists(cand) else None


def installed():
    return find() is not None


def version():
    path = find()
    if not path:
        return None
    try:
        rc, out, _ = util.run([path, "--version"], timeout=15)
        return out.strip() if rc == 0 else None
    except Exception:
        return None
