"""Surface registry — the shared source of truth across the (ephemeral, per-session)
MCP servers and the (long-lived) dashboard. A JSON file guarded by an flock, so
the first session in a directory creates a surface and later ones attach to it.

Keys: a workspace's first surface is keyed by `paths.project_key(dir)`; extra
surfaces for the same workspace take `<key>-2`, `<key>-3` and so on. `reserve()`
hands out a key *and* an X display number in one locked operation, because two
parallel lanes creating a display at the same moment would otherwise both read
the same "used" set and both pick `:101`.
"""
import contextlib
import fcntl
import json
import os
import time

from . import paths


@contextlib.contextmanager
def _locked():
    paths.ensure_dirs()
    f = open(paths.SURFACES_LOCK, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def _read():
    try:
        with open(paths.SURFACES_JSON) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _write(data):
    tmp = paths.SURFACES_JSON + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, paths.SURFACES_JSON)


def all_surfaces():
    with _locked():
        return _read()


def get(key):
    with _locked():
        return _read().get(key)


def upsert(key, record, *, drop=()):
    with _locked():
        data = _read()
        rec = data.get(key, {})
        rec.update(record)
        for field in drop:
            rec.pop(field, None)
        rec["updated"] = time.time()
        data[key] = rec
        _write(data)
        return rec


def touch(key):
    with _locked():
        data = _read()
        if key in data:
            data[key]["last_active"] = time.time()
            _write(data)


def remove(key):
    with _locked():
        data = _read()
        rec = data.pop(key, None)
        _write(data)
        return rec


def used_displays():
    with _locked():
        return {r.get("display") for r in _read().values() if r.get("display")}


class Full(RuntimeError):
    """Raised by reserve() when the concurrent-display cap is already reached."""


def reserve(base, record, *, choose_display, cap=None, is_live=None):
    """Atomically claim the next free key in the `base`, `base-2`, `base-3`...
    series together with an X display number, and write a placeholder record.

    `choose_display(used)` returns a display number given the ones already taken.
    `cap` bounds how many surfaces may exist at once; `is_live(rec)` decides which
    records count towards it. Both the count and the allocation happen inside the
    one lock, so concurrent creators can neither exceed the cap nor collide on a
    display number. The record is marked `provisioning` until the caller has its
    processes up.
    """
    with _locked():
        data = _read()
        if cap:
            live = [r for r in data.values() if (is_live(r) if is_live else True)]
            if len(live) >= int(cap):
                raise Full(
                    f"display cap reached: {len(live)} of {int(cap)} displays are already "
                    "running (each one is a browser, roughly 0.9GB). Release one you no "
                    "longer need, or raise the cap with CCDP_MAX_DISPLAYS.")
        key = None
        for n in range(1, 65):
            candidate = base if n == 1 else f"{base}-{n}"
            if candidate not in data:
                key = candidate
                break
        if key is None:
            raise Full(f"too many surfaces already keyed under {base}")
        now = time.time()
        rec = dict(record, key=key, display=choose_display(
            {r.get("display") for r in data.values() if r.get("display")}),
            provisioning=now, created=now, updated=now, last_active=now)
        data[key] = rec
        _write(data)
        return rec


def for_dir(project_dir):
    """Every surface whose workspace is exactly `project_dir`, oldest first."""
    real = os.path.realpath(project_dir)
    with _locked():
        recs = [r for r in _read().values()
                if r.get("project_dir") and os.path.realpath(r["project_dir"]) == real]
    return sorted(recs, key=lambda r: r.get("created") or 0)
