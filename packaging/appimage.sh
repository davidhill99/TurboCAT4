#!/bin/sh
# Wrap dist/TurboCAT (built by PyInstaller on Linux) as one AppImage file: dist/TurboCAT-<version>-x86_64.AppImage
set -e
cd "$(dirname "$0")/.."
VERSION="$1"
APPDIR=build/TurboCAT.AppDir
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib"
cp -a dist/TurboCAT "$APPDIR/usr/lib/TurboCAT"
cat > "$APPDIR/AppRun" <<'RUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/TurboCAT/TurboCAT" "$@"
RUN
chmod +x "$APPDIR/AppRun"
cat > "$APPDIR/turbocat4.desktop" <<'DESK'
[Desktop Entry]
Type=Application
Name=TurboCAT 4
Comment=Amiga disk cataloguer
Exec=TurboCAT
Icon=turbocat
Terminal=false
Categories=Utility;
StartupWMClass=turbocat4
DESK
cp packaging/build-icons/turbocat.png "$APPDIR/turbocat.png"
[ -f build/appimagetool ] || curl -sSL -o build/appimagetool \
  https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
chmod +x build/appimagetool
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 build/appimagetool "$APPDIR" "dist/TurboCAT-$VERSION-x86_64.AppImage"
