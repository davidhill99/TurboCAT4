"""Versions: the same disk in several TOSEC variants.

Collections such as TOSEC keep every known variant of a disk, told apart by tags in square
brackets: "PD Games Volume 001 (199x)(The Assassins)(PD)[h ALE].zip" is a hacked version of
"... (PD).zip". They are not duplicates (the bytes differ), but most people want one of them.
With grouping on, TurboCAT shows one version of each title and hides the others; nothing is
deleted. The version shown is a verified [!] dump if there is one, then one without tags, then
the fewest tags, avoiding bad dumps; the user can choose another, remembered by file path.
"""
import os
import re

CHOICES = "version_keep"       # meta: {version key: path of the version the user chose}
_TAG = re.compile(r"\[([^\]]*)\]")
_EXT = re.compile(r"\.(zip|adf|adz|dms|lha|lzh|lzx|ipf|hdf|7z|rar|gz)$", re.I)
STATUS_RANK = {"ok": 0, "warning": 1, "error": 2, "empty": 3}

# What TOSEC's tags mean (the first letters decide: [cr ...] before [c], [tr] before [t]).
MEANINGS = [
    ("!", "verified good dump"), ("cr", "cracked"), ("tr", "translated"), ("a", "alternate version"),
    ("b", "bad dump (damaged)"), ("f", "fixed"), ("h", "hacked"), ("m", "modified"),
    ("o", "overdump (extra data at the end)"), ("p", "pirate copy"), ("t", "trained (cheats added)"),
    ("u", "underdump (data missing)"), ("v", "virus infected"),
]


def tags(name):
    return _TAG.findall(os.path.basename(name))


def describe(tag):
    """'[h ALE]' -> 'hacked by ALE'; '[o]' -> 'overdump ...'; anything else as written."""
    t = tag.strip()
    for code, meaning in MEANINGS:
        if t == code or t.startswith(code + " ") or (code in "abfhmopt" and re.fullmatch(code + r"\d*", t)):
            rest = t[len(code):].strip()
            if rest.isdigit() or not rest:
                return meaning
            if code == "tr":
                return f"{meaning} ({rest})"
            return f"{meaning} by {rest}" if code in ("cr", "h", "t", "p") else f"{meaning}: {rest}"
    return t


def version_key(path):
    """The title without its TOSEC tags or extension: versions share it."""
    name = _EXT.sub("", os.path.basename(path.rstrip("/")))
    name = _TAG.sub("", name)
    return re.sub(r"\s+", " ", name).strip().lower()


def name_of(item):
    """The identified TOSEC name if there is one, else the file's own path. A coverdisk known only
    by its magazine and issue goes by that, so "Created Disk 1.adf" from two issues isn't taken
    for two versions of one disk."""
    cover = getattr(item, "cover", None)
    if not getattr(item, "tosec_name", "") and cover is not None and cover.magazine:
        return cover.tosec_name or f"{cover.title()} {os.path.basename(item.path)}"
    return getattr(item, "tosec_name", "") or item.path


def order(item):
    """Best version first: not empty, not a bad dump, no problems, verified, fewest tags."""
    t = tags(name_of(item))
    return (item.status == "empty", any(x.startswith("b") for x in t), STATUS_RANK.get(item.status, 1),
            "!" not in t, len([x for x in t if x != "!"]), item.number)


def choices(cat):
    return cat.get_meta(CHOICES, {}) or {}


def choose(cat, key, path):
    c = choices(cat)
    c[key] = path
    cat.set_meta(CHOICES, c)


def mark(items, cat):
    """Fill in .version_key, .versions, .version_of and .other_versions.
    Spare copies (exact duplicates) are left out: they already show as one."""
    groups = {}
    for it in items:
        if it.spare_of:
            continue
        it.version_key = version_key(name_of(it))
        if it.version_key:
            groups.setdefault(it.version_key, []).append(it)
    chosen = choices(cat)
    for key, group in groups.items():
        if len(group) < 2:
            continue
        group.sort(key=order)
        want = chosen.get(key)
        shown = next((it for it in group if it.path == want), group[0])
        for it in group:
            it.versions = len(group)
            it.version_of = 0 if it is shown else shown.id
            it.other_versions = tuple(o.id for o in group if o is not shown) if it is shown else ()
    mark_good_copies(items, groups)
    return groups


def mark_good_copies(items, groups):
    """A damaged disk (Problem) with a version that reads fully gets .good_copy: that version's id
    (the best one, preferring the version shown). A version TOSEC tags as a bad dump [b] doesn't
    count, even if it reads: its contents are known to be damaged. Spare copies of the damaged
    disk get it too: they are the same bytes."""
    by_id = {}
    for group in groups.values():
        healthy = [it for it in group if it.status in ("ok", "warning")
                   and not any(t.startswith("b") for t in tags(name_of(it)))]
        healthy.sort(key=lambda it: (bool(it.version_of),) + order(it))
        for it in group:
            if it.status != "error":
                continue
            # a version with no files to read can't stand in for a disk that has files
            usable = [h for h in healthy if _has_files(h) or not _has_files(it)]
            if usable:
                it.good_copy = usable[0].id
                by_id[it.id] = it.good_copy
    for it in items:
        if it.spare_of in by_id:
            it.good_copy = by_id[it.spare_of]


def _has_files(item):
    """False for a disk TurboCAT found no files on ("—" or 0)."""
    n = str(getattr(item, "files", "1")).replace(",", "")
    return n.isdigit() and int(n) > 0
