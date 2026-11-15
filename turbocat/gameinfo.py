"""What is known about a game or utility: its genre, who made it, when it came out, how many can
play, a few lines from Wikipedia, and links to Hall of Light, Lemon Amiga and MobyGames.

It comes from Wikidata (one list of about 2,000 Amiga titles, fetched once and then every two
months) and Wikipedia (a short summary for each title found in the catalogue, fetched slowly in
the background, one at a time). Wikidata is sent nothing about the user's disks: the list is the
same for everyone. Wikipedia is asked for each title found, by its article's title.
"""
import json
import os
import time
import urllib.parse
import urllib.request

from . import paths
from .pictures import USER_AGENT, Stopped, clean_title, item_key, item_titles, loose, normal

CACHE = paths.cache_dir()
LIST_FILE = os.path.join(CACHE, "wikidata-amiga.json")
LIST_MAX_AGE = 60 * 86400
SPARQL = "https://query.wikidata.org/sparql"
SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"
CONSENT = "online_info"      # meta: the user agreed to look up games and utilities online
RULES = 1                    # bump when the matching improves, so items are matched again
PAUSE = 1.0                  # seconds between Wikipedia requests (be polite, and keep the load low)

LINKS = {"hol": ("Hall of Light", "https://amiga.abime.net/{}"),
         "lemon": ("Lemon Amiga", "https://www.lemonamiga.com/games/details.php?id={}"),
         "moby": ("MobyGames", "https://www.mobygames.com/game/{}"),
         "wp": ("Wikipedia", "https://en.wikipedia.org/wiki/{}")}

# Amiga, CD32, CDTV (platform), AmigaOS and AmigaDOS (operating system: applications)
QUERY = """
SELECT ?x ?label (GROUP_CONCAT(DISTINCT ?alt; separator="|") AS ?alts) (MIN(YEAR(?date)) AS ?year)
  (GROUP_CONCAT(DISTINCT ?genreL; separator="|") AS ?genres)
  (GROUP_CONCAT(DISTINCT ?devL; separator="|") AS ?devs)
  (GROUP_CONCAT(DISTINCT ?pubL; separator="|") AS ?pubs)
  (GROUP_CONCAT(DISTINCT ?modeL; separator="|") AS ?modes)
  (SAMPLE(?hol) AS ?hol) (SAMPLE(?lemon) AS ?lemon) (SAMPLE(?moby) AS ?moby) (SAMPLE(?wp) AS ?wp)
  (SAMPLE(?desc) AS ?desc)
WHERE {
  VALUES ?p { wd:Q100047 wd:Q695161 wd:Q955368 wd:Q380526 wd:Q1053058 }
  { ?x wdt:P400 ?p } UNION { ?x wdt:P306 ?p }
  ?x rdfs:label ?label . FILTER(LANG(?label) = "en")
  OPTIONAL { ?x skos:altLabel ?alt . FILTER(LANG(?alt) = "en") }
  OPTIONAL { ?x schema:description ?desc . FILTER(LANG(?desc) = "en") }
  OPTIONAL { ?x wdt:P577 ?date }
  OPTIONAL { ?x wdt:P136 ?g . ?g rdfs:label ?genreL . FILTER(LANG(?genreL) = "en") }
  OPTIONAL { ?x wdt:P178 ?d . ?d rdfs:label ?devL . FILTER(LANG(?devL) = "en") }
  OPTIONAL { ?x wdt:P123 ?u . ?u rdfs:label ?pubL . FILTER(LANG(?pubL) = "en") }
  OPTIONAL { ?x wdt:P404 ?m . ?m rdfs:label ?modeL . FILTER(LANG(?modeL) = "en") }
  OPTIONAL { ?x wdt:P4671 ?hol }
  OPTIONAL { ?x wdt:P4846 ?lemon }
  OPTIONAL { ?x wdt:P1933 ?moby }
  OPTIONAL { ?a schema:about ?x ; schema:isPartOf <https://en.wikipedia.org/> ; schema:name ?wp }
}
GROUP BY ?x ?label
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS about (
    key       TEXT PRIMARY KEY,   -- the item's key, as in thumbs
    qid       TEXT,               -- its Wikidata entry ('' when none matched)
    rules     INTEGER
);
CREATE TABLE IF NOT EXISTS about_text (
    qid       TEXT PRIMARY KEY,
    extract   TEXT,               -- Wikipedia's summary ('' when it has none)
    got_at    REAL
);
"""

