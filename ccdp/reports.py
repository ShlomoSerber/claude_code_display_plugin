"""Report store — the program's feedback loop back to its developer.

A Claude Code session using the display can file two kinds of report:

* **bug** (`record_bug`) — a display tool broke or misbehaved.
* **feedback** (`record_feedback`) — nothing is broken, but something is awkward,
  missing, or worth keeping: friction, a wished-for capability, a suggestion.

Both land as plain JSON files under the state dir (plus an append-only `.jsonl`
index) for the user to hand over. Deliberately simple and local — no network.
Dismissing a report moves it to an `archive/` subdirectory rather than deleting
it, so nothing a session took the trouble to write is ever lost.
"""
import glob
import json
import os
import shutil
import time
import uuid

from . import paths

KINDS = ("bug", "feedback")


class Store:
    """One kind of report, stored as files in its own directory."""

    def __init__(self, kind, directory, index_name):
        self.kind = kind
        self.dir = directory
        self.index = os.path.join(directory, index_name)

    @property
    def archive_dir(self):
        return os.path.join(self.dir, "archive")

    def _ensure(self):
        paths.ensure_dirs()
        os.makedirs(self.dir, exist_ok=True)

    def record(self, summary, *, details=None, tool=None, session_id=None,
               project_dir=None, surface=None, **extra):
        """Write one report. `extra` carries the kind-specific fields (a bug's
        `severity`, feedback's `category`)."""
        from . import __version__
        self._ensure()
        rec = dict(
            id=uuid.uuid4().hex[:12],
            kind=self.kind,
            created=time.time(),
            created_iso=time.strftime("%Y-%m-%d %H:%M:%S"),
            summary=summary,
            details=details,
            tool=tool,
            session_id=session_id,
            project_dir=project_dir,
            surface=surface,
            version=__version__,
        )
        rec.update({k: v for k, v in extra.items() if v is not None})
        stamp = rec["created_iso"].replace(" ", "_").replace(":", "-")
        path = os.path.join(self.dir, f"{stamp}_{rec['id']}.json")
        with open(path, "w") as f:
            json.dump(rec, f, indent=2)
        with open(self.index, "a") as f:
            f.write(json.dumps(rec) + "\n")
        return dict(id=rec["id"], path=path, kind=self.kind)

    def _paths(self, *, archived=False):
        d = self.archive_dir if archived else self.dir
        return sorted(glob.glob(os.path.join(d, "*.json")), reverse=True)

    def list(self, limit=100, *, archived=False):
        out = []
        for p in self._paths(archived=archived)[:limit]:
            try:
                with open(p) as f:
                    rec = json.load(f)
            except (OSError, ValueError):
                continue
            rec.setdefault("kind", self.kind)
            out.append(rec)
        return out

    def count(self, *, archived=False):
        return len(self._paths(archived=archived))

    def archive(self, report_id):
        """Move a report out of the active list (reversible — the file is kept)."""
        matches = glob.glob(os.path.join(self.dir, f"*_{report_id}.json"))
        if not matches:
            return False
        os.makedirs(self.archive_dir, exist_ok=True)
        for p in matches:
            shutil.move(p, os.path.join(self.archive_dir, os.path.basename(p)))
        return True


BUGS = Store("bug", paths.BUGS_DIR, "bugs.jsonl")
FEEDBACK = Store("feedback", paths.FEEDBACK_DIR, "feedback.jsonl")

STORES = {"bug": BUGS, "feedback": FEEDBACK}


def store(kind):
    try:
        return STORES[kind]
    except KeyError:
        raise ValueError(f"unknown report kind: {kind!r} (expected one of {', '.join(KINDS)})")


def counts():
    return {kind: s.count() for kind, s in STORES.items()}


def all_reports(limit=100):
    """Both kinds, newest first."""
    out = BUGS.list(limit) + FEEDBACK.list(limit)
    out.sort(key=lambda r: r.get("created") or 0, reverse=True)
    return out[:limit]
