"""Identify disks by their checksum, whatever the files are called.

A disk image's SHA-1 is looked up in the TOSEC catalogue of Amiga disks. The full set comes from
TOSEC's own DAT pack (tosecdev.org: about 100 MB, of which only the 68 Amiga floppy lists are kept,
about 98,000 disks: games, applications, coverdisks, demos, diskmags, collections, Workbench...).
An older, smaller copy of the games list that libretro publishes on GitHub is still read if it was
downloaded before. Both are fetched only with the user's agreement and kept in ~/.cache/turbocat,
plus any TOSEC .dat files in the folders TurboCAT has scanned. A match gives the disk's proper
collector name, e.g. "Disk1.adf" is "Superfrog (1993)(Team 17)(Disk 1 of 4)[cr CSL][t +6 SCX].adf",
and the list it is in ("Coverdisks", "Games", "Demos - Music"...).

When nothing matches and the file name says nothing ("Disk1.adf"), the folder it is in may:
that is offered as a guess only, clearly marked, and never used to rename anything.
"""
import html
import json
import os
import re
import shutil
import time
import urllib.request
import zipfile

from .pictures import CACHE, USER_AGENT, Stopped

LIST_URL = ("https://raw.githubusercontent.com/libretro/libretro-database/master/"
            "metadat/tosec/Commodore%20-%20Amiga.dat")
LIST_TITLE = "the TOSEC list of Amiga disks (libretro)"
DAT_PATH = os.path.join(CACHE, "tosec-amiga.dat")
INDEX_PATH = os.path.join(CACHE, "tosec-amiga.json")
CONSENT = "identify_online"          # meta: the user agreed to download the libretro list
# TOSEC's own lists: the DAT pack of the newest release, found on its downloads page.
TOSEC_PAGE = "https://tosecdev.org/downloads"
TOSEC_PACK = ("https://tosecdev.org/downloads/category/59-2025-03-13"
              "?download=117:tosec-dat-pack-complete-4743-tosec-v2025-03-13")     # if the page can't be read
TOSEC_TITLE = "TOSEC's lists of Amiga disks"
TOSEC_DIR = os.path.join(CACHE, "tosec")
TOSEC_INDEX = os.path.join(CACHE, "tosec-index.json")
TOSEC_CONSENT = "identify_tosec"     # meta: the user agreed to download TOSEC's DAT pack
TOSEC_KEEP = "TOSEC/Commodore Amiga - "     # the Amiga floppy lists in the pack
PACK_SIZE_MB = 100
MAX_AGE = 60 * 86400                 # fetch a fresh copy after two months
TOSEC_MAX_AGE = 180 * 86400          # TOSEC releases come once or twice a year
_DAT_ROM = re.compile(r'<rom name="([^"]+)"[^>]*?sha1="([0-9A-Fa-f]{40})"')

_ROM = re.compile(r'rom \( name "((?:[^"\\]|\\.)*)" size \d+[^)]*?sha1 ([0-9A-Fa-f]{40})')
GENERIC_FILE = re.compile(r"^(disk|disc|df|image|img|adf|untitled|unknown|noname|new|copy of|"
                          r"backup|game|track)[\s_\-]*\d*[a-z]?$", re.I)
GENERIC_FOLDER = {"amiga", "adf", "adfs", "disks", "disk", "floppies", "floppy", "games", "game",
                  "downloads", "download", "dropbox", "documents", "desktop", "home", "misc",
                  "new", "old", "stuff", "temp", "tmp", "fs-uae", "amiberry", "roms", "files"}

_index = None          # sha1 -> name, from the downloaded list
_tosec = None          # sha1 -> (name, list), from TOSEC's own lists


def have_list():
    return have_tosec() or os.path.exists(INDEX_PATH) or os.path.exists(DAT_PATH)


def have_tosec():
    return os.path.isdir(TOSEC_DIR) and any(n.endswith(".dat") for n in os.listdir(TOSEC_DIR))


def list_is_old():
    try:
        return time.time() - os.path.getmtime(DAT_PATH) > MAX_AGE
    except OSError:
        return True


def tosec_is_old():
    try:
        return time.time() - os.path.getmtime(TOSEC_INDEX) > TOSEC_MAX_AGE
    except OSError:
        return True


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(2 << 20).decode("utf-8", "replace")


