"""Identify disks by their checksum, whatever the files are called.

A disk image's SHA-1 is looked up in the TOSEC catalogue of Amiga disks: the copy libretro
publishes on GitHub (about 44,000 disks, downloaded once with the user's agreement and kept in
~/.cache/turbocat), plus any TOSEC .dat files in the folders TurboCAT has scanned. A match gives
the disk's proper collector name, e.g. "Disk1.adf" is
"Superfrog (1993)(Team 17)(Disk 1 of 4)[cr CSL][t +6 SCX].adf".

When nothing matches and the file name says nothing ("Disk1.adf"), the folder it is in may:
that is offered as a guess only, clearly marked, and never used to rename anything.
"""
import json
import os
import re
import time
import urllib.request

from .pictures import CACHE, USER_AGENT, Stopped

LIST_URL = ("https://raw.githubusercontent.com/libretro/libretro-database/master/"
            "metadat/tosec/Commodore%20-%20Amiga.dat")
LIST_TITLE = "the TOSEC list of Amiga disks (libretro)"
DAT_PATH = os.path.join(CACHE, "tosec-amiga.dat")
INDEX_PATH = os.path.join(CACHE, "tosec-amiga.json")
CONSENT = "identify_online"          # meta: the user agreed to download the list
MAX_AGE = 60 * 86400                 # fetch a fresh copy after two months

_ROM = re.compile(r'rom \( name "((?:[^"\\]|\\.)*)" size \d+[^)]*?sha1 ([0-9A-Fa-f]{40})')
GENERIC_FILE = re.compile(r"^(disk|disc|df|image|img|adf|untitled|unknown|noname|new|copy of|"
                          r"backup|game|track)[\s_\-]*\d*[a-z]?$", re.I)
GENERIC_FOLDER = {"amiga", "adf", "adfs", "disks", "disk", "floppies", "floppy", "games", "game",
                  "downloads", "download", "dropbox", "documents", "desktop", "home", "misc",
                  "new", "old", "stuff", "temp", "tmp", "fs-uae", "amiberry", "roms", "files"}

_index = None          # sha1 -> name, from the downloaded list


def have_list():
    return os.path.exists(INDEX_PATH) or os.path.exists(DAT_PATH)


def list_is_old():
    try:
        return time.time() - os.path.getmtime(DAT_PATH) > MAX_AGE
    except OSError:
        return True


def download(stop=lambda: False, progress=None):
    """Fetch the list (about 12 MB) in pieces so it can be stopped; then index it."""
    req = urllib.request.Request(LIST_URL, headers={"User-Agent": USER_AGENT})
    os.makedirs(CACHE, exist_ok=True)
    with urllib.request.urlopen(req, timeout=20) as r, open(DAT_PATH + ".part", "wb") as out:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            if stop():
                raise Stopped()
            chunk = r.read(1 << 17)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    os.replace(DAT_PATH + ".part", DAT_PATH)
    _build_index()


def _build_index():
    global _index
    with open(DAT_PATH, encoding="utf-8", errors="replace") as f:
        text = f.read()
    index = {sha.lower(): name.replace('\\"', '"') for name, sha in _ROM.findall(text)}
    with open(INDEX_PATH + ".part", "w") as f:
        json.dump(index, f)
    os.replace(INDEX_PATH + ".part", INDEX_PATH)
    _index = index


def index():
    """sha1 -> TOSEC name from the downloaded list ({} if it hasn't been downloaded)."""
    global _index
    if _index is None:
        try:
            if os.path.exists(DAT_PATH) and (not os.path.exists(INDEX_PATH) or
                                             os.path.getmtime(DAT_PATH) > os.path.getmtime(INDEX_PATH)):
                _build_index()
            else:
                with open(INDEX_PATH) as f:
                    _index = json.load(f)
        except (OSError, ValueError):
            _index = {}
    return _index


def identify(rows_by_top, lists=()):
    """{top id: (TOSEC name, where the name came from)} for items whose disk is known.
    rows_by_top: {top id: [media rows of the item and everything inside it]};
    lists: datlists.CollectionList objects (TOSEC .dat files found in the scanned folders)."""
    known = index()
    dats = [l for l in lists if l.kind == "dat"]
    out = {}
    for top, rows in rows_by_top.items():
        for r in rows:
            sha = (r["sha1"] or "").lower()
            if not sha:
                continue
            for lst in dats:
                if sha in lst.by_sha1:
                    out[top] = (lst.by_sha1[sha], lst.title)
                    break
            else:
                if sha in known:
                    out[top] = (known[sha], LIST_TITLE)
            if top in out:
                break
    return out


def stem(name):
    """A TOSEC rom name without its extension."""
    return re.sub(r"\.(adf|adz|dms|ipf|zip|lha|exe)$", "", name, flags=re.I)


def guess(path):
    """For a file whose name says nothing ("Disk1.adf"), the folder it is in, if that does.
    Returns the folder name or ""."""
    base = os.path.splitext(os.path.basename(path))[0]
    if not GENERIC_FILE.match(base.strip()):
        return ""
    folder = os.path.basename(os.path.dirname(path))
    return "" if not folder or folder.lower() in GENERIC_FOLDER else folder


# ---------------------------------------------------------------- renaming files

def rename_plan(items):
    """[(item, current path, new path)] for identified items whose file name differs from the
    TOSEC name. The extension of the actual file is kept (a ZIP stays a .zip)."""
    plan, taken = [], set()
    for it in items:
        name = getattr(it, "tosec_name", "")
        if not name or it.type in ("Folder",) or not os.path.isfile(it.path):
            continue
        folder, current = os.path.split(it.path)
        ext = os.path.splitext(current)[1]
        new = _safe(stem(name)) + ext
        target = os.path.join(folder, new)
        if new == current or target in taken:
            continue
        taken.add(target)
        plan.append((it, it.path, target))
    return plan


def _safe(name):
    """A file name every system accepts."""
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip().rstrip(".")[:200]


def for_catalogue(cat):
    """identify() for every item in the catalogue: {top id: (name, list title)}."""
    from . import datlists
    top = cat.top_ids()
    rows_by_top = {}
    for r in cat.db.execute("SELECT id, parent_id, source, sha1 FROM media"):
        rows_by_top.setdefault(top.get(r["id"], r["id"]), []).append(r)
    folders = {os.path.dirname(r["source"]) for rows in rows_by_top.values() for r in rows[:1]}
    return identify(rows_by_top, datlists.lists_in(folders))
