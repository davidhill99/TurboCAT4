"""Thumbnails for catalogued items.

1. From the disks themselves: each disk's Workbench icon (Disk.info) and the best IFF picture
   on it (a title screen if there is one).
2. Online, for items with no picture of their own: the libretro-thumbnails collection used by
   RetroArch (github.com/libretro-thumbnails/Commodore_-_Amiga), matched by exact title only.
   Those images belong to the games' publishers; they are kept in a local cache for personal use.

Pictures are saved as PNG files in ~/.cache/turbocat/pictures and listed in the catalogue's
`thumbs` table, keyed by the item's SHA1 so a rescan of an unchanged file keeps them.
"""
import functools
import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request

from . import amigaimg, music, paths, readers
from .gotek import _unpack_floppy

CACHE = paths.cache_dir()      # ~/.cache/turbocat on Linux
PIC_DIR = os.path.join(CACHE, "pictures")
LR_REPO = "libretro-thumbnails/Commodore_-_Amiga"
LR_TREE = f"https://api.github.com/repos/{LR_REPO}/git/trees/master?recursive=1"
LR_RAW = f"https://raw.githubusercontent.com/{LR_REPO}/master/"
LR_ORDER = ("Named_Titles", "Named_Snaps", "Named_Boxarts")
USER_AGENT = "TurboCAT/4 (Amiga disk catalogue)"

SCHEMA = """
CREATE TABLE IF NOT EXISTS thumbs (
    key       TEXT PRIMARY KEY,   -- the item's SHA1 (or path: for folders)
    icon      TEXT, icon_from TEXT,
    pic       TEXT, pic_from  TEXT, pic_w INTEGER, pic_h INTEGER,
    origin    TEXT,               -- 'disk' or 'online' (for pic)
    online    INTEGER DEFAULT 0,  -- 1 once an online lookup was tried
    made_at   REAL
);
CREATE TABLE IF NOT EXISTS music (
    key       TEXT,               -- the item's key, as in thumbs
    media_id  INTEGER,            -- the disk or archive holding the file
    file      TEXT,               -- path inside it
    shown     TEXT,               -- where it is, for people ("Disk.adf: mods/mod.tune")
    fmt       TEXT, title TEXT, size INTEGER,
    offset    INTEGER DEFAULT 0,  -- for a module built into a program: where it starts
    length    INTEGER,            -- ... and how long it is (NULL: the whole file)
    duration  REAL                -- playing time in seconds (NULL: not measured, -1: can't play)
);
CREATE INDEX IF NOT EXISTS ix_music_key ON music(key);
"""

READABLE = ("adf", "adz", "dms", "zip", "lha", "folder", "module")
NOT_MODULES = (".library", ".device", ".font", ".iff", ".ilbm", ".pic", ".txt", ".doc", ".guide",
               ".readme", ".catalog", ".info", ".lha", ".lzx", ".zip", ".dms", ".adf")
NOT_PICTURES = (".library", ".device", ".mod", ".doc", ".txt", ".guide", ".readme", ".s",
                ".asm", ".c", ".h", ".font", ".catalog", ".exe", ".8svx", ".snd", ".smus",
                ".med", ".lha", ".lzx", ".zip", ".dms", ".adf", ".slave", ".rexx", ".rx")
MAX_READS = 400          # files opened per container, at most
MAX_PIC_SIZE = 600_000


def ensure_schema(cat):
    cat.db.executescript(SCHEMA)
    cols = {r[1] for r in cat.db.execute("PRAGMA table_info(music)")}
    if "offset" not in cols:
        cat.db.execute("ALTER TABLE music ADD COLUMN offset INTEGER DEFAULT 0")
        cat.db.execute("ALTER TABLE music ADD COLUMN length INTEGER")
    if "duration" not in cols:
        cat.db.execute("ALTER TABLE music ADD COLUMN duration REAL")
    if "artist" not in cols:
        cat.db.execute("ALTER TABLE music ADD COLUMN artist TEXT")
        cat.db.execute("ALTER TABLE music ADD COLUMN info_v INTEGER DEFAULT 0")
    tcols = {r[1] for r in cat.db.execute("PRAGMA table_info(thumbs)")}
    if "made" not in tcols:             # pictures TurboCAT draws itself (madepics.py)
        cat.db.execute("ALTER TABLE thumbs ADD COLUMN made TEXT")
        cat.db.execute("ALTER TABLE thumbs ADD COLUMN made_from TEXT")
        cat.db.execute("ALTER TABLE thumbs ADD COLUMN made_v INTEGER DEFAULT 0")


