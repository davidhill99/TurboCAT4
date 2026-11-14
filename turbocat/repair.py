"""Make repaired copy (repair R4): rebuild a damaged floppy from its readable files plus intact
copies of its damaged files found on other disks in the collection, or (once looked up, see
aminet.py) freely distributable copies found on Aminet.

The original image is only read, never changed. The repaired copy is a NEW disk image, written to
its own folder (~/TurboCAT/Repaired), and is always marked as not an original dump:
  - on the disk: a "Repaired-by-TurboCAT" text file in the root, and a file note on each restored
    file (unless it already had one);
  - in its name: TOSEC's "fixed" flag, [f TurboCAT]; bad-dump and virus flags are dropped when the
    copy is complete;
  - in a log, repairs.csv, which records where every restored file came from, so TurboCAT knows a
    repaired copy by its checksum even if it is renamed.

A replacement is matched by name and size. Its contents can't be compared with the lost file's
(they're what was lost), so each match gets a confidence:
  strong  - one version of the file exists in the collection, found on 2+ disks or with the same
            file date as the lost one
  likely  - one version, found on one disk only
  unsure  - several different versions with that name and size; used only if the user agrees
No Qt here: the window asks and shows; this module plans, builds and checks.
"""
import csv
import datetime
import hashlib
import io
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

from . import VERSION, aminet, bootblock, explain, gotek, paths

REPAIRED_DIR = paths.repaired_dir()
LOG = os.path.join(paths.data_dir(), "repairs.csv")
MARKER = "Repaired-by-TurboCAT"
FLOPPY = ("adf", "adz", "dms")
DD_SIZE = 901120

# Workbench 1.3's standard boot code: used instead of a boot block that looks like a virus
STANDARD_BOOT = bytes.fromhex("43fa00184eaeffa04a80670a20402068001670004e7570ff60fa"
                              "646f732e6c69627261727900")


@dataclass
class Source:
    media_id: int        # the disk or archive the file is in
    number: int          # its top-level item's number (#0215)
    name: str            # that item's file name
    path: str            # the file's path there
    sha1: str
    date: str = ""
    online: str = ""     # found on Aminet: the package it came from ("misc/fish/fish-0786.lha")

    @property
    def label(self):
        """Where it came from, for people: '#0215 Disk.adf' or 'Aminet misc/fish/fish-0786.lha'."""
        return f"Aminet {self.online}" if self.online else f"#{self.number:04d} {self.name}"

    @property
    def short(self):
        return "Aminet" if self.online else f"#{self.number:04d}"


@dataclass
class Lost:
    path: str
    size: int
    date: str = ""
    sources: List[Source] = field(default_factory=list)
    versions: int = 0                 # different checksums among the sources
    use: Optional[Source] = None      # the replacement picked
    confidence: str = "none"          # strong, likely, unsure, none

    @property
    def name(self):
        return os.path.basename(self.path)


@dataclass
class Plan:
    top_id: int
    disk_id: int
    number: int
    title: str
    source_file: str                  # the damaged image's own file (top level)
    lost: List[Lost]
    total_files: int = 0
    tidy: bool = False                # every file reads; only the disk's index (directory) is wrong

    def usable(self, with_unsure=False):
        ok = ("strong", "likely", "unsure") if with_unsure else ("strong", "likely")
        return [x for x in self.lost if x.use is not None and x.confidence in ok]

    def complete(self, with_unsure=False):
        return len(self.usable(with_unsure)) == len(self.lost)

    def out_name(self, with_unsure=False):
        return repaired_name(self.source_file, self.complete(with_unsure))


@dataclass
class Result:
    path: str
    restored: List[Lost]
    missing: List[Lost]
    notes: List[str]
    sha1: str
    original: str = ""        # the damaged disk's file name


# ---------------------------------------------------------------- planning

