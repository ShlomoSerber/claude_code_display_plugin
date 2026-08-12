#!/usr/bin/env bash
# Build the installable .deb. Pure-Python payload -> Architecture: all.
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
PKG="claude-code-display-plugin"
ARCH="all"
VER="$(python3 -c "import sys; sys.path.insert(0, '$HERE'); import ccdp; print(ccdp.__version__)")"
BUILD="$HERE/packaging/build"
ROOT="$BUILD/pkgroot"

echo "Building $PKG $VER"
rm -rf "$BUILD"
mkdir -p "$ROOT/DEBIAN" "$ROOT/opt/ccdp" "$ROOT/usr/bin" "$ROOT/usr/share/applications" \
         "$ROOT/usr/share/icons/hicolor/scalable/apps"

# ---- payload ----
cp -r "$HERE/ccdp"    "$ROOT/opt/ccdp/ccdp"
cp -r "$HERE/assets"  "$ROOT/opt/ccdp/assets"
cp -r "$HERE/plugin"  "$ROOT/opt/ccdp/plugin"
find "$ROOT/opt/ccdp" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

# ---- launcher on PATH ----
cat > "$ROOT/usr/bin/ccdp" <<'EOF'
#!/bin/sh
export CCDP_INSTALL_ROOT=/opt/ccdp
export PYTHONPATH=/opt/ccdp${PYTHONPATH:+:$PYTHONPATH}
exec python3 -B -m ccdp "$@"
EOF
chmod 755 "$ROOT/usr/bin/ccdp"

# ---- app icon (SVG + PNG fallbacks) ----
cp "$HERE/packaging/icon.svg" "$ROOT/usr/share/icons/hicolor/scalable/apps/ccdp.svg"
python3 "$HERE/packaging/gen_icon.py" "$ROOT/usr/share/icons/hicolor" || \
  echo "warn: PNG icon generation skipped (Pillow missing); SVG icon still shipped"

# ---- desktop launcher for the UI (filename matches the GTK app-id) ----
cat > "$ROOT/usr/share/applications/com.ccdp.display.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Claude Code Display Plugin
GenericName=Agent Display Manager
Comment=Watch and manage the displays Claude Code sessions use
Exec=ccdp ui
Icon=ccdp
Terminal=false
Categories=Development;Utility;
Keywords=claude;display;vnc;browser;agent;
StartupNotify=true
StartupWMClass=ccdp
EOF

# ---- control ----
INSTALLED_KB="$(du -sk "$ROOT/opt" "$ROOT/usr" | awk '{s+=$1} END{print s}')"
cat > "$ROOT/DEBIAN/control" <<EOF
Package: $PKG
Version: $VER
Section: utils
Priority: optional
Architecture: $ARCH
Depends: python3 (>= 3.9), python3-pil, python3-gi, gir1.2-gtk-3.0, gir1.2-webkit2-4.1, xvfb, x11-utils, xdotool, scrot, x11vnc, xdg-utils, novnc, websockify
Recommends: google-chrome-stable | chromium | chromium-browser
Suggests: python3-mss, bubblewrap
Installed-Size: $INSTALLED_KB
Maintainer: Claude Code Display Plugin <pending@example.com>
Description: Sandboxed displays for Claude Code sessions
 Gives every Claude Code session, per project directory, a virtual display it
 can see (screenshots) and drive with human-like mouse and keyboard input, plus
 a local dashboard to watch those displays live. After installing, run 'ccdp ui'
 and, once Claude Code is installed, click "Apply plugin".
EOF

# ---- maintainer scripts ----
cat > "$ROOT/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi
echo ""
echo "Claude Code Display Plugin installed."
echo "  Dashboard:            ccdp ui"
echo "  Check dependencies:   ccdp doctor"
echo "  Apply plugin (after Claude Code is installed): ccdp apply-plugin"
echo ""
exit 0
EOF
chmod 755 "$ROOT/DEBIAN/postinst"

cat > "$ROOT/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
# User data under ~/.local/state/ccdp is intentionally left in place.
exit 0
EOF
chmod 755 "$ROOT/DEBIAN/postrm"

# ---- build ----
mkdir -p "$HERE/dist"
OUT="$HERE/dist/${PKG}_${VER}_${ARCH}.deb"
fakeroot dpkg-deb --build --root-owner-group "$ROOT" "$OUT" >/dev/null
echo "Built: $OUT"
dpkg-deb --info "$OUT" | sed -n '1,20p'
