"""The TurboCAT 4 catalogue: a single SQLite database file."""

import hashlib
import json
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


class Catalogue:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)

    # ------------------------------------------------------------ writing
    def known_unchanged(self, source, size, mtime):
        row = self.db.execute(
            "SELECT id FROM media WHERE source=? AND parent_id IS NULL AND size=? AND mtime=?",
            (source, size, mtime)).fetchone()
        return row is not None

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
        like = f"%{text}%"
        low = text.lower()
        top = self.top_ids()
        hits = {}

        def hit(mid):
            return hits.setdefault(top.get(mid, mid), {"why": [], "files": 0, "first_file": ""})

        for m in self.db.execute(
                """SELECT * FROM media WHERE source LIKE ? OR inner_path LIKE ? OR volume LIKE ?
                   OR whd_name LIKE ? OR text LIKE ?""", (like,) * 5):
            h = hit(m["id"])
            if low in (m["whd_name"] or "").lower():
                h["why"].append(f"WHDLoad game {m['whd_name']}")
            elif low in (m["volume"] or "").lower():
                h["why"].append(f"volume {m['volume']}")
            elif low in (m["inner_path"] or "").lower():
                h["why"].append(f"inside: {m['inner_path']}")
            elif low not in m["source"].lower():
                try:
                    texts = json.loads(m["text"] or "[]")
                except ValueError:
                    texts = []
                found = next((t for t in texts if low in t.lower()), "")
                h["why"].append(f'disk text "{found[:60]}"' if found else "disk text")
        for f in self.db.execute(
                """SELECT media_id, path FROM files WHERE name LIKE ? OR comment LIKE ?
                   ORDER BY path LIMIT ?""", (like, like, max_files)):
            h = hit(f["media_id"])
            h["files"] += 1
            if not h["first_file"]:
                h["first_file"] = f["path"]
        return hits

    def media_by_id(self, mid):
        return self.db.execute("SELECT * FROM media WHERE id=?", (mid,)).fetchone()

    def all_media(self):
        return self.db.execute("SELECT * FROM media ORDER BY id").fetchall()

    def duplicate_images(self):
        return self.db.execute(
            """SELECT sha1, COUNT(*) n FROM media WHERE sha1 IS NOT NULL AND kind IN
               ('adf','dms','adz','hdf','lha','lzx') AND sha1 NOT IN (?,?,?)
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
        }