MUSIC_INFO_V = 1       # bump to read every tune's song name and artist again


def item_key(m):
    return m["sha1"] or ("path:" + m["source"])


def thumbs_by_key(cat):
    ensure_schema(cat)
    return {r["key"]: r for r in cat.db.execute("SELECT * FROM thumbs")}


def picture_path(name):
    return os.path.join(PIC_DIR, name) if name else None


def _save_png(png):
    os.makedirs(PIC_DIR, exist_ok=True)
    name = hashlib.sha1(png).hexdigest()[:20] + ".png"
    path = os.path.join(PIC_DIR, name)
    if not os.path.exists(path):
        with open(path + ".part", "wb") as f:
            f.write(png)
        os.replace(path + ".part", path)
    return name


# ---------------------------------------------------------------- reading items again

def _files_in(kind, data, path=None):
    """List a container's files (with readers) without the slow filesystem check."""
    if kind == "folder":
        return readers.read_folder(path).files
    if kind == "module":
        return readers.read_module(data, path or "module").files
    if kind in ("adf", "adz", "dms"):
        return readers.read_adf(_unpack_floppy(kind, data), validate=False).files
    return readers.READERS[kind](data).files


def _container_data(cat, chain):
    """Bytes of the last container in chain (top-level first), unpacked from its parents."""
    top = chain[0]
    if top["kind"] == "folder":
        return None
    with open(top["source"], "rb") as f:
        data = f.read()
    for outer, inner in zip(chain, chain[1:]):
        for fe in _files_in(outer["kind"], data, outer["source"]):
            if fe.path == inner["inner_path"] and fe.read:
                data = fe.read()
                break
        else:
            raise ValueError(f"{inner['inner_path']} not found")
    return data


# ---------------------------------------------------------------- choosing pictures

GOOD_WORDS = (("title", 120), ("intro", 70), ("logo", 60), ("splash", 60), ("loading", 60),
              ("load", 40), ("start", 30), ("menu", 30), ("screen", 30), ("pic", 20), ("front", 30))
BAD_WORDS = ("font", "brush", "sprite", "mask", "panel", "cockpit", "tile", "block", "map",
             "gfx", "icon", "button", "pointer", "anim", "frame", "bob", "shape", "sheet",
             "score", "credits", "gameover")


def _score(path, img):
    w, h = img.width, img.height
    if w < 96 or h < 64:
        return None                       # brushes, sprites, fonts
    name = path.lower().rsplit("/", 1)[-1]
    s = 0
    for word, bonus in GOOD_WORDS:
        if word in name:
            s += bonus
            break
    if any(word in name for word in BAD_WORDS):
        s -= 70
    if w >= 280 and h >= 180:
        s += 60
    s += min(img.planes, 8) * 4
    if img.planes == 1:
        s -= 40
    if 1.0 <= w / h <= 2.2:
        s += 15
    elif w / h < 0.8:                     # tall strips: score tables, palettes, scrollers
        s -= 80
    s -= path.count("/") * 3              # nearer the top is usually the main picture
    return s


def _icon_rank(path, dirs):
    low = path.lower()
    if low == "disk.info":
        return 0
    if "/" in path:
        return None
    stem = path[:-5]
    return 1 if stem.lower() in dirs else 2


