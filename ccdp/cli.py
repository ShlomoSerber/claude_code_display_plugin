"""`ccdp` command-line entrypoint. Subcommands wire the plugin's hook, the MCP
server, the dashboard UI, and housekeeping together."""
import argparse
import json
import shutil
import sys

from . import __version__, paths


def _doctor():
    from . import capture, claudecli, sandbox, surfaces
    checks = [
        ("Xvfb", shutil.which("Xvfb")),
        ("xdotool", shutil.which("xdotool")),
        ("scrot", shutil.which("scrot")),
        ("x11vnc", shutil.which("x11vnc")),
        ("xdpyinfo", shutil.which("xdpyinfo")),
        ("browser", surfaces.find_browser()),
        ("Pillow (PIL)", "yes" if capture.available() else None),
        ("claude", claudecli.find()),
        ("bwrap (sandbox)", shutil.which("bwrap")),
    ]
    print(f"Claude Code Display Plugin {__version__}\n")
    ok = True
    for name, val in checks:
        mark = "OK " if val else "-- "
        if name not in ("claude", "bwrap (sandbox)") and not val:
            ok = False
        print(f"  [{mark}] {name:<16} {val or 'not found'}")
    print(f"\n  sandbox: {'enabled' if sandbox.enabled() else 'off (default; set CCDP_SANDBOX=1 to opt in)'}")
    print(f"  state dir: {paths.STATE_DIR}")
    if not ok:
        print("\nMissing a required dependency above. Install the .deb dependencies.")
    return 0 if ok else 1


def _surfaces():
    from . import registry, surfaces
    data = registry.all_surfaces()
    if not data:
        print("(no active surfaces)")
        return 0
    for r in data.values():
        alive = surfaces._alive(r)
        print(f"{r['key']}  {r['display']}  pss={surfaces.pss_mb(r)}MB  "
              f"{'live' if alive else 'dead'}  {r['project_dir']}")
    return 0


def _reports(kind, limit, as_json):
    from . import reports
    items = reports.all_reports(limit) if kind == "all" else reports.store(kind).list(limit)
    if as_json:
        print(json.dumps(items, indent=2))
        return 0
    if not items:
        print("(nothing filed — sessions record these with record_bug / record_feedback)")
        return 0
    for r in items:
        tag = r.get("severity") if r.get("kind") == "bug" else r.get("category")
        print(f"[{(r.get('kind') or '?').upper():<8}] {r.get('created_iso','')}  "
              f"{r.get('id','')}  ({tag or '-'})")
        print(f"  {r.get('summary','').strip()}")
        if r.get("project_dir"):
            print(f"  dir: {r['project_dir']}")
        if r.get("details"):
            body = r["details"].strip().splitlines()
            for line in body[:12]:
                print(f"  | {line}")
            if len(body) > 12:
                print(f"  | ... ({len(body) - 12} more lines — see the JSON in {paths.STATE_DIR})")
        print()
    print("Actioned? Clear them: ccdp archive <id>... | ccdp archive --all "
          "(files move to archive/, nothing is deleted)")
    return 0


def _archive(ids, archive_all, kind):
    """Clear reports that have been actioned. The point of the queue is to empty
    it — a report that has been fixed or implemented should stop being shown."""
    from . import reports
    stores = list(reports.STORES.values()) if kind == "all" else [reports.store(kind)]
    if archive_all:
        n = 0
        for st in stores:
            for r in st.list(1000):
                if st.archive(r["id"]):
                    print(f"archived {st.kind} {r['id']}  {r.get('summary','').strip()[:70]}")
                    n += 1
        print(f"({n} archived, queue now empty)" if n else "(nothing active to archive)")
        return 0
    if not ids:
        print("give report ids, or --all to clear the queue "
              "(ids come from `ccdp reports`)")
        return 2
    missing = []
    for rid in ids:
        if any(st.archive(rid) for st in stores):
            print(f"archived {rid}")
        else:
            missing.append(rid)
    for rid in missing:
        print(f"no active report {rid} (already archived?)")
    return 1 if missing else 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="ccdp", description="Claude Code Display Plugin")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("mcp", help="run the stdio MCP server (used by the plugin)")
    ui = sub.add_parser("ui", help="run the display dashboard")
    ui.add_argument("--port", type=int, default=8776)
    ui.add_argument("--no-open", action="store_true", help="don't open a browser")
    sub.add_parser("doctor", help="check dependencies")
    sub.add_parser("apply-plugin", help="register the plugin with Claude Code")
    sub.add_parser("remove-plugin", help="unregister the plugin from Claude Code")
    sub.add_parser("plugin-status", help="print plugin/claude status as JSON")
    sub.add_parser("surfaces", help="list active surfaces")
    rp = sub.add_parser("reports", help="show the bug reports and feedback sessions have filed")
    rp.add_argument("kind", nargs="?", default="all", choices=["all", "bug", "feedback"])
    rp.add_argument("--limit", type=int, default=50)
    rp.add_argument("--json", action="store_true", dest="as_json")
    ar = sub.add_parser("archive", help="clear reports that have been actioned "
                                        "(moves them to archive/, does not delete)")
    ar.add_argument("ids", nargs="*", help="report ids from `ccdp reports`")
    ar.add_argument("--all", action="store_true", dest="all_reports",
                    help="archive every active report")
    ar.add_argument("--kind", default="all", choices=["all", "bug", "feedback"])
    rc = sub.add_parser("recover", help="unstick a surface by key (refocus + repaint)")
    rc.add_argument("key")
    rc.add_argument("--restart-browser", action="store_true")
    sub.add_parser("session-start", help="hook: housekeeping at session start")
    sub.add_parser("reap", help="close idle surfaces")
    c = sub.add_parser("close", help="close a surface by key")
    c.add_argument("key")
    sub.add_parser("version", help="print version")

    args = p.parse_args(argv)
    paths.ensure_dirs()

    if args.cmd == "mcp":
        from . import mcp_server
        mcp_server.main()
        return 0
    if args.cmd == "ui":
        from . import dashboard
        dashboard.serve(port=args.port, open_browser=not args.no_open)
        return 0
    if args.cmd == "doctor":
        return _doctor()
    if args.cmd == "apply-plugin":
        from . import applyplugin
        res = applyplugin.apply()
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1
    if args.cmd == "remove-plugin":
        from . import applyplugin
        res = applyplugin.remove()
        print(json.dumps(res, indent=2))
        return 0
    if args.cmd == "plugin-status":
        from . import applyplugin
        print(json.dumps(applyplugin.status(), indent=2))
        return 0
    if args.cmd == "surfaces":
        return _surfaces()
    if args.cmd == "reports":
        return _reports(args.kind, args.limit, args.as_json)
    if args.cmd == "archive":
        return _archive(args.ids, args.all_reports, args.kind)
    if args.cmd == "recover":
        from . import surfaces
        info = surfaces.recover(args.key, restart_browser=args.restart_browser)
        for step in info["steps"]:
            print(f"- {step}")
        return 0
    if args.cmd == "session-start":
        from . import surfaces
        try:
            surfaces.reap_idle()
        except Exception:
            pass
        return 0
    if args.cmd == "reap":
        from . import surfaces
        surfaces.reap_idle()
        return 0
    if args.cmd == "close":
        from . import surfaces
        surfaces.close(args.key)
        return 0
    if args.cmd == "version":
        print(__version__)
        return 0
    p.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
