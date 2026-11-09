"""Favourites: disks, games, utilities and tunes the user has starred.

Stored in the catalogue by content (an item's fingerprint, a tune's place in it), so a favourite
stays a favourite when files are renamed, moved or rescanned. TurboView gets them too.
"""

SCHEMA = """CREATE TABLE IF NOT EXISTS favourites (
    kind  TEXT NOT NULL,      -- 'item' or 'tune'
    key   TEXT NOT NULL,
    added REAL,
    PRIMARY KEY (kind, key)
)"""


def _ensure(cat):
    cat.db.execute(SCHEMA)


def item_key(key):
    return ("item", key)


def tune_key(row):
    """A tune: its item's key, its file and (for tunes inside a program) where it starts."""
    return ("tune", f"{row['key']}|{row['file']}|{row['offset'] or 0}")


def load(cat):
    """Every favourite, as a set of (kind, key)."""
    _ensure(cat)
    return {(r["kind"], r["key"]) for r in cat.db.execute("SELECT kind, key FROM favourites")}


def set_favourite(cat, keys, on):
    """Star (on=True) or unstar these (kind, key) pairs."""
    import time
    _ensure(cat)
    if on:
        cat.db.executemany("INSERT OR IGNORE INTO favourites (kind, key, added) VALUES (?, ?, ?)",
                           [(k, v, time.time()) for k, v in keys])
    else:
        cat.db.executemany("DELETE FROM favourites WHERE kind=? AND key=?", list(keys))
    cat.db.commit()