def find_on_item(cat, top, inside=None, stop=lambda: False):
    """Look through an item (and the disks or archives inside it) for its icon and best picture.
    Returns dict(icon=Image|bytes, icon_from=str, pic=Image, pic_from=str).

    Each container is opened once, from the one above it, depth first: an archive of a thousand
    zipped disks is read from disk once, not once per disk. Where two finds are equally good, the
    one nearer the item itself wins. inside(done, total, name), if given, is told how far through
    the containers inside the item it is; stop() is checked between the containers inside it (raising Stopped)."""
    found = {"icon": None, "icon_from": "", "pic": None, "pic_from": "", "score": None,
             "icon_rank": 9, "icon_depth": 0, "pic_depth": 0, "music": []}
    total = cat.db.execute(
        "WITH RECURSIVE d(id) AS (SELECT id FROM media WHERE parent_id=? "
        "UNION ALL SELECT m.id FROM media m JOIN d ON m.parent_id=d.id) SELECT COUNT(*) FROM d",
        (top["id"],)).fetchone()[0]
    seen = [0]

    def look(m, chain, data):
        depth = len(chain) - 1
        if depth:
            seen[0] += 1
            if stop():
                raise Stopped()
            if inside:
                inside(seen[0], total, os.path.basename(m["inner_path"] or m["source"]))
        kids = cat.db.execute("SELECT * FROM media WHERE parent_id=? ORDER BY id", (m["id"],)).fetchall()
        if m["kind"] not in READABLE and not kids:
            return
        try:
            if data is None and m["kind"] != "folder":
                data = _container_data(cat, chain)
            files = _files_in(m["kind"], data, m["source"])
        except Exception:
            return
        if m["kind"] in READABLE and m["status"] != "empty":
            _look_in_files(found, m, chain, files, depth)
        by_path = {fe.path: fe for fe in files if fe.read}
        for k in kids:
            fe = by_path.get(k["inner_path"])
            if fe is None:
                continue
            try:
                kid_data = fe.read()
            except Exception:
                continue
            look(k, chain + [k], kid_data)

    look(top, [top], None)
    return found


def _look_in_files(found, m, chain, files, depth):
    """Icons, pictures and tunes among one container's files."""
    where = " > ".join(os.path.basename(c["inner_path"] or c["source"]) for c in chain[1:])
    prefix = (where + ": ") if where else ""
    dirs = {fe.path.lower() for fe in files if fe.is_dir}
    reads = 0
    for fe in files:
        if fe.is_dir or not fe.read or not fe.size:
            continue
        low = fe.path.lower()
        if low.endswith(".info"):
            rank = _icon_rank(fe.path, dirs)
            # equally good: the one nearer the item itself
            if rank is None or (found["icon"] is not None and
                                (rank, depth) >= (found["icon_rank"], found["icon_depth"])):
                continue
            try:
                img = amigaimg.decode_icon(fe.read())
            except Exception:
                img = None
            if img is not None:
                found.update(icon=img, icon_from=prefix + fe.path, icon_rank=rank, icon_depth=depth)
            continue
        named_mod = music.NAME_HINT.search(fe.path) is not None
        maybe_pic = 1500 <= fe.size <= MAX_PIC_SIZE and not low.endswith(NOT_PICTURES)
        maybe_mod = 600 <= fe.size <= 32_000_000 and (
            named_mod or (fe.size >= 1084 and not low.endswith(NOT_MODULES)))
        if not (maybe_pic or maybe_mod):
            continue
        if reads >= MAX_READS and not named_mod:
            continue
        reads += 1
        try:
            content = fe.read()
        except Exception:
            continue
        if not amigaimg.is_iff_picture(content[:12]):
            tune = music.identify(fe.path, content) if maybe_mod else None
            if tune:
                found["music"].append({"media_id": m["id"], "file": fe.path,
                                       "shown": prefix + fe.path, "fmt": tune[0],
                                       "title": tune[1], "size": len(content)})
            elif content[:4] == b"\0\0\x03\xf3" and b"M.K." in content:
                for off, length, title in music.embedded(content):
                    found["music"].append({"media_id": m["id"], "file": fe.path,
                                           "shown": prefix + fe.path, "fmt": "ProTracker",
                                           "title": title, "size": length,
                                           "offset": off, "length": length})
            continue
        if not maybe_pic:
            continue
        try:
            d = amigaimg.decode_iff(content)
        except Exception:
            d = None
        if not d:
            continue
        s = _score(fe.path, d[0])
        # Below 0 it's more likely a score table or a strip of graphics than a screen.
        # Equally good: the one nearer the item itself (as when this looked breadth first).
        if s is not None and s >= 0 and (found["score"] is None or s > found["score"] or
                                         (s == found["score"] and depth < found["pic_depth"])):
            found.update(pic=amigaimg.square_pixels(*d), pic_from=prefix + fe.path, score=s,
                         pic_depth=depth)