def tosec_pack_url():
    """The DAT pack of TOSEC's newest release, read from its downloads page (or the last one known)."""
    try:
        page = _get(TOSEC_PAGE)
        releases = re.findall(r'href="(/downloads/category/\d+-(\d{4}-\d{2}-\d{2}))"', page)
        if releases:
            path = max(releases, key=lambda r: r[1])[0]
            page = _get("https://tosecdev.org" + path)
            m = re.search(r'href="([^"]*\?download=[^"]*dat-pack-complete[^"]*)"', page)
            if m:
                return "https://tosecdev.org" + html.unescape(m.group(1))
    except Exception:
        pass
    return TOSEC_PACK


def download_tosec(stop=lambda: False, progress=None):
    """Fetch TOSEC's DAT pack (about 100 MB) in pieces so it can be stopped, keep only the Amiga
    floppy lists (about 35 MB), delete the pack, and index them."""
    os.makedirs(CACHE, exist_ok=True)
    part = os.path.join(CACHE, "tosec-pack.zip.part")
    req = urllib.request.Request(tosec_pack_url(), headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as r, open(part, "wb") as out:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                if stop():
                    raise Stopped()
                chunk = r.read(1 << 18)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        new = TOSEC_DIR + ".new"
        shutil.rmtree(new, ignore_errors=True)
        os.makedirs(new)
        with zipfile.ZipFile(part) as z:
            for info in z.infolist():
                name = info.filename
                if not name.startswith(TOSEC_KEEP) or not name.endswith(".dat") or "/" in name[len("TOSEC/"):]:
                    continue
                with z.open(info) as src, open(os.path.join(new, os.path.basename(name)), "wb") as dst:
                    shutil.copyfileobj(src, dst)
        if not os.listdir(new):
            raise ValueError("the TOSEC pack has no Amiga lists")
        shutil.rmtree(TOSEC_DIR, ignore_errors=True)
        os.replace(new, TOSEC_DIR)
    finally:
        try:
            os.remove(part)
        except OSError:
            pass
    _build_tosec()


def list_name(file_name):
    """'Commodore Amiga - Coverdisks - [ADF] (TOSEC-v2024-12-14_CM).dat' -> 'Coverdisks - [ADF]'."""
    return re.sub(r"^Commodore Amiga - | \(TOSEC-v[^)]*\)\.dat$", "", file_name)


def _build_tosec():
    global _tosec
    index = {}
    for f in sorted(os.listdir(TOSEC_DIR)):
        if not f.endswith(".dat"):
            continue
        with open(os.path.join(TOSEC_DIR, f), encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        lst = list_name(f)
        for name, sha in _DAT_ROM.findall(text):
            index.setdefault(sha.lower(), (html.unescape(name), lst))
    with open(TOSEC_INDEX + ".part", "w") as fh:
        json.dump(index, fh)
    os.replace(TOSEC_INDEX + ".part", TOSEC_INDEX)
    _tosec = index


def tosec_index():
    """sha1 -> (TOSEC name, list) from TOSEC's own lists ({} if not downloaded)."""
    global _tosec
    if _tosec is None:
        try:
            if have_tosec() and not os.path.exists(TOSEC_INDEX):
                _build_tosec()
            else:
                with open(TOSEC_INDEX) as fh:
                    _tosec = {k: tuple(v) for k, v in json.load(fh).items()}
        except (OSError, ValueError):
            _tosec = {}
    return _tosec


def names_in(list_prefix):
    """Every disk name in the TOSEC lists whose name starts with list_prefix (e.g. 'Coverdisks')."""
    return [name for name, lst in tosec_index().values() if lst.startswith(list_prefix)]


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
    """{top id: (TOSEC name, where the name came from, TOSEC list)} for items whose disk is known.
    rows_by_top: {top id: [media rows of the item and everything inside it]};
    lists: datlists.CollectionList objects (TOSEC .dat files found in the scanned folders)."""
    known = index()
    tosec = tosec_index()
    dats = [l for l in lists if l.kind == "dat"]
    out = {}
    for top, rows in rows_by_top.items():
        found = []
        for r in rows:
            sha = (r["sha1"] or "").lower()
            if not sha:
                continue
            for lst in dats:
                if sha in lst.by_sha1:
                    found.append((lst.by_sha1[sha], lst.title, lst.title))
                    break
            else:
                if sha in tosec:
                    name, which = tosec[sha]
                    found.append((name, f"TOSEC's {which} list", which))
                elif sha in known:
                    found.append((known[sha], LIST_TITLE, "Games"))
            if found and r is rows[0]:
                break                    # the item itself is known: that's its name
        if found:
            out[top] = (several_disks(found[0][0], [f[0] for f in found]),) + found[0][1:]
    return out


def several_disks(first, names):
    """The name for an archive holding several disks of one set: an archive with "(Disk 1 of 3)",
    "(Disk 2 of 3)" and "(Disk 3 of 3)" inside is the whole set, not disk 1, so the disk number
    comes out of its name ("Walker (1993)(Psygnosis)"), or says which disks it holds when it isn't
    all of them ("(Disks 1, 2 of 3)"). Anything else keeps the first name found.

    One disk can match another release of the same game: Pinball Fantasies' disk 1 is the same as
    the four-disk release's, while its disks 2 and 3 say "of 3". So the total is the one most of
    the disks agree on (ties: the one their number fits), and the name comes from that release."""
    from collections import Counter
    from . import sets
    named = [(n, sets.parse(n)) for n in dict.fromkeys(names)]
    named = [(n, p) for n, p in named if p]
    if len(named) < 2 or len({p[0] for _, p in named}) != 1:
        return first                      # one disk, or disks of different games
    numbers = {p[1] for _, p in named}
    votes = Counter(p[2] for _, p in named)
    total = max(votes, key=lambda t: (votes[t], t == len(numbers), -t))
    have = sorted(n for n in numbers if n <= total)
    base = next(n for n, p in named if p[2] == total)
    m = sets._DISK.search(base)
    if m is None:
        return first
    tag = "" if have == list(range(1, total + 1)) else \
        f"(Disks {', '.join(map(str, have))} of {total})"
    return (base[:m.start()] + tag + base[m.end():]).replace("  ", " ")


def stem(name):
    """A TOSEC rom name without its extension."""
    return re.sub(r"\.(adf|adz|dms|ipf|zip|lha|exe|rom|bin)$", "", name, flags=re.I)


def guess(path):
    """For a file whose name says nothing ("Disk1.adf"), the folder it is in, if that does.
    Returns the folder name or ""."""
    base = os.path.splitext(os.path.basename(path))[0]
    if not GENERIC_FILE.match(base.strip()):
        return ""
    folder = os.path.basename(os.path.dirname(path))
    return "" if not folder or folder.lower() in GENERIC_FOLDER else folder


# ---------------------------------------------------------------- renaming files

def rename_plan(items, spares=None):
    """[(item, current path, new path)] for identified items whose file name differs from the
    TOSEC name. The extension of the actual file is kept (a ZIP stays a .zip), never doubled
    (a ROM becomes "….rom", not "….rom.rom").
    A file whose proper name is already taken by another file (an identical spare copy, usually)
    is left as it is, and listed in spares, if given, as (item, current path, the name taken)."""
    wanted = []
    for it in items:
        name = getattr(it, "tosec_name", "")
        if not name or it.type in ("Folder",) or not os.path.isfile(it.path):
            continue
        folder, current = os.path.split(it.path)
        ext = os.path.splitext(current)[1]
        base = _safe(stem(name))
        new = base if ext and base.lower().endswith(ext.lower()) else base + ext
        if new == current:
            continue
        wanted.append((it, it.path, os.path.join(folder, new), current))
    # a file already close to its proper name (only its extension wrong) goes first
    wanted.sort(key=lambda w: not w[3].lower().startswith(os.path.splitext(os.path.basename(w[2]))[0].lower()))
    plan, taken = [], set()
    for it, path, target, current in wanted:
        if target in taken or (os.path.exists(target) and not _same_file(target, path)):
            if spares is not None:
                spares.append((it, path, target))
            continue
        taken.add(target)
        plan.append((it, path, target))
    return plan


def _same_file(a, b):
    try:
        return os.path.samefile(a, b)          # a change of case only, on a case-blind disk
    except OSError:
        return False


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