_MODES = {"single-player video game": "1 player", "multiplayer video game": "multiplayer",
          "co-op mode": "co-op", "two-player video game": "2 players"}


def ensure_schema(cat):
    cat.db.executescript(SCHEMA)


def _get(url, timeout=60, stop=lambda: False, accept="application/json"):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    chunks = []
    with urllib.request.urlopen(req, timeout=timeout) as r:
        while True:
            if stop():
                raise Stopped()
            chunk = r.read(1 << 16)
            if not chunk:
                break
            chunks.append(chunk)
    return b"".join(chunks)


def _compact(bindings):
    """Wikidata's answer, cut down to what is shown: {qid: entry}."""
    out = {}
    for b in bindings:
        v = {k: x["value"] for k, x in b.items()}
        qid = v["x"].rsplit("/", 1)[-1]
        split = lambda k: [s for s in v.get(k, "").split("|") if s]
        e = {"t": v.get("label", "")}
        for short, long in (("a", "alts"), ("g", "genres"), ("d", "devs"), ("p", "pubs"), ("m", "modes")):
            if split(long):
                e[short] = split(long)
        for k in ("hol", "lemon", "moby", "wp"):
            if v.get(k):
                e[k] = v[k]
        if v.get("year", "").isdigit():
            e["y"] = int(v["year"])
        if v.get("desc"):
            e["s"] = v["desc"]
        out[qid] = e
    return out


def fetch_list(stop=lambda: False, force=False):
    """{qid: entry} for every Amiga title on Wikidata: kept on this computer, fetched again after
    two months (the last copy is used if Wikidata can't be reached)."""
    try:
        fresh = time.time() - os.path.getmtime(LIST_FILE) < LIST_MAX_AGE
    except OSError:
        fresh = False
    if fresh and not force:
        return read_list()
    try:
        raw = _get(SPARQL + "?" + urllib.parse.urlencode({"query": QUERY}), timeout=120, stop=stop,
                   accept="application/sparql-results+json")
        data = _compact(json.loads(raw)["results"]["bindings"])
    except Stopped:
        raise
    except Exception:
        old = read_list()
        if old:
            return old
        raise
    os.makedirs(CACHE, exist_ok=True)
    with open(LIST_FILE + ".part", "w") as f:
        json.dump(data, f)
    os.replace(LIST_FILE + ".part", LIST_FILE)
    _read_cached.cache_clear()
    return data


def read_list():
    """The list kept on this computer ({} if it hasn't been fetched yet)."""
    try:
        return _read_cached(os.path.getmtime(LIST_FILE))
    except OSError:
        return {}


def _lru(fn):
    import functools
    return functools.lru_cache(maxsize=1)(fn)