def _store(cat, key, icon=None, icon_from="", pic=None, pic_from="", origin="", online=0):
    icon_name = pic_name = None
    pw = ph = None
    if icon is not None:
        icon_name = _save_png(icon if isinstance(icon, bytes) else amigaimg.write_png(icon))
    if pic is not None:
        if isinstance(pic, bytes):
            pic_name = _save_png(pic)
        else:
            pic_name = _save_png(amigaimg.write_png(pic))
            pw, ph = pic.width, pic.height
    cat.db.execute(
        """INSERT INTO thumbs (key, icon, icon_from, pic, pic_from, pic_w, pic_h, origin, online, made_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(key) DO UPDATE SET icon=excluded.icon, icon_from=excluded.icon_from,
             -- keep a picture found online if the disk itself has none
             pic=COALESCE(excluded.pic, pic),
             pic_from=CASE WHEN excluded.pic IS NULL THEN pic_from ELSE excluded.pic_from END,
             pic_w=CASE WHEN excluded.pic IS NULL THEN pic_w ELSE excluded.pic_w END,
             pic_h=CASE WHEN excluded.pic IS NULL THEN pic_h ELSE excluded.pic_h END,
             origin=CASE WHEN excluded.pic IS NULL THEN origin ELSE excluded.origin END,
             made_at=excluded.made_at""",
        (key, icon_name, icon_from, pic_name, pic_from, pw, ph, origin if pic_name else "",
         online, time.time()))


RULES = 5       # bump when the choice of picture changes, so items are looked at again


def music_by_key(cat):
    ensure_schema(cat)
    out = {}
    for r in cat.db.execute("SELECT * FROM music ORDER BY rowid"):
        out.setdefault(r["key"], []).append(r)
    return out


def module_data(cat, row):
    """The bytes of one module listed in the music table."""
    data = extract_file(cat, row["media_id"], row["file"])
    if row["length"]:
        data = data[row["offset"]:row["offset"] + row["length"]]
    return data


def _clean_text(s):
    s = re.sub(r"\s+", " ", (s or "").replace("\0", " ")).strip()
    return "" if s.lower() in ("<unnamed>", "untitled", "unnamed") else s


def _is_file_name(title, path):
    """True when a tune's 'title' is just its file name (mod.tune, tune.mod)."""
    name = path.rsplit("/", 1)[-1].lower()
    stem = re.sub(r"^(mod|med|xm|s3m)\.", "", name).rsplit(".", 1)[0]
    return title.strip().lower() in (name, stem)


def measure_music(cat, progress=None, stop=lambda: False):
    """Work out the playing time, song name and artist of every module not looked at yet
    (needs libopenmpt or libxmp). Each disk or archive is opened once for all its tunes."""
    ensure_schema(cat)
    if music._Lib.get() is None and music._Xmp.get() is None:
        return {"measured": 0}
    rows = cat.db.execute("SELECT rowid, * FROM music WHERE duration IS NULL OR COALESCE(info_v, 0) < ? "
                          "ORDER BY media_id", (MUSIC_INFO_V,)).fetchall()
    by_media = {}
    for r in rows:
        by_media.setdefault(r["media_id"], []).append(r)
    done = 0
    for mid, tunes in by_media.items():
        if stop():
            break
        files = {}
        try:
            chain = []
            m = cat.media_by_id(mid)
            while m is not None:
                chain.append(m)
                m = cat.media_by_id(m["parent_id"]) if m["parent_id"] else None
            chain.reverse()
            files = {fe.path: fe for fe in _files_in(chain[-1]["kind"], _container_data(cat, chain),
                                                     chain[-1]["source"]) if fe.read}
        except Exception:
            pass
        for r in tunes:
            secs, title, artist = -1.0, r["title"] or "", r["artist"] or ""
            fe = files.get(r["file"])
            if fe is not None and r["fmt"] in music.PLAYABLE:
                try:
                    data = fe.read()
                    if r["length"]:
                        data = data[r["offset"]:r["offset"] + r["length"]]
                    mod = music.open_module(data)
                    secs = mod.duration
                    found = _clean_text(mod.meta("title"))
                    if found and (not title or _is_file_name(title, r["file"])):
                        title = found
                    artist = _clean_text(mod.meta("artist")) or artist
                    mod.close()
                except Exception:
                    secs = -1.0
            cat.db.execute("UPDATE music SET duration=?, title=?, artist=?, info_v=? WHERE rowid=?",
                           (secs, title, artist, MUSIC_INFO_V, r["rowid"]))
            done += 1
            if progress:
                progress(done, len(rows), None)
        cat.db.commit()
    return {"measured": done}


