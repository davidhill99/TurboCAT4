"""Look on Aminet for intact copies of files a damaged disk has lost.

Aminet only takes freely distributable software (public domain, freeware, shareware), and holds
the old Fred Fish disks (misc/fish), where much of the late-80s software lives. Each package page
lists every file inside with its exact size, so a match is checked by name AND size before
anything is downloaded; only real matches are downloaded, and only the one file is kept.

What is never looked for:
  - Commodore's own files (Workbench libraries, devices, fonts, C: commands). They are still
    copyrighted, so they come from your own Workbench disks, not the Internet.
  - names too plain to search for ("1", "d", "12"): far too many packages have one.

Everything is cached under ~/.cache/turbocat/aminet: each name is looked up once (results, misses
included, are kept in lookups.json), and found files are kept as files/<sha1>. Planning a repair
reads only that cache, so it never waits on the network.
"""
import datetime
import hashlib
import html
import json
import os
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

from . import pictures

BASE = "https://aminet.net"
CACHE_DIR = os.path.join(pictures.CACHE, "aminet")
LOOKUPS = os.path.join(CACHE_DIR, "lookups.json")
FILES = os.path.join(CACHE_DIR, "files")
RULES = 1                  # raise when the look-up gets better, so earlier misses are tried again
MAX_PACKAGES = 12          # package pages read per name, oldest first
MAX_DOWNLOAD = 20 << 20    # bigger packages are left alone
DELAY = 1.0                # seconds between requests: be kind to Aminet

# Commodore's own files (and ARexx's): never downloaded. Compared without case or ".info".
COMMODORE = set("""
amigaguide.library asl.library bullet.library commodities.library datatypes.library
diskfont.library dos.library exec.library expansion.library gadtools.library graphics.library
icon.library iffparse.library info.library intuition.library keymap.library layers.library
locale.library lowlevel.library mathffp.library mathieeedoubbas.library mathieeedoubtrans.library
mathieeesingbas.library mathieeesingtrans.library mathtrans.library nonvolatile.library
realtime.library rexxsyslib.library rexxsupport.library translator.library utility.library
version.library workbench.library audio.device clipboard.device console.device gameport.device
input.device keyboard.device narrator.device parallel.device printer.device ramdrive.device
scsi.device serial.device timer.device trackdisk.device carddisk.device mfm.device
disk-validator port-handler queue-handler speak-handler aux-handler ram-handler pipe-handler
newcon-handler con-handler shell-seg fastfilesystem crossdosfilesystem cdfilesystem
topaz.font diamond.font emerald.font garnet.font opal.font ruby.font sapphire.font courier.font
helvetica.font times.font xen.font xcourier.font cgtimes.font
addbuffers ask assign avail binddrivers break cd changetaskpri copy date delete dir diskchange
diskdoctor echo ed edit else endcli endif endskip eval execute failat fault filenote getenv if
install join lab list loadwb lock makedir makelink mount newcli newshell path prompt protect quit
relabel remrad rename resident run search set setclock setdate setenv skip sort stack status type
unset unsetenv wait which why setpatch iprefs conclip fastmemfirst setmap addmonitor format
diskcopy say rexxmast iconx cli shell calculator clock notepad preferences iconed initprinter
graphicdump keytoo keytoy cmd printerps printergfx memacs
""".split())


@dataclass
class Hit:
    sha1: str
    package: str            # e.g. "misc/fish/fish-0786.lha"
    inner: str              # the file's path in the package
    date: str = ""          # its date there, YYYY-MM-DD

    @property
    def label(self):
        return f"Aminet {self.package}"


def _key(name, size):
    return f"{name.lower()}|{size}"


def commodore(name):
    base = name.lower()
    if base.endswith(".info"):
        base = base[:-5]
    return base in COMMODORE


def worth_looking(name, size):
    """'' if this name is worth a look, else why not."""
    base = name[:-5] if name.lower().endswith(".info") else name
    if commodore(name):
        return "Commodore's own file: not freely distributable"
    if not size:
        return "empty"
    if len(base.strip()) < 3 or base.startswith(".") or re.fullmatch(r"[\d\W_]+", base):
        return "name too plain to search for"
    return ""


# ---------------------------------------------------------------- the cache

def _load():
    try:
        with open(LOOKUPS, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(data):
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp = LOOKUPS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=0)
    os.replace(tmp, LOOKUPS)


_memo = {"stamp": None, "data": {}}


def _cached():
    try:
        stamp = os.path.getmtime(LOOKUPS)
    except OSError:
        stamp = None
    if stamp != _memo["stamp"]:
        _memo.update(stamp=stamp, data=_load())
    return _memo["data"]


def hits(name, size):
    """Found copies of this file, from the cache only (no network): [Hit]."""
    entry = _cached().get(_key(name, size))
    if not entry:
        return []
    return [Hit(**h) for h in entry.get("hits", []) if os.path.exists(os.path.join(FILES, h["sha1"]))]


def other_versions(name, size):
    """Copies with this name but a different size seen on Aminet: [(package, path, size)]."""
    entry = _cached().get(_key(name, size)) or {}
    return [tuple(o) for o in entry.get("others", [])]


def looked(name, size):
    """True if this file has been looked up already (found or not)."""
    entry = _cached().get(_key(name, size))
    return bool(entry) and entry.get("rules") == RULES


