"""Magazine covers for coverdisks, from the scanned magazines on the Internet Archive.

A coverdisk is known by its magazine and issue (see coverdisks.py). The Internet Archive holds
scans of most Amiga magazines, one item per issue, titled e.g.
    "Amiga Shopper - Issue 21 (1993-01)(Future Publishing)(GB)", "CU Amiga Magazine Issue 082",
    "Amiga Action #35 (1992-08)", "Amiga Computing Issue 092 Nov 95"
and serves each item's front page as a picture. Find pictures online fetches the cover of each
issue the user has disks from (one search per magazine, cached for a month; one picture per issue)
and every disk of that issue shows it. The covers belong to their publishers: they are kept on
this computer for the user's own use. Nothing about the user's disks is sent: only the magazine's
name is searched for.
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request

from .pictures import CACHE, PIC_DIR, USER_AGENT, Stopped

SEARCH = "https://archive.org/advancedsearch.php"
COVER = "https://archive.org/download/{id}/page/cover_w600.jpg"
THUMB = "https://archive.org/services/img/{id}"
DETAILS = "https://archive.org/details/{id}"
INDEX_DIR = os.path.join(CACHE, "magazines")
MAX_AGE = 30 * 86400            # search a magazine again after a month
RETRY = 30 * 86400              # look again for an issue not found
SKIP = re.compile(r"cover\s*-?\s*dis[ck]|disk scans|scans? \d+ to|cd-?rom|\bdisc\b|special edition|"
                  r"supplement|newsletter|letter|index|complete collection|\bpack\b", re.I)

SCHEMA = """CREATE TABLE IF NOT EXISTS mag_covers (
    magazine TEXT NOT NULL,     -- the magazine as TurboCAT shows it ("Amiga Shopper")
    issue    TEXT NOT NULL,     -- the issue number without leading zeros ("21")
    pic      TEXT,              -- picture file in the pictures folder, or NULL if none was found
    ident    TEXT,              -- the Internet Archive item
    title    TEXT,              -- its title
    looked   REAL,
    PRIMARY KEY (magazine, issue)
)"""


def _ensure(cat):
    cat.db.execute(SCHEMA)


def issue_key(issue):
    """'021' -> '21'; anything that isn't a plain number stays as it is."""
    return issue.lstrip("0") or "0" if issue and issue.isdigit() else (issue or "")


def covers(cat):
    """{(magazine, issue): (picture path, item id, title)} for the covers found so far."""
    _ensure(cat)
    return {(r["magazine"], r["issue"]): (os.path.join(PIC_DIR, r["pic"]), r["ident"], r["title"])
            for r in cat.db.execute("SELECT * FROM mag_covers WHERE pic IS NOT NULL")}


def _words(text):
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def match_issue(magazine, title):
    """The issue number an Internet Archive title is for, if it is a plain issue of this magazine."""
    if SKIP.search(title):
        return None
    mag = r"\s+".join(re.escape(w) for w in _words(magazine).split())
    m = re.match(rf"^{mag}(?:\s+magazine)?\s+(?:issue\s+|no\s+|)0*(\d{{1,3}})\b", _words(title))
    if not m:
        # "Amiga Action #35 (1992-08)": the # is lost with the punctuation, so look for it first
        m2 = re.match(rf"^{re.escape(magazine)}(?:\s+magazine)?\s*(?:-\s*)?#\s*0*(\d{{1,3}})\b", title.strip(), re.I)
        return m2.group(1) if m2 else None
    return m.group(1)