def extract_file(cat, media_id, path):
    """The contents of one file inside a catalogued disk or archive."""
    chain = []
    m = cat.media_by_id(media_id)
    while m is not None:
        chain.append(m)
        m = cat.media_by_id(m["parent_id"]) if m["parent_id"] else None
    if not chain:
        raise ValueError("the disk is no longer in the catalogue; rescan it")
    chain.reverse()
    data = _container_data(cat, chain)
    for fe in _files_in(chain[-1]["kind"], data, chain[-1]["source"]):
        if fe.path == path and fe.read:
            return fe.read()
    raise ValueError(f"{path} was not found; the disk may have changed since it was scanned")


def build(cat, progress=None, stop=lambda: False):
    """Find icons and pictures on every item that hasn't been looked at yet.
    progress(i, n, item) before each item; progress(i, n, item, (done, total, name)) as it
    goes through the disks and archives inside a big one."""
    ensure_schema(cat)
    if cat.get_meta("picture_rules", 1) != RULES:
        # Look through every disk again; pictures found online are kept unless a better
        # one turns up on the disk.
        cat.db.execute("UPDATE thumbs SET icon_from=NULL")
        cat.db.execute("DELETE FROM music")
        cat.db.execute("UPDATE thumbs SET pic=NULL, pic_from=NULL, pic_w=NULL, pic_h=NULL, origin='' "
                       "WHERE origin='disk'")
        cat.set_meta("picture_rules", RULES)
    # icon_from is set (possibly to '') once the disk itself has been looked through
    done = {r["key"] for r in cat.db.execute("SELECT key FROM thumbs WHERE icon_from IS NOT NULL")}
    todo = [m for m in cat.db.execute("SELECT * FROM media WHERE parent_id IS NULL ORDER BY number")
            if item_key(m) not in done and m["kind"] != "hdf"]
    found = looked = 0
    stopped = False
    for i, m in enumerate(todo):
        if stop():
            stopped = True
            break
        if progress:
            progress(i, len(todo), m)
        last = [time.monotonic()]

        def inside(done, total, name, i=i, m=m, last=last):
            now = time.monotonic()
            if progress and now - last[0] >= 0.25:
                last[0] = now
                progress(i, len(todo), m, (done, total, name))
        try:
            f = find_on_item(cat, m, inside, stop)
        except Stopped:
            stopped = True
            break                         # not stored: looked through again next time
        except Exception:
            f = {"icon": None, "pic": None, "icon_from": "", "pic_from": ""}
        _store(cat, item_key(m), f["icon"], f["icon_from"], f["pic"], f["pic_from"], "disk")
        cat.db.execute("DELETE FROM music WHERE key=?", (item_key(m),))
        cat.db.executemany(
            "INSERT INTO music (key, media_id, file, shown, fmt, title, size, offset, length) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            [(item_key(m), t["media_id"], t["file"], t["shown"], t["fmt"], t["title"], t["size"],
              t.get("offset", 0), t.get("length")) for t in f.get("music", [])])
        found += bool(f["icon"] or f["pic"])
        looked += 1
        if i % 20 == 19:
            cat.db.commit()
    cat.db.commit()
    if progress:
        progress(len(todo), len(todo), None)
    return {"looked": looked, "found": found, "stopped": stopped}


# ---------------------------------------------------------------- online

@functools.lru_cache(maxsize=None)
def normal(title):
    t = title.lower().replace("&", " and ")
    t = re.sub(r"^(the|a|an)\s+(.*)$", r"\2 \1", t.strip())
    return re.sub(r"[^a-z0-9]", "", t)


