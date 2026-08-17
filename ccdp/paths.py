"""Filesystem locations. XDG-friendly, all under the user's home so nothing
needs root at runtime."""
import hashlib
import os

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


def project_key(path):
    """Stable short id for a project directory (surfaces are keyed by this)."""
    real = os.path.realpath(path)
    return hashlib.sha256(real.encode()).hexdigest()[:12]


def profile_dir(key):
    return os.path.join(PROFILES_DIR, key)
