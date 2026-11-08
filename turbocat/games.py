"""Which catalogued items are games, and why.

Each rule gives a reason that is shown to the user. Strong signs (a WHDLoad slave, a name or
folder that says "game") always count; weaker ones (a games publisher in a TOSEC name, a
title in the libretro game list, a disk that boots its own loader) are ignored for items that
are clearly something else (utilities, music modules, magazine coverdisks, scene demos).
A disk that belongs to a set (Disk 1 of 3 ...) is a game if any disk of the set is.
"""
import json
import os
import re

from .pictures import CACHE, clean_title, normal, LR_ORDER

GAME_WORD = re.compile(r"\bgames?\b", re.I)
PLAYABLE = re.compile(r"demo-(playable|rolling)|(?<![a-z])playable(?![a-z])", re.I)
TRAINER = re.compile(r"\[t[ +\]\d]", re.I)
NOT_GAME = re.compile(r"\b(utils?|utilities|tools|helper|copiers?|archivers?|virus|killers?|"
                      r"printer|print|icons|modules?|mods?|music|samples?|fonts?|clipart|"
                      r"coverdisks?|workbench|kickstart|catalogue|office|video|menu creators?|"
                      r"boot makers?|fix-disk|magic|vision)\b", re.I)
DEMO_FOLDER = re.compile(r"(^|/)[^/]*\bdemos?\b[^/]*(/|$)", re.I)

# Publishers whose Amiga output was (almost) all games, as they appear in TOSEC names.
PUBLISHERS = {
    "psygnosis", "team 17", "team17", "ocean", "virgin", "electronic arts", "core", "core design",
    "millennium", "rainbow arts", "dynamix", "renegade", "mindscape", "gremlin", "gremlin graphics",
    "microprose", "us gold", "u.s. gold", "codemasters", "thalion", "bitmap brothers",
    "the bitmap brothers", "domark", "infogrames", "ubi soft", "ubisoft", "cinemaware", "accolade",
    "sierra", "sierra on-line", "lucasfilm games", "lucasarts", "delphine", "delphine software",
    "factor 5", "hewson", "system 3", "image works", "palace", "activision", "interplay",
    "sensible software", "krisalis", "audiogenic", "grandslam", "elite", "digital integration",
    "empire", "rage", "vulcan", "daze marketing", "black legend", "kingsoft", "magic bytes",
    "linel", "ere informatique", "titus", "loriciel", "coktel vision", "blue byte", "ascon",
    "starbyte", "thalamus", "firebird", "rainbird", "mirrorsoft", "microillusions", "epyx",
    "silmarils", "cryo", "virgin games", "acclaim", "spectrum holobyte", "ssi",
    "strategic simulations", "new world computing", "origin", "infocom", "magnetic scrolls",
    "level 9", "llamasoft", "mastertronic", "zeppelin", "zeppelin games", "kixx", "hit squad",
    "the hit squad", "team17 software", "flair", "flair software", "alternative", "atlantis",
    "players", "code masters", "storm", "triffix", "21st century", "21st century entertainment",
    "vision software", "neo", "max design", "impressions", "kompart", "apex", "reflections",
    "dma design", "bullfrog", "probe", "probe software", "sales curve", "the sales curve",
    "storm software", "arc", "argonaut", "attention to detail", "epic marketing", "guildhall",
    "pd soft", "17 bit software", "seventeen bit software",
}

CUSTOM_BOOT = "custom boot code"


def _tosec_fields(name):
    """The (...) fields of a TOSEC file name, e.g. ['1993', 'Psygnosis', 'Disk 1 of 2']."""
    return re.findall(r"\(([^()]*)\)", os.path.basename(name))


def _publisher(name):
    for f in _tosec_fields(name):
        for part in re.split(r"\s+-\s+|,\s*", f):
            p = part.strip().lower()
            if p in PUBLISHERS:
                return part.strip()
    return None


