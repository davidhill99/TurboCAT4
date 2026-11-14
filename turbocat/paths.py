"""Where TurboCAT keeps its own files, in each system's normal place.

Linux keeps the places TurboCAT has always used, so nothing moves on an existing install:
    catalogue  ~/turbocat.db
    data       ~/.local/share/turbocat   (logs of repairs and renames, FS-UAE's files)
    cache      ~/.cache/turbocat         (pictures, disk lists, Aminet files, sounds)
Windows: the catalogue and data in AppData\\Roaming\\TurboCAT, the cache in AppData\\Local\\TurboCAT.
macOS:   the catalogue and data in Library/Application Support/TurboCAT, the cache in Library/Caches.
Repaired and tidied copies go in TurboCAT/Repaired in the home folder everywhere: they're the
user's own disks, so they belong where people look for files, not in a hidden folder.
"""
import os
import sys


def system():
    """'windows', 'mac' or 'linux'."""
    if sys.platform.startswith("win"):
        return "windows"
    return "mac" if sys.platform == "darwin" else "linux"


def _home(*parts):
    return os.path.join(os.path.expanduser("~"), *parts)


def data_dir():
    s = system()
    if s == "windows":
        return os.path.join(os.environ.get("APPDATA") or _home("AppData", "Roaming"), "TurboCAT")
    if s == "mac":
        return _home("Library", "Application Support", "TurboCAT")
    return _home(".local", "share", "turbocat")


def cache_dir():
    s = system()
    if s == "windows":
        return os.path.join(os.environ.get("LOCALAPPDATA") or _home("AppData", "Local"), "TurboCAT", "Cache")
    if s == "mac":
        return _home("Library", "Caches", "TurboCAT")
    return _home(".cache", "turbocat")


def default_db():
    """The catalogue TurboCAT opens unless told otherwise."""
    return _home("turbocat.db") if system() == "linux" else os.path.join(data_dir(), "turbocat.db")


def repaired_dir():
    return _home("TurboCAT", "Repaired")


def no_window():
    """subprocess options so a helper program (lha, xdms, 7z) doesn't flash up a black console
    window on Windows; nothing elsewhere."""
    return {"creationflags": 0x08000000} if system() == "windows" else {}       # CREATE_NO_WINDOW


def detached():
    """subprocess options for a program that should keep running when TurboCAT closes."""
    if system() == "windows":
        return {"creationflags": 0x00000008 | 0x00000200}     # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    return {"start_new_session": True}


def shown(path):
    """A path as people read it: the home folder as ~ (on every system)."""
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path.startswith(home) else path