class Index:
    """The catalogue's item tree, read once, so planning many disks stays quick."""

    def __init__(self, cat):
        rows = cat.db.execute("SELECT id, parent_id, number, source FROM media").fetchall()
        self.parent = {r["id"]: r["parent_id"] for r in rows}
        self.info = {r["id"]: r for r in rows}
        self.children = {}
        for r in rows:
            if r["parent_id"]:
                self.children.setdefault(r["parent_id"], []).append(r["id"])
        self.top = {}
        for mid in self.parent:            # from the same rows, so it can't go out of step
            t = mid
            while self.parent.get(t):
                t = self.parent[t]
            self.top[mid] = t

    def descendants(self, mid):
        out, todo = [], [mid]
        while todo:
            for c in self.children.get(todo.pop(), ()):
                out.append(c)
                todo.append(c)
        return out


def _top(cat, media_id):
    m = cat.media_by_id(media_id)
    while m is not None and m["parent_id"]:
        m = cat.media_by_id(m["parent_id"])
    return m


def _descendants(cat, top_id):
    out, todo = [], [top_id]
    while todo:
        i = todo.pop()
        for r in cat.db.execute("SELECT * FROM media WHERE parent_id=?", (i,)):
            out.append(r)
            todo.append(r["id"])
    return out


def damaged_disk(cat, top_id, ix=None):
    """The floppy image in this item that has damaged files (the item itself, or the ADF in its
    ZIP), or None."""
    top = cat.media_by_id(top_id)
    if top is None:
        return None
    rows = ([top] + [cat.media_by_id(i) for i in ix.descendants(top_id)] if ix is not None
            else [top] + _descendants(cat, top_id))
    for r in rows:
        if r["kind"] in FLOPPY and explain.damaged_paths(_j(r["problems"])):
            return r
    return None


def _j(s):
    import json
    try:
        return json.loads(s) if s else []
    except ValueError:
        return []


def plan(cat, top_id, ix=None):
    """What a repaired copy of this item would get, or None if it has no damaged floppy.
    ix: an Index, when planning many disks."""
    disk = damaged_disk(cat, top_id, ix)
    if disk is None:
        return None
    top = cat.media_by_id(top_id)
    own = [top_id] + (ix.descendants(top_id) if ix is not None
                      else [r["id"] for r in _descendants(cat, top_id)])
    marks = ",".join("?" * len(own))
    lost = []
    for path in explain.damaged_paths(_j(disk["problems"])):
        row = cat.db.execute("SELECT size, date FROM files WHERE media_id=? AND path=?",
                             (disk["id"], path)).fetchone()
        if row is None:
            continue
        item = Lost(path, row["size"] or 0, row["date"] or "")
        if item.size:
            for f in cat.db.execute(
                    f"SELECT f.media_id, f.path, f.sha1, f.date, m.kind FROM files f "
                    f"JOIN media m ON m.id=f.media_id "
                    f"WHERE f.name=? COLLATE NOCASE AND f.size=? AND f.sha1 IS NOT NULL "
                    f"AND NOT f.is_dir AND f.media_id NOT IN ({marks})",
                    (os.path.basename(path), item.size, *own)):
                if f["kind"] not in FLOPPY + ("zip", "lha"):
                    continue          # can't take a single file out of that yet
                if ix is not None and f["media_id"] not in ix.top:
                    continue          # added by a scan still running: next time
                t = ix.info[ix.top[f["media_id"]]] if ix is not None else _top(cat, f["media_id"])
                item.sources.append(Source(f["media_id"], t["number"] or 0,
                                           os.path.basename(t["source"].rstrip("/")),
                                           f["path"], f["sha1"], f["date"] or ""))
        if item.size and not item.sources:          # found on Aminet earlier (from the cache only)
            for h in aminet.hits(item.name, item.size):
                item.sources.append(Source(0, 0, "Aminet", h.inner, h.sha1, h.date, online=h.package))
        _judge(item)
        lost.append(item)
    total = cat.db.execute("SELECT COUNT(*) FROM files WHERE media_id=? AND NOT is_dir",
                           (disk["id"],)).fetchone()[0]
    return Plan(top_id, disk["id"], top["number"] or 0, disk["volume"] or "",
                os.path.basename(top["source"].rstrip("/")), lost, total)


