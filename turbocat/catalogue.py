"""The TurboCAT 4 catalogue: a single SQLite database file."""

import hashlib
import json
import os
import re
import sqlite3
import time

# Images with no data all share a fingerprint, so they would show up as "duplicates"
# of each other: an empty file, and blank (all-zero) DD and HD disks.
BLANK_SHA1 = tuple(hashlib.sha1(bytes(n)).hexdigest() for n in (0, 901120, 1802240))

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS media (
    id          INTEGER PRIMARY KEY,
    number      INTEGER,             -- TurboCAT-style disk number (top-level items)
    parent_id   INTEGER REFERENCES media(id) ON DELETE CASCADE,
    source      TEXT NOT NULL,       -- file or folder on the host computer
    inner_path  TEXT DEFAULT '',     -- path inside the parent container
    kind        TEXT,
    size        INTEGER,
    mtime       REAL,
    sha1        TEXT,
    volume      TEXT,
    fs          TEXT,
    boot_kind   TEXT,
    boot_flags  TEXT,
    status      TEXT,                -- ok / warning / error
    problems    TEXT,                -- JSON list
    warnings    TEXT,                -- JSON list
    text        TEXT,                -- JSON list of readable strings
    info        TEXT,                -- JSON dict
    whd_name    TEXT, whd_copy TEXT, whd_info TEXT,
    file_count  INTEGER,
    scanned_at  REAL
);
CREATE TABLE IF NOT EXISTS files (
    id       INTEGER PRIMARY KEY,
    media_id INTEGER REFERENCES media(id) ON DELETE CASCADE,
    path     TEXT, name TEXT, size INTEGER, date TEXT,
    comment  TEXT, protect TEXT, sha1 TEXT, is_dir INTEGER
);
CREATE INDEX IF NOT EXISTS ix_media_source ON media(source);
CREATE INDEX IF NOT EXISTS ix_media_sha1   ON media(sha1);
CREATE INDEX IF NOT EXISTS ix_files_media  ON files(media_id);
CREATE INDEX IF NOT EXISTS ix_files_sha1   ON files(sha1);
CREATE INDEX IF NOT EXISTS ix_files_name   ON files(name COLLATE NOCASE);
"""

# ---------------------------------------------------------------- searching

def search_words(text):
    """The words of a search. Spaces, underscores and dashes all separate words, so
    "space debris" finds space_debris.mod and "lemmings 2" finds Lemmings_2_The_Tribes.adf."""
    return [w for w in re.split(r"[\s_\-]+", text.lower()) if w]


def matches(words, *fields):
    """True if every word appears somewhere in the fields."""
    hay = " ".join((f or "") for f in fields).lower()
    return all(w in hay for w in words)


def _like_all(words, columns):
    """SQL requiring every word in at least one of the columns, and its parameters."""
    parts, args = [], []
    for w in words:
        pat = "%" + w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        parts.append("(" + " OR ".join(f"{c} LIKE ? ESCAPE '\\'" for c in columns) + ")")
        args += [pat] * len(columns)
    return " AND ".join(parts) or "1", args


# ---------------------------------------------------------------- safety copies
# The window checks the catalogue each time it starts, keeps a copy of a healthy one, and offers
# the newest copy back if the file has been damaged. Copies live in a folder beside the catalogue
# (turbocat.db -> turbocat-backups/), made with SQLite's own backup, so recent changes still in
# the journal (-wal) file are included.
BACKUP_KEEP = 5               # copies kept
BACKUP_EVERY = 3600           # seconds: at most one new copy an hour, so older ones survive restarts


def backup_folder(path):
    return os.path.splitext(os.path.abspath(path))[0] + "-backups"


def _readonly(path):
    return sqlite3.connect(f"file:{os.path.abspath(path)}?mode=ro", uri=True, timeout=30)


def check(path):
    """(True, "") if the catalogue opens and SQLite's quick check passes (or there is no file
    yet), otherwise (False, what SQLite said)."""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return True, ""
    try:
        con = _readonly(path)
        try:
            result = [r[0] for r in con.execute("PRAGMA quick_check(5)")]
        finally:
            con.close()
    except sqlite3.Error as ex:
        return False, str(ex)
    return (True, "") if result == ["ok"] else (False, "; ".join(result))


def backups(path):
    """Copies of this catalogue, newest first: [(file, made at (seconds), items)]."""
    folder = backup_folder(path)
    out = []
    try:
        names = os.listdir(folder)
    except OSError:
        return out
    for name in names:
        if not name.endswith(".db"):
            continue
        f = os.path.join(folder, name)
        try:
            con = _readonly(f)
            items = con.execute("SELECT count(*) FROM media WHERE parent_id IS NULL").fetchone()[0]
            con.close()
        except sqlite3.Error:
            continue
        out.append((f, os.path.getmtime(f), items))
    return sorted(out, key=lambda b: -b[1])


def make_backup(path, force=False):
    """Copy a healthy catalogue into its backups folder; returns the copy's path, or None if a
    recent copy already exists. Call only after check() passed."""
    if not os.path.exists(path):
        return None
    folder = backup_folder(path)
    os.makedirs(folder, exist_ok=True)
    have = sorted(n for n in os.listdir(folder) if n.endswith(".db"))
    if not force and have and time.time() - os.path.getmtime(os.path.join(folder, have[-1])) < BACKUP_EVERY:
        return None
    stem = os.path.splitext(os.path.basename(path))[0]
    target = os.path.join(folder, f"{stem}-{time.strftime('%Y-%m-%d_%H%M%S')}.db")
    src, dst = _readonly(path), sqlite3.connect(target + ".part")
    try:
        src.backup(dst)
        dst.execute("PRAGMA journal_mode=DELETE")     # one self-contained file, no -wal/-shm
    finally:
        dst.close()
        src.close()
    os.replace(target + ".part", target)
    have = sorted(n for n in os.listdir(folder) if n.endswith(".db"))
    for old in have[:-BACKUP_KEEP]:
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(os.path.join(folder, old + suffix)):
                os.remove(os.path.join(folder, old + suffix))
    return target


def restore(path, copy):
    """Put a backup copy in place of a damaged catalogue. The damaged file (and its -wal/-shm
    files) is kept beside it, renamed; returns its new name."""
    stamp = time.strftime("%Y-%m-%d_%H%M%S")
    damaged = f"{path}.damaged-{stamp}"
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(path + suffix):
            os.replace(path + suffix, damaged + suffix)
    src, dst = _readonly(copy), sqlite3.connect(path + ".part")
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    os.replace(path + ".part", path)
    return damaged


class Catalogue:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=30)
        self.db.row_factory = sqlite3.Row
        # WAL lets the window keep reading while a scan writes in the background.
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)
        self._mark_empty()

    def _mark_empty(self):
        """Give empty files and blank disks their own status (catalogues made before 4.0.0-alpha.4
        reported a 0-byte file as a problem and a blank disk as OK)."""
        self.db.execute(
            "UPDATE media SET status='empty' WHERE sha1 IN (?,?,?) AND status!='empty'", BLANK_SHA1)
        self.db.commit()      # always: an open transaction would block other connections

    # ------------------------------------------------------------ writing
    def known_unchanged(self, source, size, mtime):
        row = self.db.execute(
            "SELECT id FROM media WHERE source=? AND parent_id IS NULL AND size=? AND mtime=?",
            (source, size, mtime)).fetchone()
        return row is not None

    def sources_with_message(self, starts):
        """Files whose item, or anything inside it, has a problem or warning starting with one of
        these texts (e.g. "LHA archive unreadable")."""
        if not starts:
            return set()
        cond = " OR ".join(["m.problems LIKE ? OR m.warnings LIKE ?"] * len(starts))
        args = [a for s in starts for a in (f'%"{s}%', f'%"{s}%')]
        rows = self.db.execute(
            "WITH RECURSIVE up(id, top) AS ("
            " SELECT id, id FROM media WHERE parent_id IS NULL"
            " UNION ALL SELECT c.id, up.top FROM media c JOIN up ON c.parent_id = up.id)"
            f" SELECT DISTINCT t.source FROM up JOIN media m ON m.id = up.id"
            f" JOIN media t ON t.id = up.top WHERE {cond}", args).fetchall()
        return {r[0] for r in rows}

    def remove_source(self, source):
        """Remove an item before rescanning it; returns its old number (or None)."""
        row = self.db.execute("SELECT number FROM media WHERE source=? AND parent_id IS NULL",
                              (source,)).fetchone()
        self.db.execute("DELETE FROM media WHERE source=? AND parent_id IS NULL", (source,))
        return row["number"] if row else None

    def next_number(self):
        r = self.db.execute("SELECT MAX(number) FROM media").fetchone()[0]
        return (r or 0) + 1

    def add_media(self, rec: dict, parent_id=None, number=None):
        cur = self.db.execute(
            """INSERT INTO media (number,parent_id,source,inner_path,kind,size,mtime,sha1,volume,fs,
               boot_kind,boot_flags,status,problems,warnings,text,info,whd_name,whd_copy,whd_info,
               file_count,scanned_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (number, parent_id, rec["source"], rec.get("inner_path", ""), rec["kind"],
             rec.get("size"), rec.get("mtime"), rec.get("sha1"), rec.get("volume", ""),
             rec.get("fs", ""), rec.get("boot_kind", ""), json.dumps(rec.get("boot_flags", [])),
             rec["status"], json.dumps(rec.get("problems", [])), json.dumps(rec.get("warnings", [])),
             json.dumps(rec.get("text", [])), json.dumps(rec.get("info", {}), default=str),
             rec.get("whd_name", ""), rec.get("whd_copy", ""), rec.get("whd_info", ""),
             sum(1 for f in rec.get("files", []) if not f["is_dir"]), time.time()))
        mid = cur.lastrowid
        self.db.executemany(
            "INSERT INTO files (media_id,path,name,size,date,comment,protect,sha1,is_dir) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            [(mid, f["path"], f["path"].rsplit("/", 1)[-1].split(":")[-1], f["size"],
              f["date"], f["comment"], f["protect"], f["sha1"], int(f["is_dir"]))
             for f in rec.get("files", [])])
        return mid

    def commit(self):
        self.db.commit()

    # ------------------------------------------------------------ reading
    def label(self, row):
        top = row
        chain = []
        while top["parent_id"]:
            chain.append(top["inner_path"])
            top = self.db.execute("SELECT * FROM media WHERE id=?", (top["parent_id"],)).fetchone()
        return " > ".join([top["source"]] + list(reversed(chain)))

    def top_number(self, row):
        while row["parent_id"]:
            row = self.db.execute("SELECT * FROM media WHERE id=?", (row["parent_id"],)).fetchone()
        return row["number"]

    def search(self, text, limit=200):
        like = f"%{text}%"
        files = self.db.execute(
            """SELECT f.*, m.id AS mid FROM files f JOIN media m ON m.id=f.media_id
               WHERE f.name LIKE ? OR f.comment LIKE ? ORDER BY f.name LIMIT ?""",
            (like, like, limit)).fetchall()
        media = self.db.execute(
            """SELECT * FROM media WHERE source LIKE ? OR inner_path LIKE ? OR volume LIKE ?
               OR whd_name LIKE ? OR text LIKE ? ORDER BY number LIMIT ?""",
            (like, like, like, like, like, limit)).fetchall()
        return media, files

    def top_ids(self):
        """Map every media id to the id of the top-level item that holds it."""
        parent = {r["id"]: r["parent_id"]
                  for r in self.db.execute("SELECT id, parent_id FROM media")}
        top = {}
        for mid in parent:
            t = mid
            while parent.get(t):
                t = parent[t]
            top[mid] = t
        return top

    def search_items(self, text, max_files=5000):
        """Search everything and group the hits by top-level item.

        Returns {top_id: {"why": [short reasons], "files": n, "first_file": path}};
        "files" counts matching files inside the item (counting stops at max_files).
        """
        words = search_words(text)
        top = self.top_ids()
        hits = {}

        def hit(mid):
            return hits.setdefault(top.get(mid, mid), {"why": [], "files": 0, "first_file": ""})

        if not words:
            return hits
        cols = ("source", "inner_path", "volume", "whd_name", "text")
        where, args = _like_all(words, cols)
        for m in self.db.execute(f"SELECT * FROM media WHERE {where}", args):
            h = hit(m["id"])
            if matches(words, m["whd_name"]):
                h["why"].append(f"WHDLoad game {m['whd_name']}")
            elif matches(words, m["volume"]):
                h["why"].append(f"volume {m['volume']}")
            elif matches(words, m["inner_path"]):
                h["why"].append(f"inside: {m['inner_path']}")
            elif not matches(words, m["source"]):
                try:
                    texts = json.loads(m["text"] or "[]")
                except ValueError:
                    texts = []
                found = next((t for t in texts if matches(words, t)), "")
                h["why"].append(f'disk text "{found[:60]}"' if found else "disk text")
        where, args = _like_all(words, ("name", "comment"))
        for f in self.db.execute(
                f"SELECT media_id, path FROM files WHERE {where} ORDER BY path LIMIT ?",
                args + [max_files]):
            h = hit(f["media_id"])
            h["files"] += 1
            if not h["first_file"]:
                h["first_file"] = f["path"]
        # Tunes by their own titles ("stardust memories" is inside stardstm.mod).
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='music'").fetchone():
            where, args = _like_all(words, ("title",))
            for r in self.db.execute(f"SELECT media_id, title FROM music WHERE {where}", args):
                h = hit(r["media_id"])
                why = f'tune "{r["title"]}"'
                if why not in h["why"]:
                    h["why"].append(why)
        return hits

    # ------------------------------------------------------------ scanned folders
    def get_meta(self, key, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        try:
            return json.loads(row[0]) if row else default
        except ValueError:
            return default

    def set_meta(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                        (key, json.dumps(value)))
        self.db.commit()

    @staticmethod
    def _within(path, root):
        try:
            return os.path.commonpath([path, root]) == root
        except ValueError:
            return False

    def _outermost(self, paths):
        paths = sorted({os.path.normpath(p) for p in paths}, key=len)
        out = []
        for p in paths:
            if not any(self._within(p, r) for r in out):
                out.append(p)
        return sorted(out)

    def scan_roots(self):
        """Folders (or files) this catalogue was built from, for Rescan.

        Catalogues made before 4.0.0-alpha.4 did not record them; for those, the folders
        holding the catalogued items are used.
        """
        roots = self.get_meta("roots")
        if roots is not None:
            return roots
        found = []
        for r in self.db.execute("SELECT source, kind FROM media WHERE parent_id IS NULL"):
            found.append(r["source"] if r["kind"] == "folder" else os.path.dirname(r["source"]))
        return self._outermost(found)

    def add_scan_roots(self, paths):
        self.set_meta("roots", self._outermost(list(self.scan_roots()) + list(paths)))

    def remove_missing(self, roots):
        """Drop items whose file has gone, but only under roots that still exist
        (so an unplugged drive or unmounted share doesn't empty the catalogue)."""
        live = [r for r in roots if os.path.exists(r)]
        gone = []
        for r in self.db.execute("SELECT id, number, source FROM media WHERE parent_id IS NULL"):
            if not os.path.exists(r["source"]) and any(self._within(r["source"], x) for x in live):
                gone.append(r)
        for r in gone:
            self.db.execute("DELETE FROM media WHERE id=?", (r["id"],))
        self.db.commit()
        return [(r["number"], r["source"]) for r in gone]

    def media_by_id(self, mid):
        return self.db.execute("SELECT * FROM media WHERE id=?", (mid,)).fetchone()

    def all_media(self):
        return self.db.execute("SELECT * FROM media ORDER BY id").fetchall()

    def duplicate_images(self):
        return self.db.execute(
            """SELECT sha1, COUNT(*) n FROM media WHERE sha1 IS NOT NULL AND kind IN
               ('adf','dms','adz','hdf','lha','lzx','zip') AND sha1 NOT IN (?,?,?)
               GROUP BY sha1 HAVING n>1""", BLANK_SHA1).fetchall()

    def duplicate_files(self, min_size=1024, limit=100):
        return self.db.execute(
            """SELECT sha1, size, COUNT(DISTINCT media_id) n, MIN(name) name FROM files
               WHERE sha1 IS NOT NULL AND size>=? AND is_dir=0
               GROUP BY sha1 HAVING n>1 ORDER BY size DESC LIMIT ?""",
            (min_size, limit)).fetchall()

    def media_with_sha1(self, sha1):
        return self.db.execute("SELECT * FROM media WHERE sha1=?", (sha1,)).fetchall()

    def files_with_sha1(self, sha1):
        return self.db.execute("SELECT * FROM files WHERE sha1=?", (sha1,)).fetchall()

    def stats(self):
        q = lambda s: self.db.execute(s).fetchone()[0]
        return {
            "items": q("SELECT COUNT(*) FROM media WHERE parent_id IS NULL"),
            "containers": q("SELECT COUNT(*) FROM media"),
            "files": q("SELECT COUNT(*) FROM files WHERE is_dir=0"),
            "errors": q("SELECT COUNT(*) FROM media WHERE status='error'"),
            "warnings": q("SELECT COUNT(*) FROM media WHERE status='warning'"),
            "empty": q("SELECT COUNT(*) FROM media WHERE status='empty'"),
        }