def _libretro_titles():
    """Game titles from the libretro-thumbnails list, if it was downloaded before (no network)."""
    try:
        with open(os.path.join(CACHE, "libretro-amiga.json")) as f:
            tree = json.load(f)
    except (OSError, ValueError):
        return set()
    titles = set()
    for e in tree.get("tree", []):
        p = e.get("path", "")
        if "/" in p and p.split("/", 1)[0] in LR_ORDER and p.endswith(".png"):
            titles.add(normal(re.split(r"\s*\(", p.split("/", 1)[1][:-4], maxsplit=1)[0]))
    return titles


def _set_key(source):
    """Disks of one set share a folder and a title: 'Dune (1992)(Virgin)(Disk 2 of 3).adf'."""
    return os.path.dirname(source), normal(clean_title(source))


def classify(cat):
    """Return {top-level media id: reason} for every item judged to be a game."""
    lr = _libretro_titles()
    tops = cat.db.execute("SELECT * FROM media WHERE parent_id IS NULL").fetchall()
    inner = {}
    for r in cat.db.execute("SELECT id, parent_id, kind, boot_kind, info, whd_name, inner_path "
                            "FROM media WHERE parent_id IS NOT NULL"):
        inner.setdefault(r["parent_id"], []).append(r)
    online = {r["key"] for r in cat.db.execute(
        "SELECT key FROM thumbs WHERE origin='online'")} if _has_table(cat, "thumbs") else set()

    found = {}
    for m in tops:
        src = m["source"]
        base = os.path.basename(src.rstrip("/"))
        kids = inner.get(m["id"], [])
        names = [base] + [os.path.basename(k["inner_path"] or "") for k in kids]
        if m["status"] == "empty":
            continue
        # Strong signs: always count.
        if m["whd_name"] or any(k["whd_name"] for k in kids):
            found[m["id"]] = "WHDLoad game"
            continue
        if any(PLAYABLE.search(n) for n in names):
            found[m["id"]] = "playable game demo (the file name says so)"
            continue
        word = next((n for n in names if GAME_WORD.search(n)), None)
        if word:
            found[m["id"]] = f"the name says it's a game: “{clean_title(word) or word}”"
            continue
        folder = os.path.dirname(src)
        if re.search(r"(^|/)[^/]*\bgames?\b[^/]*$", folder, re.I):
            found[m["id"]] = f"it's in a games folder ({os.path.basename(folder)})"
            continue
        # Weaker signs: not for things that are clearly something else.
        if NOT_GAME.search(base) or NOT_GAME.search(folder) or DEMO_FOLDER.search(folder):
            continue
        if TRAINER.search(base):
            found[m["id"]] = "it has a trainer (cheat menu) added, which only games get"
            continue
        pub = _publisher(src)
        if pub:
            found[m["id"]] = f"published by {pub}, a games publisher"
            continue
        title = normal(clean_title(src))
        key = m["sha1"] or ("path:" + src)
        if (title and title in lr) or key in online:
            found[m["id"]] = "the title is in the libretro game list"
            continue
        boot = m["boot_kind"] or next((k["boot_kind"] for k in kids if k["boot_kind"]), "")
        # PD compilations boot their own menu, so for them a custom loader says nothing.
        if boot.startswith(CUSTOM_BOOT) and "PD" not in _tosec_fields(src):
            found[m["id"]] = "it boots its own loader, as most commercial games do (a likely guess)"
            continue

    # Disks of a set go together: Disk 2 of Dune is a game because Disk 1 is.
    sets = {}
    for m in tops:
        sets.setdefault(_set_key(m["source"]), []).append(m)
    for members in sets.values():
        if len(members) < 2:
            continue
        lead = next((x for x in sorted(members, key=lambda x: x["number"] or 0) if x["id"] in found), None)
        if lead is None:
            continue
        for x in members:
            if x["id"] not in found and x["status"] != "empty":
                found[x["id"]] = f"another disk of the same set (#{lead['number']:04d}) is a game"
    return found


def _has_table(cat, name):
    return cat.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                          (name,)).fetchone() is not None