def _judge(item):
    """Pick a replacement and say how sure TurboCAT is."""
    by_sha = {}
    for s in item.sources:
        by_sha.setdefault(s.sha1, []).append(s)
    item.versions = len(by_sha)
    if not by_sha:
        item.confidence = "none"
        return
    if len(by_sha) == 1:
        group = next(iter(by_sha.values()))
        same_date = item.date and any(s.date == item.date or (s.online and s.date == item.date[:10])
                                      for s in group)
        item.use = group[0]
        item.confidence = "strong" if len({s.number for s in group}) > 1 or same_date else "likely"
        return
    dated = [g for g in by_sha.values() if item.date and any(s.date == item.date for s in g)]
    if len(dated) == 1:                       # the only version with the lost file's date
        item.use, item.confidence = dated[0][0], "likely"
        return
    best = max(by_sha.values(), key=len)      # else the version found most often
    item.use, item.confidence = best[0], "unsure"


_plans = {}


def plan_all(cat, top_ids=None):
    """Plans for every damaged item (or those given): {top id: Plan}. The plans for every item are
    remembered until the catalogue (anything added, removed or read again) or the repair log
    changes, since the window asks for them on every reload."""
    if top_ids is None:
        try:
            log_stamp = os.path.getmtime(LOG)
        except OSError:
            log_stamp = None
        try:                                   # files found on Aminet change the plans too
            log_stamp = (log_stamp, os.path.getmtime(aminet.LOOKUPS))
        except OSError:
            pass
        stamp = (getattr(cat, "path", id(cat)), tuple(cat.db.execute(
            "SELECT COUNT(*), MAX(id), MAX(scanned_at) FROM media").fetchone()), log_stamp)
        if _plans.get("stamp") != stamp:
            _plans.update(stamp=stamp, plans=_plan_all(cat))
        return dict(_plans["plans"])
    return _plan_all(cat, top_ids)


def _plan_all(cat, top_ids=None):
    ix = Index(cat)
    if top_ids is None:
        # a scan still running can add a disk between reading the tree and this query: it is
        # planned on the next reload, since the catalogue's stamp has changed by then (issue #1)
        bad = {ix.top[r["id"]] for r in cat.db.execute(
            "SELECT id FROM media WHERE kind IN ('adf','adz','dms') AND problems LIKE '%file unreadable%'")
            if r["id"] in ix.top}
        top_ids = sorted(bad)
    out = {}
    for t in top_ids:
        p = plan(cat, t, ix)
        if p is not None:
            out[t] = p
    return out


# How the scan words a directory error on a disk whose files all read (readers.py)
FS_ISSUE = "filesystem inconsistency, but every file reads: "


def untidy_disk(cat, top_id):
    """The floppy image in this item whose index (directory) has errors although every file reads,
    or None."""
    top = cat.media_by_id(top_id)
    if top is None:
        return None
    for r in [top] + _descendants(cat, top_id):
        if r["kind"] in FLOPPY and any(FS_ISSUE in w for w in _j(r["warnings"])) \
                and not explain.damaged_paths(_j(r["problems"])):
            return r
    return None


def tidy_plan(cat, top_id):
    """A plan for a tidied copy: the same files, in a fresh, correct index. None if the item has
    no such disk."""
    disk = untidy_disk(cat, top_id)
    if disk is None:
        return None
    top = cat.media_by_id(top_id)
    total = cat.db.execute("SELECT COUNT(*) FROM files WHERE media_id=? AND NOT is_dir",
                           (disk["id"],)).fetchone()[0]
    return Plan(top_id, disk["id"], top["number"] or 0, disk["volume"] or "",
                os.path.basename(top["source"].rstrip("/")), [], total, tidy=True)


def repaired_name(name, complete):
    """'Disk (1991)(PD)[v Saddam][b virus damage].zip' -> 'Disk (1991)(PD)[f TurboCAT].adf'.
    A partial repair keeps [b]: it is still missing files."""
    stem = re.sub(r"\.(zip|adf|adz|dms|lha|lzh|gz)$", "", name, flags=re.I)
    tags = re.findall(r"\[[^\]]*\]", stem)
    base = re.sub(r"\s*\[[^\]]*\]", "", stem).rstrip()
    keep = [t for t in tags if not t[1:].startswith(("b", "v", "f TurboCAT"))]
    if not complete:
        keep.append("[b]")
    return f"{base}{''.join(keep)}[f TurboCAT].adf"


# ---------------------------------------------------------------- reading