_JUNK_PREFIX = re.compile(r"^(zzz-unk-|zzz-)", re.I)
_EXTRA_WORDS = re.compile(r"(\s*-\s*|\s+)(hd install(er)?|trainer\b.*|cd32|aga|ecs|ocs|1mb|512k|"
                          r"preview|budget|re-?release)\s*$", re.I)


@functools.lru_cache(maxsize=None)
def loose(title):
    """A looser key for matching names that differ only in small words: no 'the/a/an', no
    version number at the end, no edition words ('Dune II - The Battle for Arrakis' and
    'Dune II - Battle for Arrakis'; 'Millennium 2.2' and 'Millennium')."""
    t = _JUNK_PREFIX.sub("", title.strip())
    for _ in range(3):
        t = _EXTRA_WORDS.sub("", t)
    t = re.sub(r"\s+v?[0-9]+(\.[0-9]+)+[a-z]?\s*$", "", t, flags=re.I)
    t = t.lower().replace("&", " and ")
    t = re.sub(r"\b(the|a|an)\b", " ", t)
    return re.sub(r"[^a-z0-9]", "", t)


@functools.lru_cache(maxsize=None)
def clean_title(name):
    """'Lemmings 2 - The Tribes (1993)(Psygnosis)[cr].zip' -> 'Lemmings 2 - The Tribes'."""
    base = os.path.basename(name.rstrip("/"))
    for _ in range(2):
        stem, ext = os.path.splitext(base)
        if ext.lower() in (".adf", ".adz", ".dms", ".zip", ".lha", ".lzh", ".lzx", ".gz", ".hdf", ".ipf"):
            base = stem
    base = re.split(r"\s*[\(\[]", base, maxsplit=1)[0]
    base = base.replace("_", " ")
    # Names without TOSEC brackets: "Lemmings 2 The Tribes demo-playable 1993 Psygnosis"
    base = re.sub(r"\s+(demo[- ]?(playable|rolling)?|(19|20)[0-9x]{2})\b.*$", "", base, flags=re.I)
    base = re.sub(r"[\s\-]*\b(disk|disc)\s*([0-9]+|[a-d])(\s*of\s*[0-9]+)?\s*$", "", base, flags=re.I)
    base = re.sub(r"\s+v?[0-9]+(\.[0-9]+)+[a-z]?\s*$", "", base, flags=re.I)   # versions
    base = _JUNK_PREFIX.sub("", base)                                          # "ZZZ-UNK-Ishar 3"
    return " ".join(base.split()).strip(" -")


class Stopped(Exception):
    """The user stopped the search (or is closing TurboCAT) while something was downloading."""


def _cached_json(path, url, max_age_days=30, stop=lambda: False):
    try:
        if time.time() - os.path.getmtime(path) < max_age_days * 86400:
            with open(path) as f:
                return json.load(f)
    except (OSError, ValueError):
        pass
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    chunks = []
    with urllib.request.urlopen(req, timeout=20) as r:
        while True:                         # a few MB: read in pieces so Stop works
            if stop():
                raise Stopped()
            chunk = r.read(1 << 16)
            if not chunk:
                break
            chunks.append(chunk)
    data = json.loads(b"".join(chunks))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".part", "w") as f:
        json.dump(data, f)
    os.replace(path + ".part", path)
    return data


def online_index(stop=lambda: False):
    """normalised title -> {folder: file path} from the libretro-thumbnails Amiga collection."""
    tree = _cached_json(os.path.join(CACHE, "libretro-amiga.json"), LR_TREE, stop=stop)
    index = {}
    for e in tree.get("tree", []):
        p = e.get("path", "")
        if e.get("type") != "blob" or not p.endswith(".png") or "/" not in p:
            continue
        folder, fname = p.split("/", 1)
        if folder not in LR_ORDER:
            continue
        title = re.split(r"\s*\(", fname[:-4], maxsplit=1)[0]
        _add(index, normal(title), folder, fname, p)
        _add(index, "~" + loose(title), folder, fname, p)     # the looser key, tried second
    return index