@_lru
def _read_cached(_mtime):
    try:
        with open(LIST_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def index(entries):
    """name key -> qid. A name two titles share is dropped (unless only one is on Hall of Light,
    the Amiga game database: then that one is meant)."""
    seen = {}
    for qid, e in entries.items():
        for name in [e.get("t", "")] + e.get("a", []):
            for key in (normal(name), "~" + loose(name)):
                if len(key.lstrip("~")) < 4:       # "Go", "Pong": too easily something else
                    continue
                seen.setdefault(key, set()).add(qid)
    out = {}
    for key, qids in seen.items():
        if len(qids) > 1:
            on_hol = [q for q in qids if "hol" in entries[q]]
            if len(on_hol) != 1:
                continue
            qids = on_hol
        out[key] = next(iter(qids))
    return out


def match(titles, idx):
    """The qid for the first of an item's names that is known, exact names before loose ones."""
    for key in [normal(n) for n in titles] + ["~" + loose(n) for n in titles]:
        if key in idx:
            return idx[key]
    return ""


def lookup(cat, progress=None, stop=lambda: False, known=None, which=None, pace=lambda: None):
    """Match the catalogue's games and utilities to Wikidata, then fetch Wikipedia's summary of
    each title found that hasn't got one yet, slowly. known: {top id: proper name} from the
    checksum lists; which: the top ids to look at (games and utilities), None for all.
    pace(): called between steps, to wait while the user is busy."""
    ensure_schema(cat)
    known = known or {}
    if progress:
        progress("list", 0, 0, "")
    try:
        entries = fetch_list(stop)
    except Stopped:
        return {"matched": 0, "texts": 0, "stopped": True}
    except Exception as ex:                  # offline, or Wikidata busy: next time
        return {"matched": 0, "texts": 0, "error": str(ex) or type(ex).__name__}
    idx = index(entries)
    done = {r["key"]: r["rules"] for r in cat.db.execute("SELECT key, rules FROM about")}
    rows = [m for m in cat.db.execute("SELECT * FROM media WHERE parent_id IS NULL ORDER BY number")
            if (which is None or m["id"] in which) and done.get(item_key(m)) != RULES
            and m["status"] != "empty" and m["kind"] not in ("folder", "module", "kickstart")]
    matched = 0
    for i, m in enumerate(rows):
        if stop():
            cat.db.commit()
            return {"matched": matched, "texts": 0, "stopped": True}
        if i % 200 == 0:
            pace()
            if progress:
                progress("match", i, len(rows), "")
        titles = item_titles(cat, m)
        if m["id"] in known:
            titles = [clean_title(known[m["id"]])] + titles
        qid = match(titles, idx)
        matched += bool(qid)
        cat.db.execute("INSERT OR REPLACE INTO about (key, qid, rules) VALUES (?,?,?)",
                       (item_key(m), qid, RULES))
    cat.db.commit()

    # Wikipedia's summaries, for the titles found that have an article and no summary yet
    have = {r[0] for r in cat.db.execute("SELECT qid FROM about_text")}
    want = sorted({r[0] for r in cat.db.execute("SELECT DISTINCT qid FROM about WHERE qid != ''")}
                  - have)
    want = [q for q in want if q in entries and entries[q].get("wp")]
    got = 0
    for i, qid in enumerate(want):
        if stop():
            return {"matched": matched, "texts": got, "stopped": True}
        pace()
        e = entries[qid]
        if progress:
            progress("text", i, len(want), e.get("t", ""))
        try:
            raw = _get(SUMMARY + urllib.parse.quote(e["wp"].replace(" ", "_"), safe=""), timeout=20,
                       stop=stop)
            extract = (json.loads(raw).get("extract") or "").strip()
        except Stopped:
            return {"matched": matched, "texts": got, "stopped": True}
        except Exception:
            extract = None                     # try again next time
        if extract is not None:
            cat.db.execute("INSERT OR REPLACE INTO about_text (qid, extract, got_at) VALUES (?,?,?)",
                           (qid, extract, time.time()))
            cat.db.commit()
            got += 1
        time.sleep(PAUSE)
    return {"matched": matched, "texts": got, "stopped": False}


def about_by_key(cat):
    """{item key: qid} for the items matched to Wikidata (for the list)."""
    try:
        return {r[0]: r[1] for r in cat.db.execute("SELECT key, qid FROM about WHERE qid != ''")}
    except Exception:                      # not looked up yet: no table
        return {}


def qid_for(cat, key):
    """The Wikidata entry an item was matched to ('' if none, or not looked up yet)."""
    if not key:
        return ""
    try:
        row = cat.db.execute("SELECT qid FROM about WHERE key=?", (key,)).fetchone()
    except Exception:                      # not looked up yet: no table
        return ""
    return row[0] if row else ""


def facts(cat, qid):
    """What to show for a matched item: a dict with title, summary, genres, developers, publishers,
    year, players and links [(name, url)], or None."""
    e = read_list().get(qid)
    if not e:
        return None
    try:
        row = cat.db.execute("SELECT extract FROM about_text WHERE qid=?", (qid,)).fetchone()
    except Exception:
        row = None
    modes = []
    for m in e.get("m", []):
        m = _MODES.get(m, m)
        if m not in modes:
            modes.append(m)
    links = [(LINKS[k][0], LINKS[k][1].format(urllib.parse.quote(e[k].replace(" ", "_"))))
             for k in ("hol", "lemon", "moby", "wp") if e.get(k)]
    links.append(("Wikidata", f"https://www.wikidata.org/wiki/{qid}"))
    return {"title": e.get("t", ""), "summary": (row[0] if row else "") or "",
            "what": e.get("s", ""), "genres": e.get("g", []), "developers": e.get("d", []),
            "publishers": e.get("p", []), "year": e.get("y"), "players": modes, "links": links}