def _media_bytes(cat, media_id):
    """The raw bytes of a catalogued item: read from its file, unpacked from what holds it."""
    chain = []
    m = cat.media_by_id(media_id)
    while m is not None:
        chain.append(m)
        m = cat.media_by_id(m["parent_id"]) if m["parent_id"] else None
    chain.reverse()
    with open(chain[0]["source"], "rb") as f:
        data = f.read()
    for outer, inner in zip(chain, chain[1:]):
        data = _take(data, outer["kind"], inner["inner_path"])
    return data


def _take(data, kind, path):
    """One file out of a container held in memory: an archive (ZIP, LHA, including old -lh1-
    ones through lha) or an AmigaDOS disk image (ADF, ADZ, DMS)."""
    from . import readers
    if kind in FLOPPY:
        return bytes(_node(_volume(gotek._unpack_floppy(kind, data)), path).get_file_data())
    if kind == "zip":
        return gotek._open_inner(data, kind, path)
    if kind == "lha":
        res = readers.read_lha(data)
        for want in (path, path.lower()):
            for e in res.files:
                if not e.is_dir and (e.path if want is path else e.path.lower()) == want:
                    return e.read()
        raise ValueError(f"{path} not found in the LHA archive")
    raise ValueError(f"files can't be taken out of {kind.upper()} archives yet")


def _volume(adf):
    from amitools.fs.ADFSVolume import ADFSVolume
    from amitools.fs.blkdev.ADFBlockDevice import ADFBlockDevice
    hd = len(adf) >= 2 * DD_SIZE
    size = 2 * DD_SIZE if hd else DD_SIZE      # an overdump is read at its normal size
    adf = bytes(adf[:size]).ljust(size, b"\0")
    dev = ADFBlockDevice(None, read_only=True, fobj=io.BytesIO(adf), hd=hd)
    dev.open()
    vol = ADFSVolume(dev)
    vol.open()
    return vol


def _node(vol, path):
    from amitools.fs.FSString import FSString
    return vol.get_path_name(FSString(path))


def read_source(cat, src):
    """The replacement file's bytes, checked against the catalogue (or the Aminet cache)."""
    if src.online:
        return aminet.read_hit(aminet.Hit(src.sha1, src.online, src.path, src.date))
    m = cat.media_by_id(src.media_id)
    data = _take(_media_bytes(cat, src.media_id), m["kind"], src.path)
    if hashlib.sha1(data).hexdigest() != src.sha1:
        raise ValueError(f"#{src.number:04d} has changed since it was catalogued")
    return data


# ---------------------------------------------------------------- building

