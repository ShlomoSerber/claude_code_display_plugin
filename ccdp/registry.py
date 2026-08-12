"""Surface registry — the shared source of truth across the (ephemeral, per-session)
MCP servers and the (long-lived) dashboard. A JSON file guarded by an flock, so
the first session in a directory creates a surface and later ones attach to it.
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


def upsert(key, record):
    with _locked():
        data = _read()
        rec = data.get(key, {})
        rec.update(record)
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
