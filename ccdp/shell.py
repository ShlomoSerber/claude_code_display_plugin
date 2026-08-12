"""Native window shell: a real GTK application with a GTK HeaderBar (native title,
native window controls, OS theme and font) embedding the dashboard in a WebKitGTK
webview. Prefers GTK4 + WebKit 6.0; works on GTK3 + WebKit2 4.1. If neither is
usable, the caller falls back to a Chrome app window.
"""
import importlib


def _versions(ns):
    try:
        import gi
        return set(gi.Repository.get_default().enumerate_versions(ns))
    except Exception:
        return set()


def pick():
    """Return (gtk_version, webkit_namespace, webkit_version) or None."""
    gtk = _versions("Gtk")
    if "4.0" in gtk and "6.0" in _versions("WebKit"):
        return ("4.0", "WebKit", "6.0")
    if "3.0" in gtk:
        wk = _versions("WebKit2")
        if "4.1" in wk:
            return ("3.0", "WebKit2", "4.1")
        if "4.0" in wk:
            return ("3.0", "WebKit2", "4.0")
    return None


def available():
    return pick() is not None


def run_gtk(url, title="Claude Code Display Plugin"):
    """Blocking. Show the native window; return True once the user closes it.
    Raises on setup failure so the caller can fall back to another window."""
    combo = pick()
    if not combo:
        raise RuntimeError("no GTK+WebKit combination available")
    gtkver, wkns, wkver = combo

    import gi
    gi.require_version("Gtk", gtkver)
    gi.require_version(wkns, wkver)
    from gi.repository import Gio, Gtk
    WebKit = importlib.import_module("gi.repository." + wkns)

    shown = {"ok": False}

    class App(Gtk.Application):
        def __init__(self):
            super().__init__(application_id="com.ccdp.display",
                             flags=Gio.ApplicationFlags.NON_UNIQUE)

        def do_activate(self):
            win = Gtk.ApplicationWindow(application=self)
            win.set_title(title)
            win.set_default_size(1200, 820)
            try:
                win.set_icon_name("ccdp")
            except Exception:
                pass
            header = Gtk.HeaderBar()
            if gtkver == "3.0":
                header.set_show_close_button(True)
                header.set_title(title)
            win.set_titlebar(header)

            view = WebKit.WebView()
            view.load_uri(url)
            if gtkver == "4.0":
                win.set_child(view)
                win.present()
            else:
                win.add(view)
                win.show_all()
            shown["ok"] = True

    App().run(None)
    if not shown["ok"]:
        raise RuntimeError("GTK window failed to initialize")
    return True
