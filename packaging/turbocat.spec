# PyInstaller recipe for TurboCAT: pyinstaller packaging/turbocat.spec
# Makes dist/TurboCAT/ (Windows and Linux) or dist/TurboCAT.app (macOS): TurboCAT with Python, Qt
# and its own icons and TurboView inside. Helper programs fetched by the build go in
# packaging/bundle/bin (7-Zip, xdms: found first by turbocat/tools.py) and packaging/bundle/lib
# (libopenmpt: found first by turbocat/music.py).
import glob
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

HERE = os.path.abspath(SPECPATH)
ROOT = os.path.dirname(HERE)
HELPERS = os.path.join(HERE, "bundle")      # (not BUNDLE: that is PyInstaller's macOS app step)
ICONS = os.path.join(HERE, "build-icons")

sys.path.insert(0, ROOT)
from turbocat import VERSION  # noqa: E402

datas = [(os.path.join(ROOT, "turbocat", "icons"), os.path.join("turbocat", "icons")),
         (os.path.join(ROOT, "turbocat", "amiga", "TurboView"), os.path.join("turbocat", "amiga"))]
binaries = ([(p, "bin") for p in glob.glob(os.path.join(HELPERS, "bin", "*"))]
            + [(p, os.path.join("turbocat", "lib")) for p in glob.glob(os.path.join(HELPERS, "lib", "*"))])
# amitools' vamos (an AmigaOS emulator for the command line) isn't used by TurboCAT
hidden = collect_submodules("amitools", filter=lambda n: not n.startswith("amitools.vamos")) + [
    "lhafile", "PySide6.QtSvg", "PySide6.QtMultimedia"]
icon = os.path.join(ICONS, "turbocat.ico" if sys.platform.startswith("win") else "turbocat.icns")
icon = icon if os.path.exists(icon) else None

a = Analysis([os.path.join(HERE, "turbocat_app.py")], pathex=[ROOT], datas=datas, binaries=binaries,
             hiddenimports=hidden, excludes=["tkinter", "test", "amitools.vamos"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="TurboCAT", console=False, icon=icon)
coll = COLLECT(exe, a.binaries, a.datas, name="TurboCAT")
if sys.platform == "darwin":
    app = BUNDLE(coll, name="TurboCAT.app", icon=icon, bundle_identifier="io.github.davidhill99.turbocat",
                 version=VERSION.split("-")[0],
                 info_plist={"CFBundleName": "TurboCAT", "CFBundleDisplayName": "TurboCAT 4",
                             "CFBundleShortVersionString": VERSION, "NSHighResolutionCapable": True})
