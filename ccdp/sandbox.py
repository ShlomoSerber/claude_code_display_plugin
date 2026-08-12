"""Best-effort process isolation via bubblewrap.

Phase 0 did NOT get to harden/verify the sandbox on real hardware, so this is
deliberately conservative: sandboxing is OFF by default and opt-in via
CCDP_SANDBOX=1 (or config), so the program works out of the box and the sandbox
can be tightened as it's exercised. When enabled and `bwrap` is present, apps get
a private HOME with only the project directory bound in, no D-Bus, and the X
socket for their display. Network isolation / seccomp are left as follow-ups.
"""
import os
import shutil

from . import util


def enabled():
    return os.environ.get("CCDP_SANDBOX", "0") == "1" and shutil.which("bwrap") is not None


def wrap(cmd, *, profile_dir, project_dir, display):
    """Return cmd possibly wrapped in bwrap. Falls back to cmd unchanged (with a
    warning) when sandboxing is disabled or unavailable."""
    if not enabled():
        if os.environ.get("CCDP_SANDBOX") == "1":
            util.log("CCDP_SANDBOX=1 but bwrap not found — running UNSANDBOXED", component="sandbox")
        return cmd
    home = profile_dir  # private HOME per surface
    os.makedirs(home, exist_ok=True)
    xsock = "/tmp/.X11-unix"
    bwrap = [
        "bwrap",
        "--die-with-parent", "--new-session",
        "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
        "--ro-bind", "/usr", "/usr",
        "--ro-bind", "/etc", "/etc",
        "--symlink", "usr/lib", "/lib",
        "--symlink", "usr/lib64", "/lib64",
        "--symlink", "usr/bin", "/bin",
        "--ro-bind-try", xsock, xsock,
        "--bind", project_dir, project_dir,
        "--bind", home, home,
        "--setenv", "HOME", home,
        "--unsetenv", "DBUS_SESSION_BUS_ADDRESS",
    ]
    return bwrap + list(cmd)