def build(cat, p, out_dir=None, with_unsure=False, mark=True, log=None):
    """Write the repaired copy. Returns a Result. The original is only read."""
    out_dir = out_dir or REPAIRED_DIR
    log = LOG if log is None else log
    from amitools.fs.ADFSVolume import ADFSVolume
    from amitools.fs.FSString import FSString
    from amitools.fs.MetaInfo import MetaInfo
    from amitools.fs.blkdev.ADFBlockDevice import ADFBlockDevice

    adf = gotek.adf_bytes(cat, p.disk_id)          # checks it hasn't changed since the scan
    hd = len(adf) > DD_SIZE
    old = _volume(adf)
    notes, failed = [], []
    use = {x.path: x for x in p.usable(with_unsure)}
    data_for = {}
    for path, x in list(use.items()):
        # any copy with the same checksum will do: plain disks first, then the one picked
        same = sorted((s for s in x.sources if s.sha1 == x.use.sha1),
                      key=lambda s: (bool(s.online) or cat.media_by_id(s.media_id)["kind"] not in FLOPPY,
                                     s is not x.use))
        why = ""
        for s in same:
            try:
                data_for[path] = read_source(cat, s)
                x.use = s
                break
            except Exception as ex:
                why = why or str(ex)
        else:
            failed.append(x)
            notes.append(f"{x.name} not restored: no copy of it could be read ({why})")
            del use[path]

    boot = bootblock.analyse(adf[:1024])
    if "SUSPICIOUS" in boot["kind"]:
        boot_code = STANDARD_BOOT
        notes.append("The original boot block looked like a virus, so the standard Workbench "
                     "boot block was written instead.")
    elif boot["bootable"]:
        boot_code = adf[12:1024]
    else:
        boot_code = None

    fobj = io.BytesIO()
    dev = ADFBlockDevice(None, fobj=fobj, hd=hd)
    dev.create()
    new = ADFSVolume(dev)
    new.create(old.get_volume_name(), meta_info=old.get_meta_info(), dos_type=old.get_dos_type(),
               boot_code=boot_code)
    today = datetime.date.today().isoformat()
    restored, extra = [], []

    def copy(src_dir, dst_dir, prefix):
        taken = {}                        # names used in this folder (AmigaDOS ignores case): data
        for e in src_dir.get_entries_sorted_by_name():
            name = e.get_file_name().get_unicode_name()
            path = prefix + name
            mi = e.get_meta_info()
            if name.lower() in taken:
                # A broken index can list one name twice. The same file again is left out;
                # anything else is kept under a new name. Either way the marker note says so.
                try:
                    data = None if e.is_dir() else bytes(e.get_file_data())
                except Exception:
                    data = None
                if not e.is_dir() and data is not None and data == taken[name.lower()]:
                    notes.append(f"{path} was listed twice in the original's index; the copy has it once.")
                    continue
                n = 2
                while f"{name}.{n}".lower() in taken:
                    n += 1
                notes.append(f"{path} was listed twice in the original's index, with different "
                             f"contents; the second is kept as {name}.{n}.")
                name, path = f"{name}.{n}", f"{prefix}{name}.{n}"
            if e.is_dir():
                taken[name.lower()] = None
                d = dst_dir.create_dir(FSString(name), meta_info=mi, update_ts=False)
                copy(e, d, path + "/")
                continue
            if path in use:
                x = use[path]
                comment = mi.get_comment()
                if mark and (comment is None or not comment.get_unicode()):
                    comment = FSString(f"Restored by TurboCAT {today} from {x.use.short}"[:79])
                mi = MetaInfo(protect=mi.get_protect(), mod_ts=mi.get_mod_ts(), comment=comment)
                taken[name.lower()] = data_for[path]
                dst_dir.create_file(FSString(name), data_for[path], meta_info=mi, update_ts=False)
                restored.append(x)
                continue
            if any(x.path == path for x in p.lost):
                continue                  # damaged and nothing to put back: left out
            try:
                data = bytes(e.get_file_data())
            except Exception:             # damaged, though the scan didn't say so: left out too
                extra.append(Lost(path, e.get_size()))
                continue
            taken[name.lower()] = data
            dst_dir.create_file(FSString(name), data, meta_info=mi, update_ts=False)

    copy(old.get_root_dir(), new.get_root_dir(), "")
    missing = [x for x in p.lost if x not in restored] + extra
    if mark:
        text = _marker_text(p, restored, missing, notes)
        try:
            new.get_root_dir().create_file(FSString(MARKER), text.encode("latin-1", "replace"),
                                           update_ts=False)
        except Exception:
            notes.append(f"The disk is too full for the {MARKER} note; the name and TurboCAT's "
                         "log still mark it as repaired.")
    new.close()
    dev.flush()
    out = fobj.getvalue()
    gone = {x.path for x in extra}
    kept = {}                     # path -> its checksums (a broken index can list a name twice)
    for r in cat.db.execute(
            "SELECT path, sha1 FROM files WHERE media_id=? AND NOT is_dir AND sha1 IS NOT NULL",
            (p.disk_id,)):
        if r["path"] not in gone:
            kept.setdefault(r["path"], set()).add(r["sha1"])
    _check(out, restored, data_for, kept)

    os.makedirs(out_dir, exist_ok=True)
    path = _unique(os.path.join(out_dir, repaired_name(p.source_file, not missing)))
    with open(path, "xb") as f:
        f.write(out)
    sha = hashlib.sha1(out).hexdigest()
    if log:
        _log(log, p, path, sha, restored, missing)
    return Result(path, restored, missing, notes, sha, p.source_file)


