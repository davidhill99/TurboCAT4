"""Finding the helper programs TurboCAT runs (lha, xdms, 7z).

On Linux they come from the system's package manager and are found on the PATH. The Windows and
macOS packages of TurboCAT carry their own copies in a "bin" folder (Windows has no standard way to
install them, and a Mac only does with Homebrew), so that folder is looked in first:
  - beside the turbocat package:      turbocat/bin/<name>[.exe]
  - inside a frozen app (PyInstaller): <app>/bin/<name>[.exe]
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def bundled_dirs():
    dirs = [os.path.join(HERE, "bin")]
    base = getattr(sys, "_MEIPASS", None)
    if base:
        dirs.insert(0, os.path.join(base, "bin"))
    return dirs


def bundled(name):
    """The copy of a helper program that came with TurboCAT, or None."""
    for d in bundled_dirs():
        for n in (name, name + ".exe"):
            p = os.path.join(d, n)
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return p
    return None


def which(name):
    """Where a helper program is: TurboCAT's own copy first, then the system's. None if neither."""
    return bundled(name) or shutil.which(name)
