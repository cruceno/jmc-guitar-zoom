#!/usr/bin/env bash
# Build dist/JMC_Guitar_Zoom-<version>-x86_64.AppImage from the PyInstaller onedir bundle.
# Run from anywhere: bash packaging/linux/build_appimage.sh   (needs uv and the `build` group: uv sync --group build)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

# Pinned appimagetool release; the download is checked against this SHA-256 before it is ever run.
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage"
APPIMAGETOOL_SHA256="ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0"

NAME="jmc-guitar-zoom"
VERSION="$(uv run python -c 'import jmc_guitar_zoom; print(jmc_guitar_zoom.__version__)')"
OUT="dist/JMC_Guitar_Zoom-${VERSION}-x86_64.AppImage"
APPDIR="build/AppDir"
TOOLS="build/tools"

echo "==> PyInstaller"
uv run pyinstaller --noconfirm --workpath build --distpath dist packaging/jmc-guitar-zoom.spec

echo "==> AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib" "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -a "dist/$NAME" "$APPDIR/usr/lib/$NAME"
cp packaging/icons/app-icon.png "$APPDIR/$NAME.png"
cp packaging/icons/app-icon.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/$NAME.png"
ln -s "$NAME.png" "$APPDIR/.DirIcon"
cat > "$APPDIR/$NAME.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=JMC Guitar Zoom
Comment=Unofficial editor for the Zoom A1 FOUR pedal
Exec=$NAME
Icon=$NAME
Categories=AudioVideo;Audio;Music;
Terminal=false
StartupWMClass=$NAME
DESKTOP
cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/jmc-guitar-zoom/jmc-guitar-zoom" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

echo "==> appimagetool"
mkdir -p "$TOOLS"
TOOL="$TOOLS/appimagetool-x86_64.AppImage"
if [ ! -f "$TOOL" ] || ! echo "$APPIMAGETOOL_SHA256  $TOOL" | sha256sum -c --status -; then
  rm -f "$TOOL"
  curl -fsSL --retry 3 -o "$TOOL" "$APPIMAGETOOL_URL"
  echo "$APPIMAGETOOL_SHA256  $TOOL" | sha256sum -c -
fi
chmod +x "$TOOL"

echo "==> AppImage"
mkdir -p dist
rm -f "$OUT"
# No FUSE needed (CI containers): the tool and the result are extracted and run instead of mounted.
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$TOOL" --no-appstream "$APPDIR" "$OUT"
chmod +x "$OUT"
echo "built $OUT ($(du -h "$OUT" | cut -f1))"