def _check(out, restored, data_for, kept):
    """Read the new disk back: no filesystem errors, every restored file as planned, and every
    other file exactly as it was on the original."""
    from . import readers
    res = readers.read_adf(out)
    if res.problems:
        raise ValueError("the repaired copy didn't check out: " + res.problems[0])
    if res.fs_issues:
        raise ValueError("the new copy's index still has errors: " + res.fs_issues[0])
    vol = _volume(out)
    for x in restored:
        if bytes(_node(vol, x.path).get_file_data()) != data_for[x.path]:
            raise ValueError(f"{x.name} didn't read back correctly")
    for path, shas in kept.items():
        if hashlib.sha1(bytes(_node(vol, path).get_file_data())).hexdigest() not in shas:
            raise ValueError(f"{path} didn't copy across correctly")


def _marker_text(p, restored, missing, notes):
    if p.tidy:
        lines = [
            "This disk was tidied by TurboCAT " + VERSION + " on " + datetime.date.today().isoformat() + ".",
            "It is NOT an original dump.",
            "",
            "Original: " + p.source_file,
            "Every file was copied across unchanged into a fresh disk with a correct",
            "directory: the errors in the original's directory are gone.",
        ]
        return "\n".join(lines + ([""] + notes if notes else [])) + "\n"
    lines = [
        "This disk was repaired by TurboCAT " + VERSION + " on " + datetime.date.today().isoformat() + ".",
        "It is NOT an original dump.",
        "",
        "Original: " + p.source_file,
        f"{len(restored)} damaged file(s) were replaced with copies found on other disks"
        + (" or on Aminet (freely distributable):" if any(x.use.online for x in restored) else ":"),
    ]
    lines += [f"  {x.path}  from {x.use.label}" for x in restored]
    if missing:
        lines += ["", "Still damaged, left out:"] + [f"  {x.path}" for x in missing]
    if notes:
        lines += [""] + notes
    return "\n".join(lines) + "\n"


def _unique(path):
    base, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(path):
        path = f"{base} ({n}){ext}"
        n += 1
    return path


def _log(log, p, path, sha, restored, missing=()):
    os.makedirs(os.path.dirname(log), exist_ok=True)
    new = not os.path.exists(log)
    with open(log, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["date", "original", "repaired copy", "repaired sha1", "file", "from", "file sha1"])
        for x in restored:
            w.writerow([datetime.date.today().isoformat(), p.source_file, path, sha, x.path,
                        x.use.label, x.use.sha1])
        if p.tidy:                   # nothing replaced: one line saying what was done
            w.writerow([datetime.date.today().isoformat(), p.source_file, path, sha,
                        "(the disk's index)", TIDIED, ""])
        for x in missing:            # still damaged: "from" left empty
            w.writerow([datetime.date.today().isoformat(), p.source_file, path, sha, x.path, "", ""])


TIDIED = "rebuilt by TurboCAT"         # the log's "from" for a tidied copy

# What to tell the user when a repaired copy is still missing files
FINISH_IT = ("To fix it fully, either:\n"
             "• get a good copy of the disk. Free disks (public domain, freeware, shareware) are "
             "usually on Aminet or the Internet Archive; or\n"
             "• Tools › Look on Aminet for missing files: freely distributable files with exactly "
             "the same name and size are downloaded and used; or\n"
             "• put disks that have the missing files in a folder TurboCAT scans, and press F5. The "
             "disk will then say \u201cCan be fully rebuilt now\u201d, and Fix all can make a complete copy.")


def log_for(sha, log=None):
    """What the log says about one repaired copy: [(file, from)]; from is "" for a file that is
    still missing."""
    log = log or LOG
    try:
        with open(log, newline="", encoding="utf-8") as fh:
            return [(r["file"], r["from"]) for r in csv.DictReader(fh) if r["repaired sha1"] == sha]
    except OSError:
        return []


def copies_of(log=None):
    """{original's file name: [checksums of its repaired copies]}, from the log."""
    log = log or LOG
    out = {}
    try:
        with open(log, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                shas = out.setdefault(r["original"], [])
                if r["repaired sha1"] not in shas:
                    shas.append(r["repaired sha1"])
    except OSError:
        pass
    return out


def repaired_sha1s(log=None):
    """Checksums of every repaired copy TurboCAT has made."""
    log = log or LOG
    try:
        with open(log, newline="", encoding="utf-8") as fh:
            return {r["repaired sha1"] for r in csv.DictReader(fh)}
    except OSError:
        return set()