def _get_json(url, stop, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        chunks = []
        while True:
            if stop():
                raise Stopped()
            chunk = r.read(1 << 16)
            if not chunk:
                break
            chunks.append(chunk)
    return json.loads(b"".join(chunks))


def magazine_issues(magazine, stop=lambda: False):
    """{issue: (item id, title)} for a magazine's scanned issues (searched once a month)."""
    os.makedirs(INDEX_DIR, exist_ok=True)
    path = os.path.join(INDEX_DIR, re.sub(r"[^a-z0-9]+", "-", magazine.lower()).strip("-") + ".json")
    try:
        if time.time() - os.path.getmtime(path) < MAX_AGE:
            with open(path) as f:
                return {k: tuple(v) for k, v in json.load(f).items()}
    except (OSError, ValueError):
        pass
    q = f'title:("{magazine}") AND mediatype:texts AND amiga'
    url = SEARCH + "?" + urllib.parse.urlencode(
        [("q", q), ("fl[]", "identifier"), ("fl[]", "title"), ("rows", "1000"), ("output", "json")])
    docs = _get_json(url, stop)["response"]["docs"]
    found = {}
    for d in sorted(docs, key=lambda d: (len(d.get("title", "")), d["identifier"])):
        n = match_issue(magazine, d.get("title", ""))
        if n is not None:
            found.setdefault(issue_key(n), (d["identifier"], d.get("title", "")))
    with open(path + ".part", "w") as f:
        json.dump(found, f)
    os.replace(path + ".part", path)
    return found


def _fetch_picture(ident, stop):
    for url in (COVER.format(id=urllib.parse.quote(ident)), THUMB.format(id=urllib.parse.quote(ident))):
        if stop():
            raise Stopped()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read(4 << 20)
        except Exception:
            continue
        if data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n":
            return data
    return None


def _save(data):
    import hashlib
    os.makedirs(PIC_DIR, exist_ok=True)
    name = hashlib.sha1(data).hexdigest()[:20] + (".jpg" if data[:3] == b"\xff\xd8\xff" else ".png")
    path = os.path.join(PIC_DIR, name)
    if not os.path.exists(path):
        with open(path + ".part", "wb") as f:
            f.write(data)
        os.replace(path + ".part", path)
    return name


def wanted(cat, issues):
    """The (magazine, issue) pairs still to look up: not found yet, and not looked at recently."""
    _ensure(cat)
    done = {(r["magazine"], r["issue"]): r for r in cat.db.execute("SELECT * FROM mag_covers")}
    out = []
    for mag, issue in sorted(set(issues)):
        r = done.get((mag, issue))
        if r is not None and (r["pic"] or time.time() - (r["looked"] or 0) < RETRY):
            continue
        out.append((mag, issue))
    return out


def lookup(cat, issues, progress=None, stop=lambda: False):
    """Fetch the covers of these (magazine, issue) pairs. Returns {looked, found, stopped}."""
    todo = wanted(cat, issues)
    found = looked = 0
    by_mag = {}
    try:
        for i, (mag, issue) in enumerate(todo):
            if stop():
                raise Stopped()
            if progress:
                progress(i, len(todo), f"{mag} #{issue}")
            looked += 1
            if mag not in by_mag:
                try:
                    by_mag[mag] = magazine_issues(mag, stop)
                except Stopped:
                    raise
                except Exception:
                    by_mag[mag] = None             # the search failed: try again next time
            if by_mag[mag] is None:
                continue
            item = by_mag[mag].get(issue)
            pic = None
            if item:
                data = _fetch_picture(item[0], stop)
                pic = _save(data) if data else None
            cat.db.execute(
                """INSERT INTO mag_covers (magazine, issue, pic, ident, title, looked) VALUES (?,?,?,?,?,?)
                   ON CONFLICT(magazine, issue) DO UPDATE SET pic=excluded.pic, ident=excluded.ident,
                   title=excluded.title, looked=excluded.looked""",
                (mag, issue, pic, item[0] if item else None, item[1] if item else None, time.time()))
            cat.db.commit()
            found += bool(pic)
    except Stopped:
        return {"looked": looked, "found": found, "stopped": True}
    if progress:
        progress(len(todo), len(todo), "")
    return {"looked": looked, "found": found, "stopped": False}
