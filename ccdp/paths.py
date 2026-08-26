"""Filesystem locations, and the rule that decides *which* workspace a session
belongs to. XDG-friendly, all under the user's home so nothing needs root at
runtime."""
import hashlib
import os
import subprocess

_HOME = os.path.expanduser("~")


def _xdg(var, default):
    v = os.environ.get(var)
    return v if v and os.path.isabs(v) else os.path.join(_HOME, default)


STATE_DIR = os.path.join(_xdg("XDG_STATE_HOME", ".local/state"), "ccdp")
CONFIG_DIR = os.path.join(_xdg("XDG_CONFIG_HOME", ".config"), "ccdp")
RUNTIME_DIR = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or os.path.join(STATE_DIR, "run"), "ccdp") \
    if os.environ.get("XDG_RUNTIME_DIR") else os.path.join(STATE_DIR, "run")

SURFACES_JSON = os.path.join(STATE_DIR, "surfaces.json")
SURFACES_LOCK = os.path.join(STATE_DIR, "surfaces.lock")
BUGS_DIR = os.path.join(STATE_DIR, "bugs")
FEEDBACK_DIR = os.path.join(STATE_DIR, "feedback")
LOG_DIR = os.path.join(STATE_DIR, "logs")
PROFILES_DIR = os.path.join(STATE_DIR, "profiles")

# Where the installed program lives (overridable for dev). The .deb sets these.
INSTALL_ROOT = os.environ.get("CCDP_INSTALL_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.environ.get("CCDP_ASSETS_DIR") or os.path.join(INSTALL_ROOT, "assets")
PLUGIN_SRC_DIR = os.environ.get("CCDP_PLUGIN_DIR") or os.path.join(INSTALL_ROOT, "plugin")

# Where a plugin gets applied for Claude Code to discover it.
CLAUDE_DIR = os.path.join(_HOME, ".claude")
CLAUDE_PLUGINS_DIR = os.path.join(CLAUDE_DIR, "plugins")


def ensure_dirs():
    for d in (STATE_DIR, CONFIG_DIR, RUNTIME_DIR, BUGS_DIR, FEEDBACK_DIR, LOG_DIR, PROFILES_DIR):
        os.makedirs(d, exist_ok=True)


_TOPLEVEL_CACHE = {}


def git_worktree_root(path):
    """Root of the git *worktree* containing `path`, or None.

    `--show-toplevel` is the deliberate choice here. A git worktree is a separate
    working directory sharing one repository, and parallel agent lanes are exactly
    that: three worktrees of one repo, often nested inside the main checkout
    (`<repo>/.claude/worktrees/<lane>`). `--show-toplevel` returns each lane's own
    root, so the lanes key apart. `--git-common-dir` resolves to the *shared*
    repository and would collapse all of them onto one display — which is the bug,
    not the fix. Anything that walks up looking for `.git` has the same problem.
    """
    real = os.path.realpath(path)
    if real in _TOPLEVEL_CACHE:
        return _TOPLEVEL_CACHE[real]
    top = None
    try:
        p = subprocess.run(["git", "-C", real, "rev-parse", "--show-toplevel"],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           text=True, timeout=5)
        out = (p.stdout or "").strip()
        if p.returncode == 0 and out:
            top = os.path.realpath(out)
    except (OSError, subprocess.SubprocessError):
        top = None
    _TOPLEVEL_CACHE[real] = top
    return top


def workspace_dir():
    """The directory a session's displays are keyed by.

    Resolution order, first hit wins:

    1. `CCDP_DISPLAY_DIR` — explicit override, for when nothing else is right.
    2. The git worktree root of the process's current directory. For an ordinary
       single checkout this *is* the project root, so nothing changes; for a
       worktree lane it is the lane, which is the point.
    3. The git worktree root of `CLAUDE_PROJECT_DIR`, when the cwd is not in a
       repository at all.
    4. `CLAUDE_PROJECT_DIR`, then the cwd — the original behaviour.

    Preferring the cwd over `CLAUDE_PROJECT_DIR` matters: a session started in a
    worktree can still inherit its parent's `CLAUDE_PROJECT_DIR`, and keying on
    that would put every lane of a repo on one display.
    """
    override = (os.environ.get("CCDP_DISPLAY_DIR") or "").strip()
    if override:
        return os.path.realpath(os.path.expanduser(override))
    try:
        cwd = os.getcwd()
    except OSError:
        cwd = _HOME
    project = os.environ.get("CLAUDE_PROJECT_DIR") or cwd
    for candidate in (cwd, project):
        top = git_worktree_root(candidate)
        if top:
            return top
    return os.path.realpath(project)


def project_key(path):
    """Stable short id for a workspace directory (a workspace's first surface is
    keyed by this; extra surfaces for the same workspace get `<key>-2`, `-3`...)."""
    real = os.path.realpath(path)
    return hashlib.sha256(real.encode()).hexdigest()[:12]


def profile_dir(key):
    return os.path.join(PROFILES_DIR, key)