def read_hit(hit):
    with open(os.path.join(FILES, hit.sha1), "rb") as f:
        data = f.read()
    if hashlib.sha1(data).hexdigest() != hit.sha1:
        raise ValueError("TurboCAT's copy of the file from Aminet has changed")
    return data


# ---------------------------------------------------------------- reading Aminet's pages

_MONTHS = {m: i for i, m in enumerate(
    "jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
_ROW = re.compile(r"^(?:\[\w[\w-]*\]|[-dlrwxsStT]{10})\s+(?:\d+/\d+\s+)?(\d+)\s+(\d+)\s+\S+\s+-\w{3}-\s+"
                  r"[0-9a-f]{4}\s+(\w{3})\s+(\d+)\s+([\d:]+)\s(.+)$")


def parse_results(page):
    """Package paths from a search result page, in the order shown."""
    out = []
    for m in re.finditer(r'href="/([a-z]+/[\w+-]+/[^"/\s]+\.(?:lha|lzh))"', page):
        p = m.group(1)
        if p not in out:
            out.append(p)
    return out


def parse_contents(page):
    """[(path in the package, size, YYYY-MM-DD or '')] from a package page's contents list."""
    i = page.find("Contents of")
    if i < 0:
        return []
    pre = page[i:]
    j = pre.find("</pre>")
    out = []
    for line in html.unescape(re.sub(r"<[^>]+>", "", pre[:j if j > 0 else None])).splitlines():
        m = _ROW.match(line.strip())
        if not m:
            continue
        packed, size, mon, day, year, name = m.groups()
        date = ""
        if mon.lower() in _MONTHS and ":" not in year:
            date = f"{int(year):04d}-{_MONTHS[mon.lower()]:02d}-{int(day):02d}"
        out.append((name.strip(), int(size), date))
    return out


class Fetcher:
    """Gets pages and packages, politely (one at a time, a pause between), caching pages."""

    def __init__(self, get=None, delay=DELAY):
        self.get = get or self._get
        self.delay = delay
        self.last = 0.0
        self.requests = 0

    def _get(self, url, limit=None):
        req = urllib.request.Request(url, headers={"User-Agent": pictures.USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as r:
            if limit and int(r.headers.get("Content-Length") or 0) > limit:
                raise ValueError("too big")
            return r.read(limit + 1 if limit else -1)

    def fetch(self, url, limit=None):
        wait = self.last + self.delay - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            self.requests += 1
            return self.get(url, limit) if limit else self.get(url)
        finally:
            self.last = time.monotonic()

    def page(self, url):
        name = hashlib.sha1(url.encode()).hexdigest()
        path = os.path.join(CACHE_DIR, "pages", name)
        try:
            with open(path, "rb") as f:
                return f.read().decode("latin-1")
        except OSError:
            pass
        data = self.fetch(url)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return data.decode("latin-1")


def search_url(name):
    q = urllib.parse.urlencode({"type": "advanced", "content": name, "q_content": "AND",
                                "sort": "date", "ord": "ASC", "search": "search"})
    return f"{BASE}/search?{q}"


def look_up(name, size, fetcher=None, stop=None):
    """Look on Aminet for this file (exact name and size), download any match and keep the file.
    Returns [Hit]. The answer (even 'nothing found') is cached."""
    data = _load()
    key = _key(name, size)
    entry = data.get(key)
    if entry and entry.get("rules") == RULES:
        return hits(name, size)
    found, others = [], []
    why = worth_looking(name, size)
    if not why:
        fetcher = fetcher or Fetcher()
        packages = parse_results(fetcher.page(search_url(name)))
        for pkg in packages[:MAX_PACKAGES]:
            if stop is not None and stop():
                return []                     # not finished: nothing saved, so it's tried again
            listing = parse_contents(fetcher.page(f"{BASE}/package/{pkg.rsplit('.', 1)[0]}"))
            same = [(p, s, d) for p, s, d in listing if p.rsplit("/", 1)[-1].lower() == name.lower()]
            want = [(p, d) for p, s, d in same if s == size]
            others += [[pkg, p, s] for p, s, d in same if s != size]
            if not want:
                continue
            hit = _download(fetcher, pkg, want, size)
            if hit is not None and all(h.sha1 != hit.sha1 for h in found):
                found.append(hit)
    data = _load()                            # another look-up may have saved meanwhile
    data[key] = {"rules": RULES, "checked": datetime.date.today().isoformat(),
                 "skipped": why, "hits": [h.__dict__ for h in found],
                 "others": others[:20]}
    _save(data)
    return found


def _download(fetcher, pkg, want, size):
    """Download a package and keep the wanted file out of it. None if it can't be had."""
    from . import readers
    try:
        blob = fetcher.fetch(f"{BASE}/{pkg}", MAX_DOWNLOAD)
    except Exception:
        return None
    if len(blob) > MAX_DOWNLOAD:
        return None
    res = readers.read_lha(blob)
    for path, date in want:
        for e in res.files:
            if not e.is_dir and e.path.lower() == path.lower():
                try:
                    content = e.read()
                except Exception:
                    continue
                if len(content) != size:
                    continue
                sha = hashlib.sha1(content).hexdigest()
                os.makedirs(FILES, exist_ok=True)
                with open(os.path.join(FILES, sha), "wb") as f:
                    f.write(content)
                return Hit(sha, pkg, e.path, date)
    return None
