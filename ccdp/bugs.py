"""Bug store. Claude calls the `record_bug` MCP tool when the program misbehaves
in a session; reports land here as JSON for the user to hand off. Deliberately
simple and local — no network."""
import glob
import json
import os
import time
import uuid

from . import paths


def record(summary, *, details=None, tool=None, session_id=None, project_dir=None,
           surface=None, severity="normal"):
    paths.ensure_dirs()
    bug = dict(
        id=uuid.uuid4().hex[:12],
        created=time.time(),
        created_iso=time.strftime("%Y-%m-%d %H:%M:%S"),
        summary=summary,
        details=details,
        tool=tool,
        session_id=session_id,
        project_dir=project_dir,
        surface=surface,
        severity=severity,
    )
    path = os.path.join(paths.BUGS_DIR, f"{bug['created_iso'].replace(' ', '_').replace(':', '-')}_{bug['id']}.json")
    with open(path, "w") as f:
        json.dump(bug, f, indent=2)
    with open(os.path.join(paths.BUGS_DIR, "bugs.jsonl"), "a") as f:
        f.write(json.dumps(bug) + "\n")
    return dict(id=bug["id"], path=path)


def list_bugs(limit=100):
    files = sorted(glob.glob(os.path.join(paths.BUGS_DIR, "*.json")), reverse=True)
    out = []
    for p in files[:limit]:
        try:
            with open(p) as f:
                out.append(json.load(f))
        except (OSError, ValueError):
            continue
    return out