def _add(index, key, folder, fname, p):
    if key in ("", "~"):
        return
    slot = index.setdefault(key, {})
    # Prefer the entry without a region, then Europe, then whatever came first.
    old = slot.get(folder)
    if old is None or ("(" not in fname and "(" in old) or \
            ("(Europe)" in fname and "(Europe)" not in old and "(" in old):
        slot[folder] = p


def item_titles(cat, m):
    """Names an item might be known by, best first."""
    names = []
    if m["whd_name"]:
        names.append(m["whd_name"])
    names.append(clean_title(m["source"]))
    for k in cat.db.execute("SELECT inner_path, kind, volume FROM media WHERE parent_id=?", (m["id"],)):
        if k["kind"] in ("adf", "adz", "dms"):
            names.append(clean_title(k["inner_path"]))
    if m["volume"] and len(normal(m["volume"])) >= 8:
        names.append(m["volume"])
    out = []
    for n in names:
        if n and normal(n) and normal(n) not in [normal(o) for o in out]:
            out.append(n)
    return out


ONLINE_RULES = 2     # bump when the matching improves, so disks not found before are tried again


def lookup_online(cat, progress=None, stop=lambda: False, force=False, known=None):
    """For items without a picture of their own, fetch one from libretro-thumbnails.
    known: {top id: proper name} for disks identified by checksum: their real titles are tried
    first, and they are looked up again even if their file name found nothing before."""
    known = known or {}
    ensure_schema(cat)
    if progress:
        progress(0, 0, None)          # 0 of 0: fetching the list of pictures (a few MB, cached)
    try:
        index = online_index(stop)
    except Stopped:
        return {"looked": 0, "found": 0, "stopped": True}
    thumbs = thumbs_by_key(cat)
    retry = cat.get_meta("online_rules", 1) < ONLINE_RULES      # better matching since last time
    todo = []
    for m in cat.db.execute("SELECT * FROM media WHERE parent_id IS NULL ORDER BY number"):
        t = thumbs.get(item_key(m))
        if t is not None and t["pic"]:
            continue
        if t is not None and t["online"] and not (force or retry) and m["id"] not in known:
            continue
        if m["status"] == "empty" or m["kind"] in ("hdf", "folder", "module", "kickstart"):
            continue
        todo.append(m)
    got = looked = 0
    stopped = False
    for i, m in enumerate(todo):
        if stop():
            stopped = True
            break
        looked += 1
        if progress:
            progress(i, len(todo), m)
        key = item_key(m)
        t = thumbs.get(key)
        match = None
        titles = item_titles(cat, m)
        if m["id"] in known:
            titles = [clean_title(known[m["id"]])] + titles
        for key in [normal(n) for n in titles] + ["~" + loose(n) for n in titles]:
            slot = index.get(key)
            if slot:
                match = (titles[0], next(slot[f] for f in LR_ORDER if f in slot))
                break
        if match:
            url = LR_RAW + urllib.parse.quote(match[1])
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=30) as r:
                    png = r.read()
            except Exception:
                png = None
            if png and png[:8] == b"\x89PNG\r\n\x1a\n":
                pic_name = _save_png(png)
                cat.db.execute(
                    """INSERT INTO thumbs (key, pic, pic_from, origin, online, made_at)
                       VALUES (?,?,?,?,1,?) ON CONFLICT(key) DO UPDATE SET pic=excluded.pic,
                       pic_from=excluded.pic_from, origin='online', online=1, made_at=excluded.made_at""",
                    (key, pic_name, f"{match[1]}|{match[0]}", "online", time.time()))
                got += 1
                cat.db.commit()
                continue
        if t is None:
            cat.db.execute("INSERT OR IGNORE INTO thumbs (key, online, made_at) VALUES (?,1,?)",
                           (key, time.time()))
        else:
            cat.db.execute("UPDATE thumbs SET online=1 WHERE key=?", (key,))
        if i % 20 == 19:
            cat.db.commit()
    cat.db.commit()
    if retry and not stopped:
        cat.set_meta("online_rules", ONLINE_RULES)
    if progress:
        progress(len(todo), len(todo), None)
    return {"looked": looked, "found": got, "stopped": stopped}
