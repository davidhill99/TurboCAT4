"""TurboCAT 4 desktop window.

Follows the "TurboCAT 4 Window" design: wordmark header, a search box, the
numbered disk list with type icons and status pills, a details panel for the
selected item, and a status line.
Run with:  python -m turbocat window   (add --db FILE for another catalogue)
"""

import dataclasses
import json
import os
import re
import shutil
import sys
import threading
import time
from dataclasses import dataclass, field

from PySide6.QtCore import (QAbstractTableModel, QIODevice, QItemSelectionModel, QModelIndex,
                            QEvent, QObject, QPoint, QRect, QRectF, QSize, QSortFilterProxyModel, Qt, QThread, QTimer,
                            QStorageInfo, QUrl, Signal)
from PySide6.QtGui import (QColor, QCursor, QDesktopServices, QFont, QFontMetrics, QGuiApplication, QIcon,
                           QAction, QKeySequence, QPainter, QPen, QPixmap, QShortcut)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QFileDialog,
                               QFrame, QGridLayout, QLayout, QProgressDialog, QListWidget, QListWidgetItem, QMenu, QMessageBox,
                               QRadioButton,
                               QButtonGroup, QHBoxLayout, QProgressBar,
                               QHeaderView, QLabel, QLineEdit, QMainWindow, QPushButton,
                               QScrollArea, QSizePolicy, QSplitter, QStackedWidget, QStyle, QStyledItemDelegate,
                               QTableView, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QWidgetItem)

from . import APP_NAME, VERSION
from . import explain, readers, repair
from .bootblock import best_title
from .catalogue import Catalogue, matches, search_words
from . import coverdisks, datlists, folders, magcovers, dups as dupes, favourites as favs, identify, setup as setupcheck, sets as disksets, utilities, versions as vers, emulator, games, gotek, music, pictures, turboview
from .scanner import BIG_ARCHIVE, recheck, rescan_all, scan

ICON_DIR = os.path.join(os.path.dirname(__file__), "icons")

# Colour tokens from the TurboCAT design system (light, dark).
TOKENS = {
    "surface": ("#ffffff", "#16191f"),
    "chrome": ("#f3f4f7", "#1f232b"),
    "line": ("#d5dae1", "#343a45"),
    "row-line": ("#e8ebf0", "#2a2f38"),
    "control-edge": ("#7e8796", "#6b7482"),
    "ink": ("#16191f", "#e8ebf0"),
    "ink-soft": ("#3d4552", "#c2c8d2"),
    "ink-muted": ("#5a6270", "#a3abb8"),
    "accent": ("#1d4f91", "#8db0e6"),
    "on-accent": ("#ffffff", "#0b1220"),
    "accent-tint": ("#e3ecf8", "#1e2c42"),
    "accent-ink": ("#123766", "#c9daf4"),
    "ok": ("#1e6b3a", "#8ad6a4"),
    "ok-tint": ("#e2f3e7", "#17301f"),
    "warn": ("#7a4a00", "#f2c46b"),
    "warn-tint": ("#fff1d6", "#3a2c12"),
    "problem": ("#9a2318", "#f49b92"),
    "problem-tint": ("#fde4e1", "#3d1b18"),
    "neutral-tint": ("#eef1f5", "#262b34"),
}
C = {}  # filled by _pick_theme()

UI_FONTS = ["IBM Plex Sans", "Noto Sans", "Segoe UI", "sans-serif"]
DATA_FONTS = ["IBM Plex Mono", "DejaVu Sans Mono", "monospace"]

IMAGE_KINDS = ("adf", "dms", "adz", "hdf", "lha", "lzx", "zip")
ARCHIVE_KINDS = ("lha", "lzx", "zip")
DISK_KINDS = ("adf", "dms", "adz", "hdf")
KIND_ICON = {"adf": "disk", "dms": "disk", "adz": "disk", "hdf": "harddrive",
             "lha": "archive", "lzx": "archive", "zip": "archive", "folder": "folder",
             "module": "music", "kickstart": "chip"}
SET_TONE = {"ok": ("ok", "ok-tint", "ok"), "warn": ("warn", "warn-tint", "warning"),
            "problem": ("problem", "problem-tint", "problem")}
STATUS = {"ok": ("OK", "ok", "ok-tint", None),
          "warning": ("Warning", "warn", "warn-tint", "warning"),
          "error": ("Problem", "problem", "problem-tint", "problem"),
          "empty": ("Empty", "ink-soft", "neutral-tint", None)}

# Filter chips above the list: key, label, icon, test for an item.
FILTERS = [
    ("all", "All items", None, lambda it: True),
    ("favs", "Favourites", "star", lambda it: it.favourite),
    ("games", "Games", "game", lambda it: bool(it.game)),
    ("music", "Music", "music", lambda it: it.music > 0),
    ("utils", "Utilities", "tool", lambda it: bool(it.utility)),
    ("covers", "Coverdisks", "magazine", lambda it: it.cover is not None),
    ("roms", "Kickstart ROMs", "chip", lambda it: it.type == "Kickstart"),
    ("problems", "Problems", "problem", lambda it: it.status == "error" and not it.good_copy),
    ("warnings", "Warnings", "warning", lambda it: it.status == "warning"),
    ("fixable", "Can be fixed", "tool", lambda it: can_fix(it)),
    ("repaired", "Repaired copies", "tool", lambda it: it.repaired),
    ("dups", "Duplicates", "duplicate", lambda it: it.copies > 1),
    ("sets", "Sets to complete", "disk", lambda it: it.set_problem),
    ("whd", "WHDLoad games", "game", lambda it: it.type == "WHDLoad"),
    ("nondos", "Non-DOS disks", "disk", lambda it: it.non_dos),
    ("hd", "Hard drives", "harddrive", lambda it: it.hard_drive),
    ("empty", "Empty", None, lambda it: it.status == "empty" and not it.good_copy),
]
FILTER_TEST = {k: t for k, _, _, t in FILTERS}


def _pick_theme():
    dark = False
    try:
        dark = QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:
        pass
    for k, (light, dk) in TOKENS.items():
        C[k] = QColor(dk if dark else light)


def ui_font(px, weight=QFont.Weight.Normal, italic=False):
    f = QFont()
    f.setFamilies(UI_FONTS)
    f.setPixelSize(px)
    f.setWeight(weight)
    f.setItalic(italic)
    return f


def data_font(px):
    f = QFont()
    f.setFamilies(DATA_FONTS)
    f.setPixelSize(px)
    f.setStyleHint(QFont.StyleHint.Monospace)
    return f


_pix_cache = {}


def icon(name, size):
    """Render one of the design's pixel-art SVG icons, kept crisp."""
    key = (name, size)
    if key not in _pix_cache:
        dpr = QGuiApplication.primaryScreen().devicePixelRatio() if QGuiApplication.primaryScreen() else 1
        pm = QPixmap(int(size * dpr), int(size * dpr))
        pm.fill(Qt.GlobalColor.transparent)
        r = QSvgRenderer(os.path.join(ICON_DIR, name + ".svg"))
        p = QPainter(pm)
        r.render(p)
        p.end()
        pm.setDevicePixelRatio(dpr)
        _pix_cache[key] = pm
    return _pix_cache[key]


_thumb_cache = {}


def thumb(path, w, h, upscale=True):
    """A picture from the cache folder, fitted into w x h (pixel art kept crisp when enlarged)."""
    key = (path, w, h, upscale)
    if key not in _thumb_cache:
        pm = QPixmap(path)
        if pm.isNull():
            _thumb_cache[key] = None
        else:
            if not upscale and pm.width() <= w and pm.height() <= h:
                out = pm
            else:
                big = pm.width() < w and pm.height() < h
                out = pm.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.FastTransformation if big
                                else Qt.TransformationMode.SmoothTransformation)
            _thumb_cache[key] = out
            if len(_thumb_cache) > 3000:
                _thumb_cache.clear()
    return _thumb_cache[key]


# ---------------------------------------------------------------- data

@dataclass
class Item:
    id: int
    number: int
    file: str
    path: str
    type: str
    icon: str
    title: str
    from_text: bool
    files: str
    status: str
    sha1: str = ""
    dup: bool = False           # the same disk is catalogued more than once
    found: str = ""
    dup_key: str = ""           # content fingerprint: the disk itself, whatever it is wrapped in
    copies: int = 1             # how many copies of this disk there are
    spare_of: int = 0           # a spare copy: the id of the copy TurboCAT keeps (and shows)
    spares: tuple = ()          # the copy kept: ids of its hidden spares
    version_key: str = ""       # the title without TOSEC tags: versions of a disk share it
    versions: int = 1           # how many versions of this disk there are
    version_of: int = 0         # another version: the id of the version shown instead
    other_versions: tuple = ()  # the version shown: ids of the others
    shares: frozenset = frozenset()   # fingerprints of archives/disks it shares with other items
    members: tuple = ()         # a disk set's row: ids of its disks, in disk order
    set_badge: str = ""         # a disk set's row: "Complete · 3 of 3", "Disk 2 missing"...
    set_tone: str = ""          # ok, warn or problem
    set_problem: bool = False   # a set with missing or damaged disks
    dset: object = None         # the sets.DiskSet behind a set's row
    non_dos: bool = False
    hard_drive: bool = False
    thumb_icon: str = ""        # the disk's own Workbench icon (PNG path)
    pic: str = ""               # best picture: on the disk, or found online
    pic_from: str = ""
    pic_origin: str = ""
    game: str = ""              # why it counts as a game ("" if it doesn't)
    utility: str = ""           # why it counts as a utility or application ("" if it doesn't)
    verified: tuple = ()        # ("match" or "differs", collection list title) if a list knows it
    favourite: bool = False     # starred by the user
    tosec_name: str = ""        # the disk's proper name, found by its checksum ("" if unknown)
    identified_by: str = ""     # the list that knew it
    name_guess: str = ""        # a guess from the folder, for a file called "Disk1.adf"
    key: str = ""               # pictures / music key
    music: int = 0              # music modules found inside
    cover: object = None        # a coverdisks.Coverdisk: the magazine, issue and disk it came with
    fixable: tuple = ()         # readers.local_fixes: helper programs that would let it be read
    good_copy: int = 0          # damaged, but this version (id) of the same disk reads fully
    damage: str = ""            # a Problem in plain words: "1 of 220 files damaged — ..."
    repaired: bool = False      # a repaired copy TurboCAT made (not an original dump)
    rebuild: tuple = ()         # (damaged files that can be put back, damaged files): repair.plan
    repaired_copy: int = 0      # the id of a repaired copy TurboCAT made of this damaged disk
    search_blob: str = field(default="", repr=False)


def load_items(cat):
    rows = cat.db.execute("SELECT * FROM media WHERE parent_id IS NULL ORDER BY number").fetchall()
    shared_sha = {r["sha1"] for r in cat.duplicate_images()}
    emulator.EXTRA_ROM_DIRS[:] = emulator.catalogued_rom_dirs(cat)   # ROMs found by scanning
    thumbs = pictures.thumbs_by_key(cat)
    game_why = games.classify(cat)
    lists = datlists.lists_in({os.path.dirname(m["source"]) for m in rows})
    tunes = {k: len(v) for k, v in pictures.music_by_key(cat).items()}
    top = cat.top_ids()
    inside = {}      # top-level id -> every archive / image found inside it
    for r in cat.db.execute("SELECT * FROM media WHERE parent_id IS NOT NULL ORDER BY id"):
        inside.setdefault(top.get(r["id"]), []).append(r)
    known = identify.identify({m["id"]: [m] + inside.get(m["id"], []) for m in rows}, lists)
    not_games = ("Applications", "Compilations - Applications", "Coverdisks", "Demos", "Diskmags",
                 "Docs", "Drivers", "Educational", "Firmware", "Kickstart", "Operating Systems",
                 "Packmags", "Book")
    for mid, (name, _src, which) in known.items():   # an identified disk by a games publisher
        if mid not in game_why and not str(which).startswith(not_games):
            pub = games._publisher(name)
            if pub:
                game_why[mid] = f"identified as a {pub} disk by its checksum ({pub} published games)"
    util_why = utilities.classify(cat, rows, game_why, lists, cat.scan_roots())
    for mid, (_name, _src, which) in known.items():  # TOSEC files it with the applications
        if mid not in util_why and mid not in game_why and str(which).startswith(
                ("Applications", "Compilations - Applications")):
            util_why[mid] = f"in TOSEC's {which} list"
    starred = favs.load(cat)
    mag_covers = magcovers.covers(cat)
    made = repair.repaired_sha1s()
    plans = repair.plan_all(cat)
    rank = {"error": 3, "warning": 2}
    items = []
    for m in rows:
        kind = m["kind"] or ""
        kids = inside.get(m["id"], [])
        # An archive holding a single disk image (the usual TOSEC .zip, or an .lha of one ADF)
        # is shown as that disk: its name, type, status and file count.
        disk = m
        if kind in ARCHIVE_KINDS and not m["whd_name"]:
            direct = [k for k in kids if k["parent_id"] == m["id"]]
            if len(direct) == 1 and direct[0]["kind"] in DISK_KINDS:
                disk = direct[0]
        info = _j(disk["info"], {})
        texts = _j(disk["text"], [])
        dkind = disk["kind"] or ""
        non_dos = "non-DOS" in str(info.get("format", ""))
        if m["whd_name"]:
            typ, ico = "WHDLoad", "game"
        elif disk is not m:
            typ, ico = f"{dkind.upper()} in {kind.upper()}", KIND_ICON.get(dkind, "disk")
        else:
            typ, ico = ({"folder": "Folder", "module": "Module", "kickstart": "Kickstart"}.get(kind, kind.upper()),
                        KIND_ICON.get(kind, "disk"))

        status = disk["status"] or "ok"
        worst = max([m] + kids, key=lambda r: rank.get(r["status"], 0))
        if rank.get(worst["status"], 0) > rank.get(status, 0):
            status = worst["status"]

        title, from_text = m["whd_name"] or disk["volume"] or "", False
        if status == "empty":
            title = "Empty file" if not disk["size"] else "Blank disk"
        if not title and disk is m and kind in ARCHIVE_KINDS:
            first = cat.db.execute("SELECT path FROM files WHERE media_id=? ORDER BY id LIMIT 1",
                                   (m["id"],)).fetchone()
            title = first["path"].split("/")[0] if first else "Empty archive"
        if not title:
            title = best_title(texts)[:60]
            from_text = bool(title)
            if not title:
                title = "Non-DOS data disk" if non_dos or not disk["fs"] else "No volume name"
        if m["id"] in known and (from_text or not (disk["volume"] or m["whd_name"])):
            # Text found on the disk (or nothing) is a poor title next to the disk's real name.
            title, from_text = pictures.clean_title(known[m["id"]][0]), False
        cover = coverdisks.recognise(m["source"], known.get(m["id"])) if kind != "kickstart" else None
        if cover is not None and cover.magazine:
            title, from_text = cover.title(), False       # "Amiga Shopper #47 · Mar 1995 · Disk 2 of 3"

        if disk is m:
            n = (m["file_count"] or 0) + sum(k["file_count"] or 0 for k in kids)
        else:
            n = (disk["file_count"] or 0) + sum(k["file_count"] or 0 for k in kids if k is not disk)
        files = f"{n:,}" if n or (disk["volume"] and not non_dos) else "—"
        if status == "empty" or kind == "kickstart":
            files = "—"
        # Things inside it that also turn up elsewhere (not counting the item's own disk,
        # which is what makes a true duplicate).
        own_key = disk["sha1"] or m["sha1"] or ""
        shares = frozenset({r["sha1"] for r in kids if r["kind"] in IMAGE_KINDS} & shared_sha
                           - {own_key})
        th = thumbs.get(pictures.item_key(m))
        pic = pictures.picture_path(th["pic"]) or "" if th else ""
        pic_from = (th["pic_from"] or "") if th else ""
        pic_origin = (th["origin"] or "") if th else ""
        if cover is not None and cover.magazine and cover.issue:
            # a coverdisk shows the cover of the magazine it came with
            found = mag_covers.get((cover.magazine, magcovers.issue_key(cover.issue)))
            if found and os.path.exists(found[0]):
                pic, pic_from, pic_origin = found[0], f"{found[1]}|{found[2]}", "cover"
        items.append(Item(
            id=m["id"], number=m["number"] or 0, file=os.path.basename(m["source"].rstrip("/")),
            path=m["source"], type=typ, icon=ico, title=title, from_text=from_text, files=files,
            status=status, sha1=own_key, dup_key=own_key if dkind != "folder" else "", shares=shares,
            non_dos=non_dos and status != "empty",
            hard_drive=dkind in ("hdf", "folder") or any(k["kind"] == "hdf" for k in kids),
            thumb_icon=pictures.picture_path(th["icon"]) or "" if th else "",
            pic=pic, pic_from=pic_from, pic_origin=pic_origin,
            game=game_why.get(m["id"], ""), utility=util_why.get(m["id"], ""),
            verified=_verified(m, kids, lists),
            favourite=favs.item_key(pictures.item_key(m)) in starred,
            tosec_name=identify.stem(known[m["id"]][0]) if m["id"] in known else "",
            identified_by=known[m["id"]][1] if m["id"] in known else "",
            name_guess="" if m["id"] in known else identify.guess(m["source"]),
            key=pictures.item_key(m), music=tunes.get(pictures.item_key(m), 0), cover=cover,
            fixable=tuple(readers.local_fixes(
                [x for r in [m] + kids for f in ("problems", "warnings") for x in _j(r[f], [])])),
            damage=explain.summary([x for r in [m] + kids for x in _j(r["problems"], [])],
                                   int(files.replace(",", "")) if files.replace(",", "").isdigit() else 0)
            if status == "error" else "",
            repaired=bool(own_key) and own_key in made,
            rebuild=(len(plans[m["id"]].usable()), len(plans[m["id"]].lost)) if m["id"] in plans else ()))
    dupes.mark(items, cat)
    vers.mark(items, cat)
    _link_repairs(items)
    _link_empty_covers(items)
    return items


def _link_empty_covers(items):
    """An empty coverdisk file (0 bytes) whose magazine, issue and disk are in the collection as a
    working image: point it there, so Empty lists only what is really missing."""
    def key(it):
        c = it.cover
        return (c.magazine, c.issue, c.disk) if c is not None and c.magazine and c.issue else None
    good = {}
    for it in sorted((x for x in items if x.status in ("ok", "warning") and key(x)), key=vers.order):
        if not any(t.startswith("b") for t in vers.tags(vers.name_of(it))):
            good.setdefault(key(it), it.id)
    for it in items:
        if it.status == "empty" and not it.good_copy and key(it) in good:
            it.good_copy = good[key(it)]


def _link_repairs(items):
    """Point each damaged disk at the repaired copy TurboCAT made of it (from the repair log, so
    it works whatever the names say). A complete repair counts as a good copy."""
    copies = repair.copies_of()
    if not copies:
        return
    by_sha = {it.sha1: it for it in items if it.repaired}
    for it in items:
        if it.status != "error" or it.repaired:
            continue
        made = [by_sha[sha] for sha in copies.get(it.file, []) if sha in by_sha]
        if not made:
            continue
        whole = [c for c in made if "[b]" not in c.file]
        it.repaired_copy = (whole or made)[-1].id
        if whole and not it.good_copy:
            it.good_copy = whole[-1].id


def _set_rebuild(members):
    """A set's rebuild counts: over its damaged disks that have no good copy."""
    todo = [m.rebuild for m in members if m.rebuild and can_fix(m)]
    return (sum(a for a, _ in todo), sum(b for _, b in todo)) if todo else ()


def fix_word(it):
    """The second pill on a damaged row: how it can be fixed, if it can. ('', '') if not."""
    if it.repaired:
        return "Repaired copy", "tool"
    if it.status != "error" and not it.members:
        return "", ""
    if it.good_copy:
        return "", ""
    if it.repaired_copy:
        full = it.rebuild and it.rebuild[0] == it.rebuild[1]
        return ("Can be fully rebuilt now" if full else "Partly repaired"), "tool"
    if it.rebuild and it.rebuild[0]:
        return ("Can be rebuilt" if it.rebuild[0] == it.rebuild[1] else "Partly rebuildable"), "tool"
    if any(here for _, _, here in it.fixable):
        return "Can be fixed now", "tool"
    if it.fixable:
        return "Fix: install " + ", ".join(pkg for _, pkg, _ in it.fixable), "tool"
    return "", ""


def can_fix(it):
    """For the Can be fixed chip: a helper program, or files on other disks, would fix it."""
    if it.repaired or it.good_copy:
        return False
    if it.repaired_copy:            # partly repaired: again only once every file can be put back
        return bool(it.rebuild and it.rebuild[0] == it.rebuild[1])
    return bool(it.fixable) or bool(it.rebuild and it.rebuild[0])


def _verified(m, kids, lists):
    """("match"/"differs", list title) if a collection list beside the item knows it."""
    if not lists:
        return ()
    shas = {(r["sha1"] or "").lower() for r in [m] + kids if r["sha1"]}
    verdict, lst = datlists.check(os.path.basename(m["source"]), os.path.dirname(m["source"]), shas, lists)
    return (verdict, lst.title) if verdict else ()


def make_set_items(items):
    """One row per multi-disk set, built from its disks (spare copies left out).
    Returns (set rows, {disk id: its set's row}, {disk id: disk number})."""
    rows, member_of, number_of = [], {}, {}
    for ds in disksets.group([it for it in items if not it.spare_of],
                             lambda it: (bool(it.version_of), vers.order(it))):
        members = [it for _, it, _ in ds.disks]
        first = members[0]
        with_pic = next((m for m in members if m.pic), first)
        with_icon = next((m for m in members if m.thumb_icon), first)
        worst = max(members, key=lambda m: {"error": 3, "warning": 2}.get(m.status, 0))
        files = sum(int(m.files.replace(",", "")) for m in members if m.files.replace(",", "").isdigit())
        badge, tone = ds.badge()
        have = len(members)
        # A coverdisk set (an issue's disks) is a coverdisk too, titled by its issue, not disk 1
        cover = next((m.cover for m in members if m.cover is not None and m.cover.magazine), None)
        if cover is not None:
            cover = dataclasses.replace(cover, disk="", of="", label="", tosec_name="")
        row = Item(
            id=first.id, number=first.number, file=ds.key, path=first.path,
            type=f"Set of {ds.expected} disks" + (f" · {have} here" if have != ds.expected else ""),
            icon=first.icon, title=cover.title() if cover is not None else first.title,
            from_text=first.from_text,
            files=f"{files:,}" if files else "—", status=worst.status, sha1="",
            non_dos=all(m.non_dos for m in members), hard_drive=False,
            thumb_icon=with_icon.thumb_icon, pic=with_pic.pic, pic_from=with_pic.pic_from,
            pic_origin=with_pic.pic_origin, game=next((m.game for m in members if m.game), ""),
            utility=next((m.utility for m in members if m.utility), ""),
            favourite=any(m.favourite for m in members),
            key=first.key, music=sum(m.music for m in members),
            members=tuple(m.id for m in members), set_badge=badge, set_tone=tone,
            set_problem=not ds.complete, dset=ds, cover=cover,
            fixable=tuple(sorted({f for m in members for f in m.fixable})),
            rebuild=_set_rebuild(members))
        rows.append(row)
        for n, m, _ in ds.disks:
            member_of[m.id] = row
            number_of[m.id] = n
    return rows, member_of, number_of


# ---------------------------------------------------------------- table

COLUMNS = ["NO.", "IMAGE", "VOLUME OR TITLE", "FILES", "STATUS"]


class ItemModel(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self.items = []

    def set_items(self, items):
        self.beginResetModel()
        self.items = items
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def columnCount(self, parent=QModelIndex()):
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal:
            if role == Qt.ItemDataRole.DisplayRole:
                return COLUMNS[section]
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return int((Qt.AlignmentFlag.AlignRight if section == 3 else Qt.AlignmentFlag.AlignLeft)
                           | Qt.AlignmentFlag.AlignVCenter)
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        it = self.items[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return it
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            col = index.column()
            if col == 0:
                return f"#{it.number:04d}"
            if col == 1:
                if role == Qt.ItemDataRole.ToolTipRole:
                    return it.path + (f"\nIdentified as {it.tosec_name}" if it.tosec_name else "")
                return _shown_name(it)
            if col == 2:
                return it.title + (f"\nFound: {it.found}" if it.found else "")
            if col == 3:
                return it.files
            if it.members:
                return it.set_badge
            if role == Qt.ItemDataRole.ToolTipRole and it.status == "error" and it.damage:
                fix = fix_word(it)[0]
                return it.damage + ("\nYou have a good copy: another version reads fully."
                                    if it.good_copy else
                                    f"\n{fix}: {it.rebuild[0]} of {it.rebuild[1]} damaged files are on "
                                    "your other disks." if fix in ("Can be rebuilt", "Partly rebuildable")
                                    else f"\n{fix}." if fix else "")
            v = _version_word(it)
            fix = fix_word(it)[0]
            return (STATUS.get(it.status, STATUS["ok"])[0] + (f" · {fix}" if fix else "")
                    + _dup_word(it, long=True) + (f" · {v}" if v else ""))
        return None


def _dup_word(it, long=False):
    """The duplicate pill: "Spare copy" on a hidden spare, "2 copies" on the copy kept."""
    if it.copies < 2:
        return ""
    word = "Spare copy" if it.spare_of else f"{it.copies} copies"
    return f" · {word}" if long else word


def _renamed(it):
    """True when the disk is identified and its file is called something else."""
    return bool(it.tosec_name) and not it.members and \
        identify.stem(os.path.splitext(it.file)[0]) != it.tosec_name


def _shown_name(it):
    """The name in the list: the identified TOSEC name, else the file name."""
    return it.tosec_name if _renamed(it) else it.file


def _type_line(it):
    """The small line under the name: the type, and the real file name when it differs."""
    return f"{it.type} · file {it.file}" if _renamed(it) else it.type


def star_rect(r):
    """Where a row's star sits, at the right of the number column."""
    return QRectF(r.right() - 26, r.top() + (r.height() - 16) / 2, 16, 16)


def _version_word(it):
    """The versions pill: "4 versions" on the version shown, "Other version" on the rest."""
    if it.versions < 2:
        return ""
    return "Other version" if it.version_of else f"{it.versions} versions"


TUNE_COLUMNS = ["TUNE", "ARTIST", "FORMAT", "LENGTH", "SIZE", "NO.", "WHERE"]
SORT_ROLE = Qt.ItemDataRole.UserRole + 1


def _short_size(n):
    return f"{n / 1048576:.1f} MB" if n >= 1048576 else f"{max(1, round(n / 1024)):,} KB"


def _n(count, word):
    return f"{count:,} {word}{'' if count == 1 else 's'}"


class TuneModel(QAbstractTableModel):
    """Every music module found, one per row."""

    def __init__(self):
        super().__init__()
        self.rows = []          # (music row, item)
        self.starred = set()    # favourites.tune_key of each favourite tune

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(TUNE_COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal:
            if role == Qt.ItemDataRole.DisplayRole:
                return TUNE_COLUMNS[section]
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return int((Qt.AlignmentFlag.AlignRight if section in (3, 4) else Qt.AlignmentFlag.AlignLeft)
                           | Qt.AlignmentFlag.AlignVCenter)
        return None

    @staticmethod
    def title(r):
        """The song name, or the file name when the tune has none."""
        return (r["title"] or "").strip() or TuneModel.file_name(r)

    GENERIC = re.compile(r"^(song|songs|tune|tunes|music|data|sng|mod|module|snd|sound|theme|intro|end|"
                         r"backsong|game|title|main)[\s._\-]*\d*$", re.I)

    @staticmethod
    def file_name(r):
        """The file name without mod./med. prefixes; with its folder in front when the name alone
        says little (Columns › song.0 rather than song.0)."""
        parts = r["file"].split("/")
        name = re.sub(r"^(mod|med|xm|s3m)\.", "", parts[-1], flags=re.I)
        stem = re.sub(r"\.(mod|med|sng|song|xm|s3m|it)$", "", name, flags=re.I)
        if (TuneModel.GENERIC.match(stem) or len(stem) <= 3) and len(parts) > 1:
            folder = next((p for p in reversed(parts[:-1]) if not TuneModel.GENERIC.match(p)), parts[-2])
            return f"{folder} › {name}"
        return name

    @staticmethod
    def named(r):
        """True when the tune has a song name of its own (not just its file name)."""
        t = (r["title"] or "").strip()
        return bool(t) and not pictures._is_file_name(t, r["file"])

    @staticmethod
    def artist(r):
        try:
            return (r["artist"] or "").strip()
        except (IndexError, KeyError):
            return ""

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        r, it = self.rows[index.row()]
        col = index.column()
        dur = r["duration"]
        length = music.fmt_time(dur) if dur and dur > 0 else ("can't play" if dur is not None else "…")
        if role == Qt.ItemDataRole.DisplayRole:
            return [self.title(r), self.artist(r),
                    r["fmt"] + (" (in a program)" if r["length"] else ""),
                    length, _short_size(r["size"] or 0), f"#{it.number:04d}", r["shown"]][col]
        if role == SORT_ROLE:
            return [self.title(r).lower(), self.artist(r).lower(), r["fmt"], dur or 0, r["size"] or 0,
                    it.number, r["shown"].lower()][col]
        if role == Qt.ItemDataRole.ToolTipRole:
            name = "" if self.named(r) else "\n(no song name in the tune: this is its file name)"
            by = f"\nby {self.artist(r)}" if self.artist(r) else ""
            return f"{self.title(r)}{by}{name}\n{r['shown']}\nDouble-click to play"
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int((Qt.AlignmentFlag.AlignRight if col in (3, 4) else Qt.AlignmentFlag.AlignLeft)
                       | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ForegroundRole:
            if col == 0 and not self.named(r):
                return C["ink-soft"]
            if col in (2, 5, 6):
                return C["ink-muted"]
        if role == Qt.ItemDataRole.FontRole:
            if col == 0:
                return ui_font(14, QFont.Weight.Medium, italic=not self.named(r))
            return data_font(13) if col in (3, 4, 5) else ui_font(13)
        if role == Qt.ItemDataRole.DecorationRole and col == 0:
            return QIcon(icon("star" if favs.tune_key(r) in self.starred else "music", 16))
        return None

    def refresh(self):
        if self.rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, 0))


class RowDelegate(QStyledItemDelegate):
    """Paints rows the way the design draws them."""
    PAD = 12
    SLOT_W, SLOT_H = 56, 42      # the picture / icon at the start of each row

    def paint(self, p, opt, index):
        it = index.data(Qt.ItemDataRole.UserRole)
        r = opt.rect
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(r, C["accent-tint"] if selected else C["surface"])
        p.setPen(QPen(C["row-line"], 1))
        p.drawLine(r.left(), r.bottom(), r.right(), r.bottom())
        col = index.column()
        x = r.left() + self.PAD
        w = r.width() - 2 * self.PAD
        if col == 0:
            if selected:
                p.fillRect(r.left(), r.top(), 3, r.height(), C["accent"])
            p.setFont(data_font(13))
            p.setPen(C["ink-muted"])
            p.drawText(QRectF(x, r.top(), w, r.height()), Qt.AlignmentFlag.AlignVCenter, f"#{it.number:04d}")
            if it.favourite or selected:            # a click on the star stars / unstars the row
                sr = star_rect(r)
                p.drawPixmap(int(sr.x()), int(sr.y()), icon("star" if it.favourite else "star-off", 16))
        elif col == 1:
            self._paint_thumb(p, it, x, r)
            tx, tw = x + self.SLOT_W + 10, w - self.SLOT_W - 10
            f1, f2 = ui_font(14, QFont.Weight.Medium), data_font(12)
            h = QFontMetrics(f1).height() + QFontMetrics(f2).height()
            y = r.top() + (r.height() - h) / 2
            p.setFont(f1)
            p.setPen(C["ink"])
            p.drawText(QRectF(tx, y, tw, QFontMetrics(f1).height()), Qt.AlignmentFlag.AlignLeft,
                       QFontMetrics(f1).elidedText(_shown_name(it), Qt.TextElideMode.ElideMiddle, int(tw)))
            p.setFont(f2)
            p.setPen(C["ink-muted"])
            p.drawText(QRectF(tx, y + QFontMetrics(f1).height(), tw, QFontMetrics(f2).height()),
                       Qt.AlignmentFlag.AlignLeft,
                       QFontMetrics(f2).elidedText(_type_line(it), Qt.TextElideMode.ElideMiddle, int(tw)))
        elif col == 2:
            f1 = ui_font(14, italic=it.from_text)
            fs = ui_font(12)
            fm1, fms = QFontMetrics(f1), QFontMetrics(fs)
            h = fm1.height() + (fms.height() if it.found else 0)
            y = r.top() + (r.height() - h) / 2
            title = fm1.elidedText(it.title, Qt.TextElideMode.ElideRight, int(w))
            p.setFont(f1)
            p.setPen(C["ink-soft"] if it.from_text else C["ink"])
            p.drawText(QRectF(x, y, w, fm1.height()), Qt.AlignmentFlag.AlignLeft, title)
            if it.from_text:
                tail = x + fm1.horizontalAdvance(title)
                if tail + 40 < x + w:
                    p.setFont(fs)
                    p.setPen(C["ink-muted"])
                    p.drawText(QRectF(tail, y, x + w - tail, fm1.height()),
                               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                               fms.elidedText(" · from disk text", Qt.TextElideMode.ElideRight,
                                              int(x + w - tail)))
            if it.found:
                p.setFont(fs)
                p.setPen(C["accent-ink"] if selected else C["ink-muted"])
                p.drawText(QRectF(x, y + fm1.height(), w, fms.height()), Qt.AlignmentFlag.AlignLeft,
                           fms.elidedText("Found: " + it.found, Qt.TextElideMode.ElideRight, int(w)))
        elif col == 3:
            p.setFont(data_font(13))
            p.setPen(C["ink"])
            p.drawText(QRectF(x, r.top(), w, r.height()),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, it.files)
        elif it.members:
            fg, bg, ico = SET_TONE[it.set_tone]
            px = self._pill(p, x, r, it.set_badge, C[fg], C[bg], ico)
            fix, fico = fix_word(it)
            if fix:
                self._pill(p, px + 6, r, fix, C["accent"], C["accent-tint"], fico)
        else:
            word, fg, bg, ico = STATUS.get(it.status, STATUS["ok"])
            px = self._pill(p, x, r, word, C[fg], C[bg], ico)
            fix, fico = fix_word(it)
            if fix:
                px = self._pill(p, px + 6, r, fix, C["accent"], C["accent-tint"], fico)
            if it.copies > 1:
                px = self._pill(p, px + 6, r, _dup_word(it), C["ink-soft"], C["neutral-tint"], "duplicate")
            if it.versions > 1:
                self._pill(p, px + 6, r, _version_word(it), C["ink-soft"], C["neutral-tint"], None)
        p.restore()

    def _pill(self, p, x, r, text, fg, bg, ico):
        f = ui_font(12, QFont.Weight.DemiBold)
        fm = QFontMetrics(f)
        left = 4 if ico else 9
        w = left + (20 if ico else 0) + fm.horizontalAdvance(text) + 9
        h = 22
        y = r.top() + (r.height() - h) / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(x, y, w, h), h / 2, h / 2)
        tx = x + left
        if ico:
            p.drawPixmap(int(tx), int(y + 3), icon(ico, 16))
            tx += 20
        p.setFont(f)
        p.setPen(fg)
        p.drawText(QRectF(tx, y, w, h), Qt.AlignmentFlag.AlignVCenter, text)
        return x + w

    def _paint_thumb(self, p, it, x, r):
        """Games show their picture (title screen); other items their own Workbench icon.
        Failing those, the picture if there is one, else the generic symbol for the type."""
        sw, sh = self.SLOT_W, self.SLOT_H
        cy = r.top() + (r.height() - sh) // 2
        order = ("pic", "icon") if it.game else ("icon", "pic")
        for what in order:
            if what == "pic" and it.pic:
                pm = thumb(it.pic, sw, sh)
                if pm is not None:
                    px, py = x + (sw - pm.width()) // 2, cy + (sh - pm.height()) // 2
                    p.drawPixmap(px, py, pm)
                    p.setPen(QPen(C["line"], 1))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawRect(px, py, pm.width() - 1, pm.height() - 1)
                    return
            if what == "icon" and it.thumb_icon:
                pm = thumb(it.thumb_icon, sw - 8, sh - 4)
                if pm is not None:
                    p.drawPixmap(x + (sw - pm.width()) // 2, cy + (sh - pm.height()) // 2, pm)
                    return
        p.drawPixmap(x + (sw - 32) // 2, cy + (sh - 32) // 2, icon(it.icon, 32))

    def sizeHint(self, opt, index):
        """The width each column needs for this row (used when a divider is double-clicked)."""
        it = index.data(Qt.ItemDataRole.UserRole)
        col = index.column()
        w = 100
        if it is not None:
            if col == 0:
                w = QFontMetrics(data_font(13)).horizontalAdvance(f"#{it.number:04d}")
            elif col == 1:
                w = self.SLOT_W + 10 + max(QFontMetrics(ui_font(14, QFont.Weight.Medium)).horizontalAdvance(it.file),
                             QFontMetrics(data_font(12)).horizontalAdvance(it.type))
            elif col == 2:
                w = QFontMetrics(ui_font(14, italic=it.from_text)).horizontalAdvance(it.title)
                if it.from_text:
                    w += QFontMetrics(ui_font(12)).horizontalAdvance(" · from disk text")
            elif col == 3:
                w = QFontMetrics(data_font(13)).horizontalAdvance(it.files)
            else:
                w = (QFontMetrics(ui_font(12, QFont.Weight.DemiBold)).horizontalAdvance(it.set_badge) + 44
                     if it.members else 120 + (130 if it.copies > 1 else 0) + (120 if it.versions > 1 else 0))
        return QSize(w + 2 * self.PAD + 4, 56)


# ---------------------------------------------------------------- window

class SearchBox(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("searchBox")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(12)
        ico = QLabel()
        ico.setPixmap(icon("search", 32))
        ico.setFixedSize(32, 32)
        self.edit = QLineEdit()
        self.edit.setObjectName("searchEdit")
        self.edit.setPlaceholderText("Search files, disk names, WHDLoad games and text found on disks…")
        self.edit.setClearButtonEnabled(True)
        self.edit.setAccessibleName("Search the catalogue")
        self.edit.setFont(ui_font(16))
        hint = QLabel("Ctrl F")
        hint.setObjectName("keyHint")
        hint.setFont(data_font(12))
        lay.addWidget(ico)
        lay.addWidget(self.edit, 1)
        lay.addWidget(hint, 0, Qt.AlignmentFlag.AlignVCenter)
        self.setMinimumHeight(52)


# ---------------------------------------------------------------- details panel

KIND_NAME = {"adf": "ADF disk image", "dms": "DMS disk image", "adz": "ADZ disk image",
             "hdf": "HDF hard drive image", "lha": "LHA archive", "lzx": "LZX archive",
             "zip": "ZIP archive", "folder": "Amiga folder", "module": "Music module",
             "kickstart": "Kickstart ROM"}
DENSITY = {"DD": "double density", "HD": "high density"}
FS_ISSUE = "filesystem inconsistency, but every file reads: "


def _j(s, default):
    try:
        return json.loads(s) if s else default
    except ValueError:
        return default


def _size(n):
    if n is None:
        return "—"
    if n < 1024:
        return f"{n:,} bytes"
    if n < 1024 * 1024:
        return f"{n / 1024:,.0f} KB ({n:,} bytes)"
    return f"{n / 1048576:,.1f} MB"


def _breakable(s):
    """Let long paths and engine messages wrap at / : _ and , as well as at spaces."""
    for ch in "/:_,":
        s = s.replace(ch, ch + "​")
    return s


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _cap(s):
    return s[:1].upper() + s[1:] if s else s


class WrapLabel(QLabel):
    """A word-wrapped label that asks its layout for all the lines it needs.

    Qt box and grid layouts don't pass a wrapped label's height-for-width on, so long
    titles and facts were cut off after the first line or two."""

    def _fit(self):
        if self.width() > 0:
            old = self.minimumHeight()
            self.setMinimumHeight(0)       # Qt's measurement includes the current minimum
            h = self.heightForWidth(self.width())
            self.setMinimumHeight(h if h > 0 else old)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def setText(self, text):
        super().setText(text)
        self._fit()

    def setFont(self, font):
        super().setFont(font)
        self._fit()


def _wrap_label(text="", font=None, obj=None):
    lab = WrapLabel(text)
    lab.setWordWrap(True)
    lab.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    lab.setMinimumWidth(40)
    lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    if font is not None:
        lab.setFont(font)
    if obj:
        lab.setObjectName(obj)
    return lab


class Note(QFrame):
    """A tinted note: icon, a heading and up to three detail lines."""
    MAX_LINES = 3

    def __init__(self, tone, ico, heading, lines=(), on_link=None, tip="", button=None):
        super().__init__()
        self.setObjectName("note_" + tone)
        if tip:
            self.setToolTip(tip)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)
        if ico:
            pic = QLabel()
            pic.setPixmap(icon(ico, 32))
            pic.setFixedSize(32, 32)
            lay.addWidget(pic, 0, Qt.AlignmentFlag.AlignTop)
        body = QVBoxLayout()
        body.setSpacing(4)
        head = _wrap_label(heading, ui_font(13))
        head.setTextFormat(Qt.TextFormat.RichText)
        if on_link:
            head.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            head.linkActivated.connect(on_link)
        body.addWidget(head)
        lines = list(lines)
        for line in lines[:self.MAX_LINES]:
            body.addWidget(_wrap_label(_breakable(line), ui_font(12)))
        if len(lines) > self.MAX_LINES:
            more = _wrap_label(f"… and {len(lines) - self.MAX_LINES} more", ui_font(12, italic=True))
            more.setToolTip("\n".join(lines[self.MAX_LINES:self.MAX_LINES + 40]))
            body.addWidget(more)
        if button:
            b = QPushButton(button[0])
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(button[1])
            row = QHBoxLayout()
            row.addWidget(b)
            row.addStretch(1)
            body.addSpacing(4)
            body.addLayout(row)
        lay.addLayout(body, 1)


class RepairDialog(QDialog):
    """Make repaired copy: what TurboCAT will do, in plain words, and a go-ahead."""
    MARK = {"strong": "✓", "likely": "✓", "unsure": "?", "none": "✗"}

    def __init__(self, parent, plan):
        super().__init__(parent)
        self.plan = plan
        self.setWindowTitle("Make repaired copy")
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 16)
        v.setSpacing(12)
        lost = plan.lost
        found = [x for x in lost if x.confidence in ("strong", "likely")]
        unsure = [x for x in lost if x.confidence == "unsure"]
        none = [x for x in lost if x.confidence == "none"]
        head = QLabel(f"Repair #{plan.number:04d}?")
        head.setFont(ui_font(16, QFont.Weight.DemiBold))
        v.addWidget(head)
        n = len(lost)
        if len(found) == n:
            what = f"good copies of {'all ' + str(n) if n > 1 else 'it'} are on your other disks."
        else:
            what = f"good copies of {len(found)} {'is' if len(found) == 1 else 'are'} on your other disks."
        intro = _wrap_label(
            f"{_esc(plan.source_file)}<br>has {n} damaged file{'s' if n != 1 else ''}; {what}",
            ui_font(13))
        intro.setTextFormat(Qt.TextFormat.RichText)
        intro.setFixedWidth(580)
        v.addWidget(intro)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)
        for r, x in enumerate(lost):
            mark = QLabel(self.MARK[x.confidence])
            name = QLabel(x.path)
            name.setFont(ui_font(13, QFont.Weight.DemiBold))
            if x.use is None:
                where = "not on your other disks: it will be left out"
            else:
                disks = len({s.number for s in x.sources})
                where = f"from #{x.use.number:04d} {x.use.name}"
                if x.confidence == "strong":
                    tip = (f"Found on {disks} disks, all identical." if disks > 1 else
                           "Found on one disk, with the same file date as the damaged one.")
                elif x.confidence == "likely":
                    tip = ("Found on one disk only. Same name and size, so very probably the same file."
                           if x.versions == 1 else
                           "Several versions exist; this is the only one with the damaged file's date.")
                else:
                    tip = (f"{x.versions} different files have this name and size. TurboCAT would use "
                           "the one found most often, but can't be sure it is the right one.")
                where += "  ·  " + {"strong": "sure", "likely": "very likely", "unsure": "not sure"}[
                    x.confidence]
                for w in (mark, name):
                    w.setToolTip(tip)
            lab = QLabel(where)
            lab.setObjectName("muted")
            if x.use is not None:
                lab.setToolTip(tip)
            grid.addWidget(mark, r, 0)
            grid.addWidget(name, r, 1)
            grid.addWidget(lab, r, 2)
        grid.setColumnStretch(2, 1)
        v.addLayout(grid)

        self.unsure_box = None
        if unsure:
            self.unsure_box = QCheckBox(f"Also use the file{'s' if len(unsure) > 1 else ''} marked "
                                        "“not sure”")
            self.unsure_box.setToolTip("Left unticked, those files are left out and the copy is marked "
                                       "as still damaged [b].")
            v.addWidget(self.unsure_box)

        does = _wrap_label(
            "<b>What TurboCAT will do</b><br>"
            "• Make a <b>new</b> disk image with these files put back. Your original stays exactly as "
            "it is.<br>"
            "• Mark it as repaired, not original: <i>[f TurboCAT]</i> in its name, and in the "
            "catalogue." + ("" if not none else
                            "<br>• Files not found are left out, so the copy is marked as still damaged "
                            "<i>[b]</i>.") +
            f"<br>• Save it in {_esc(repair.REPAIRED_DIR)} and add it to the catalogue.",
            ui_font(13))
        does.setTextFormat(Qt.TextFormat.RichText)
        does.setFixedWidth(580)
        v.addWidget(does)
        self.mark_box = QCheckBox("Also mark the disk itself (recommended)")
        self.mark_box.setChecked(True)
        self.mark_box.setToolTip(f"Adds a {repair.MARKER} text file saying what was done, and a file note "
                                 "on each restored file. Both show on a real Amiga.")
        v.addWidget(self.mark_box)
        how = QLabel("Files are matched by name and size — hover for what that means")
        how.setObjectName("muted")
        how.setToolTip("TurboCAT can't compare a replacement with the damaged file's contents, because "
                       "those are what was lost. A file with the same name and size, found intact "
                       "elsewhere, is almost always the same file, especially when several disks agree.")
        v.addWidget(how)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        go = QPushButton("Make repaired copy")
        go.setObjectName("primary")
        go.setDefault(True)
        cancel.clicked.connect(self.reject)
        go.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(go)
        v.addLayout(row)

    def with_unsure(self):
        return bool(self.unsure_box and self.unsure_box.isChecked())

    def mark(self):
        return self.mark_box.isChecked()


class ElidedLabel(QLabel):
    """A one-line label that shortens its text with … in the middle when there isn't room, so a
    long path never makes the window wider (the whole text is in its tooltip)."""

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full = ""
        self.setMinimumWidth(40)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text):
        self._full = text
        self.setToolTip(text)
        self._fit()

    def text(self):
        return self._full

    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self._full) + 2, super().sizeHint().height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def _fit(self):
        QLabel.setText(self, self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideMiddle,
                                                           max(0, self.width())))


class FlowLayout(QLayout):
    """Widgets in a row that wraps onto more lines when there isn't room, so a row of buttons
    never makes a narrow panel wider than the space it has."""

    def __init__(self, parent=None, spacing=8):
        super().__init__(parent)
        self._items = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def insertWidget(self, index, widget):
        self.addChildWidget(widget)
        self._items.insert(index, QWidgetItem(widget))
        self.invalidate()

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._place(QRect(0, 0, width, 0), move=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._place(rect, move=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for it in self._items:
            if not it.isEmpty():
                size = size.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _place(self, rect, move):
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line = r.x(), r.y(), 0
        gap = self.spacing()
        for it in self._items:
            if it.isEmpty():
                continue
            hint = it.sizeHint()
            if x > r.x() and x + hint.width() > r.right() + 1:
                x, y, line = r.x(), y + line + gap, 0
            if move:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + gap
            line = max(line, hint.height())
        return y + line - rect.y() + m.bottom()


class KeyButton(QPushButton):
    """A button that shows its keyboard shortcut beside its words, in a small key cap like the
    search box's "Ctrl F"."""

    def __init__(self, text, keys):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 10, 0)
        lay.setSpacing(10)
        self.words = QLabel(text)
        self.words.setObjectName("buttonWords")
        native = QKeySequence(keys).toString(QKeySequence.SequenceFormat.NativeText)
        self.cap = QLabel(native.replace("+", " ") if "+" in native and len(native) > 2 else native)
        self.cap.setObjectName("keyHint")
        self.cap.setFont(data_font(11))
        for w in (self.words, self.cap):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            lay.addWidget(w, 0, Qt.AlignmentFlag.AlignVCenter)
        self._fit()

    def setText(self, text):
        self.words.setText(text)
        self._fit()

    def text(self):
        return self.words.text()

    def setFont(self, font):
        super().setFont(font)
        self.words.setFont(font)
        self._fit()

    def _fit(self):
        self.setMinimumWidth(self.layout().sizeHint().width())

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.EnabledChange:
            self.words.setProperty("off", not self.isEnabled())
            self.words.style().unpolish(self.words)
            self.words.style().polish(self.words)

    def sizeHint(self):
        return QSize(self.layout().sizeHint().width(), super().sizeHint().height())


PLAY_TIP = ("Start this disk (and the rest of its set) in Amiberry or FS-UAE "
            "(Ctrl+P, or double-click it in the list)")


class PictureView(QLabel):
    """A picture that fills the panel's width, keeping its shape (pixel art stays crisp)."""

    MAX_H = 360

    def __init__(self):
        super().__init__()
        self.path = None
        self.setObjectName("picture")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumWidth(40)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def set_picture(self, path):
        self.path = path
        self._fit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def _fit(self):
        if not self.path or self.width() <= 0:
            return
        src = QPixmap(self.path)
        if src.isNull():
            return
        w = self.width()
        h = min(self.MAX_H, int(src.height() * w / src.width()))
        pm = thumb(self.path, w, h)
        if pm is not None:
            if self.height() != pm.height():
                self.setFixedHeight(pm.height())
            self.setPixmap(pm)


RECHECK_TIP = ("Look again at just this (for a set, all its disks) and the folder it is in: a disk "
               "you have replaced, added or deleted there is picked up without rescanning "
               "everything (Shift+F5)")


class DetailsPanel(QFrame):
    """Everything about the selected item: the right-hand panel of the design."""
    FACTS = ["Filesystem", "Bootblock", "Contents", "Status", "Size", "Scanned"]

    def __init__(self, cat, on_select_number, on_copy=None, on_online=None, on_play=None,
                 on_start=None):
        super().__init__()
        self.cat = cat
        self.on_select_number = on_select_number
        self.on_keep = None          # keep this copy of a duplicate (set by the window)
        self.on_favourite = None     # star / unstar what is shown (set by the window)
        self.on_recheck = None       # look again at what is shown, and its folder (set by the window)
        self.item = None
        self.on_version = None       # show this version of a disk (set by the window)
        self.source = None
        self.item_id = None
        self.setObjectName("details")
        self.setMinimumWidth(360)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack)

        self.placeholder = QLabel("Select an item to see its details.")
        self.placeholder.setObjectName("message")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setWordWrap(True)
        self.placeholder.setFont(ui_font(14))
        self.stack.addWidget(self.placeholder)

        page = QWidget()
        page.setObjectName("detailsPage")
        v = QVBoxLayout(page)
        v.setContentsMargins(20, 20, 20, 20)
        v.setSpacing(16)

        head = QHBoxLayout()
        head.setSpacing(14)
        self.big_icon = QLabel()
        self.big_icon.setFixedSize(64, 64)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.kicker = _wrap_label("", data_font(13), "muted")
        self.title = _wrap_label("", ui_font(24, QFont.Weight.Bold))
        self.path = _wrap_label("", ui_font(13), "muted")
        for w in (self.kicker, self.title, self.path):
            col.addWidget(w)
        head.addWidget(self.big_icon, 0, Qt.AlignmentFlag.AlignTop)
        head.addLayout(col, 1)
        v.addLayout(head)

        self.picture = PictureView()
        v.addWidget(self.picture)
        self.pic_caption = _wrap_label("", ui_font(12), "muted")
        self.pic_caption.setTextFormat(Qt.TextFormat.RichText)
        self.pic_caption.linkActivated.connect(
            lambda link: on_online() if link == "#online" and on_online else
            QDesktopServices.openUrl(QUrl(link)))
        v.addWidget(self.pic_caption)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(12)
        self.facts = {}
        for i, name in enumerate(self.FACTS):
            cell = QVBoxLayout()
            cell.setSpacing(2)
            cell.addWidget(_wrap_label(name, ui_font(13), "muted"))
            row = QHBoxLayout()
            row.setSpacing(6)
            pic = QLabel()
            pic.setFixedSize(16, 16)
            pic.hide()
            val = _wrap_label("", ui_font(13, QFont.Weight.DemiBold))
            row.addWidget(pic, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(val, 1)
            cell.addLayout(row)
            grid.addLayout(cell, i // 2, i % 2)
            self.facts[name] = (pic, val)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        v.addLayout(grid)

        self.notes = QVBoxLayout()
        self.notes.setSpacing(10)
        v.addLayout(self.notes)

        lf = ui_font(12, QFont.Weight.DemiBold)
        lf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.6)
        self.music_label = QLabel("MUSIC")
        self.music_label.setObjectName("section")
        self.music_label.setFont(lf)
        v.addWidget(self.music_label)
        self.tunes = QTreeWidget()
        self.tunes.setObjectName("tunes")
        self.tunes.setColumnCount(2)
        self.tunes.setHeaderHidden(True)
        self.tunes.setRootIsDecorated(False)
        self.tunes.setUniformRowHeights(True)
        self.tunes.setFont(ui_font(13))
        self.tunes.setIconSize(QSize(16, 16))
        self.tunes.setToolTip("Double-click a tune (or select it and press Enter) to play it")
        mh = self.tunes.header()
        mh.setStretchLastSection(False)
        mh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        mh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tunes.itemActivated.connect(lambda it, _c: on_play and on_play(self.tune_rows, it.data(0, Qt.ItemDataRole.UserRole)))
        v.addWidget(self.tunes)
        self.tune_rows = []

        self.contents_label = QLabel("CONTENTS")
        self.contents_label.setObjectName("section")
        self.contents_label.setFont(lf)
        v.addWidget(self.contents_label)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setFont(data_font(12))
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tree.setIndentation(16)
        th = self.tree.header()
        th.setStretchLastSection(False)
        th.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        th.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        th.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        v.addWidget(self.tree)

        buttons = FlowLayout(spacing=8)
        self.fav_btn = QPushButton()
        self.fav_btn.setFont(ui_font(13, QFont.Weight.DemiBold))
        self.fav_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fav_btn.setToolTip("Star it, so it shows under Favourites here and in TurboView (Ctrl+D)")
        self.fav_btn.clicked.connect(lambda: self.on_favourite and self.on_favourite())
        buttons.addWidget(self.fav_btn)
        self.show_btn = QPushButton("Show in folder")
        self.show_btn.setFont(ui_font(13, QFont.Weight.DemiBold))
        self.show_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.show_btn.setToolTip("Open the folder holding it (Ctrl+Shift+O)")
        self.show_btn.clicked.connect(self.show_in_folder)
        buttons.addWidget(self.show_btn)
        self.play_btn = QPushButton("Play in emulator")
        self.play_btn.setObjectName("primary")
        self.play_btn.setFont(ui_font(13, QFont.Weight.DemiBold))
        self.play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play_btn.setToolTip(PLAY_TIP)
        self.play_ids = []           # what Play starts: the item, its set, or a good copy of an empty disk
        self.play_btn.clicked.connect(lambda: on_start and self.play_ids and on_start(list(self.play_ids)))
        buttons.insertWidget(0, self.play_btn)
        self.copy_btn = QPushButton("Copy to Gotek stick")
        self.copy_btn.setFont(ui_font(13, QFont.Weight.DemiBold))
        self.copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_btn.setToolTip("Copy this disk to a USB stick for a Gotek drive (Ctrl+G)")
        self.copy_btn.clicked.connect(lambda: on_copy and self.item_id and on_copy(
            list(self.item.members) if self.item is not None and self.item.members else [self.item_id]))
        buttons.addWidget(self.copy_btn)
        self.recheck_btn = QPushButton("Recheck")
        self.recheck_btn.setFont(ui_font(13, QFont.Weight.DemiBold))
        self.recheck_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.recheck_btn.setToolTip(RECHECK_TIP)
        self.recheck_btn.clicked.connect(lambda: self.on_recheck and self.on_recheck())
        buttons.addWidget(self.recheck_btn)
        v.addLayout(buttons)
        v.addStretch(1)
        scroll = QScrollArea()
        scroll.setObjectName("detailsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        self.stack.addWidget(scroll)
        self.page = scroll

    # -------------------------------------------------------------- filling
    def clear(self):
        self.source = None
        self.item_id = None
        self.stack.setCurrentWidget(self.placeholder)

    def _descendants(self, mid):
        out, todo = [], [mid]
        while todo:
            rows = self.cat.db.execute(
                f"SELECT * FROM media WHERE parent_id IN ({','.join('?' * len(todo))}) ORDER BY id",
                todo).fetchall()
            out += rows
            todo = [r["id"] for r in rows]
        return out

    def _playable_version(self, item):
        """Another version or copy of this disk that has a real floppy image in it, or None."""
        others = list(item.other_versions) + ([item.version_of] if item.version_of else []) + \
            list(item.spares) + ([item.spare_of] if item.spare_of else [])
        for oid in others:
            rows = [self.cat.media_by_id(oid)] + self._descendants(oid)
            if any(r is not None and r["kind"] in gotek.FLOPPY_KINDS and r["status"] != "empty"
                   and r["size"] for r in rows):
                return oid
        return None

    def _cover_note(self, item, m):
        """What is known about a coverdisk: its magazine, issue and disk, and how sure that is."""
        cd = item.cover
        what = cd.magazine or "a magazine"
        if cd.issue:
            what += f" issue {cd.issue.lstrip('0') or cd.issue}"
        if cd.date:
            what += f" ({cd.date})"
        disk = ""
        if cd.disk and cd.of and cd.of != "1":
            disk = f", disk {cd.disk} of {cd.of}"
        if cd.label and cd.how != "made":
            disk += f" — {_esc(cd.label)}"
        tosec = f"<br>TOSEC's name for it: {_esc(cd.tosec_name)}" if cd.tosec_name else ""
        empty = m["status"] == "empty" or not m["size"]
        if cd.how == "checksum":
            self.notes.addWidget(Note(
                "accent", "ok", f"<b>Coverdisk from {_esc(what)}{disk}.</b> Its checksum matches TOSEC's "
                f"list of coverdisks exactly, so this is a known good copy.{tosec}"))
        elif cd.how == "name" and empty:
            self.notes.addWidget(Note(
                "warn", "warning", f"<b>Coverdisk from {_esc(what)}{disk}</b> — recognised by its name, "
                "but this file is empty (0 bytes): the disk's data is missing, so it can't be checked "
                f"or played. TOSEC lists the disk, so a good copy exists.{tosec}"))
        elif cd.how == "name":
            ambiguous = "" if cd.tosec_name else (" The file name doesn't say which of the issue's disks "
                                                   "it is.")
            self.notes.addWidget(Note(
                "neutral", "magazine", f"<b>Coverdisk from {_esc(what)}{disk}</b> — recognised by its "
                "name. Its checksum isn't the one in TOSEC's list, so it is a different copy of the "
                "disk, or one that has been changed (written to, or saved with a game's progress)."
                f"{ambiguous}{tosec}"))
        elif cd.how == "made":
            self.notes.addWidget(Note(
                "neutral", "magazine", f"<b>Made from the coverdisk of {_esc(what)}.</b> It is in a folder "
                "beside the issue's disks, so it was probably made by one of them (an installer or a "
                "“create disks” program). TOSEC doesn't list disks like this."
                + (" This file is empty (0 bytes)." if empty else "")))
        else:
            hint = ("" if identify.have_tosec() else " <b>Tools › Identify disks online…</b> downloads "
                    "TOSEC's lists, to check its issue and disk.")
            self.notes.addWidget(Note(
                "neutral", "magazine", f"<b>Coverdisk</b>{' from ' + _esc(what) if cd.magazine else ''}, "
                f"going by its folder. TOSEC's list of coverdisks doesn't have this one.{hint}"))

    def _set_fact(self, name, text, ico=None, color=None):
        pic, val = self.facts[name]
        val.setText(_breakable(text))
        val.setStyleSheet(f"color: {color.name()};" if color else "")
        if ico:
            pic.setPixmap(icon(ico, 16))
            pic.show()
        else:
            pic.hide()

    def _disk_files(self, media_id):
        """{path: sha1} of the files on an item's disk (the one disk inside an archive)."""
        kids = self.cat.db.execute("SELECT id, kind FROM media WHERE parent_id=?", (media_id,)).fetchall()
        mid = kids[0]["id"] if len(kids) == 1 and kids[0]["kind"] in DISK_KINDS else media_id
        # AmigaDOS names ignore case: S/Startup-Sequence and S/startup-sequence are one file.
        return {f["path"].lower(): (f["path"], f["sha1"]) for f in self.cat.db.execute(
            "SELECT path, sha1 FROM files WHERE media_id=? AND is_dir=0", (mid,))}

    def _difference(self, a, b):
        """How disk b's files differ from disk a's, in a few words."""
        fa, fb = self._disk_files(a), self._disk_files(b)
        if not fa and not fb:
            return "no files to compare"
        if {k: v[1] for k, v in fa.items()} == {k: v[1] for k, v in fb.items()}:
            return "same files"
        changed = sorted(fb[p][0] for p in fa.keys() & fb.keys() if fa[p][1] != fb[p][1])
        extra = sorted(fb[p][0] for p in fb.keys() - fa.keys())
        gone = sorted(fa[p][0] for p in fa.keys() - fb.keys())
        bits = []
        if changed:
            bits.append("changed " + ", ".join(changed[:3]) + (f" +{len(changed) - 3}" if len(changed) > 3 else ""))
        if extra:
            bits.append("extra " + ", ".join(extra[:3]) + (f" +{len(extra) - 3}" if len(extra) > 3 else ""))
        if gone:
            bits.append("without " + ", ".join(gone[:3]) + (f" +{len(gone) - 3}" if len(gone) > 3 else ""))
        return "files differ: " + "; ".join(bits)

    def _versions_note(self, item):
        """Versions of one disk: which is shown, what the others are, how they differ."""
        acc = C["accent"].name()

        def what(path):
            t = vers.tags(path)
            return "; ".join(_esc(vers.describe(x)) for x in t) if t else "the standard version, no tags"

        def link(row):
            return f"<a href='{row['number']}' style='color:{acc}'>#{row['number']:04d}</a>"

        if item.version_of:
            shown = self.cat.media_by_id(item.version_of)
            if shown is None:
                return Note("neutral", None, "")
            return Note(
                "neutral", "duplicate",
                f"<b>Another version</b> of {link(shown)} {_esc(os.path.basename(shown['source']))}.<br>"
                f"This one: {what(item.path)} · {self._difference(shown['id'], item.id)}.<br>"
                f"With grouping on, TurboCAT shows #{shown['number']:04d} and hides this one (nothing is "
                f"deleted). <a href='version:{item.id}' style='color:{acc}'>Show this version instead</a>",
                on_link=self._note_link)
        lines = []
        for vid in item.other_versions[:8]:
            r = self.cat.media_by_id(vid)
            if r is None:
                continue
            lines.append(f"{link(r)} {what(r['source'])} · {self._difference(item.id, vid)} · "
                         f"<a href='version:{vid}' style='color:{acc}'>show this one instead</a>")
        more = f"<br>and {len(item.other_versions) - 8} more" if len(item.other_versions) > 8 else ""
        return Note(
            "accent", "duplicate",
            f"<b>{item.versions} versions of this disk.</b> TurboCAT shows this one ({what(item.path)}) and "
            f"hides the others while grouping is on (nothing is deleted):<br>" + "<br>".join(lines) + more,
            on_link=self._note_link)

    def _set_note(self, item):
        """A disk set: its disks in order, with gaps, problems and other versions."""
        ds, acc = item.dset, C["accent"].name()
        tone = {"ok": "accent", "warn": "warn", "problem": "problem"}[item.set_tone]
        folders = {os.path.dirname(it.path) for _, it, _ in ds.disks}
        home = os.path.expanduser("~")

        def link(it):
            where = (f" <span style='color:{C['ink-muted'].name()}'>in "
                     f"{_esc(os.path.dirname(it.path).replace(home, '~'))}</span>") if len(folders) > 1 else ""
            bad = " — <b>has problems</b>" if it.status == "error" else ""
            rest = it.file[len(ds.key):].strip() if it.file.startswith(ds.key) else it.file
            return (f"<a href='{it.number}' style='color:{acc}'>#{it.number:04d}</a> "
                    f"{_esc(rest)}{bad}{where}")

        have = {n: (it, others) for n, it, others in ds.disks}
        lines = []
        for n in range(1, ds.expected + 1):
            if n in have:
                it, others = have[n]
                line = f"Disk {n}: {link(it)}"
                if others:
                    line += f"<br>&nbsp;&nbsp;&nbsp;other version{'s' if len(others) > 1 else ''}: " + \
                            ", ".join(link(o) for o in others[:3])
            else:
                line = f"Disk {n}: <b>missing</b>"
            lines.append(line)
        if ds.complete:
            head = f"<b>Complete set of {ds.expected} disks.</b> Play starts them all, disk 1 first."
        else:
            need = ds.missing + ds.problem_disks
            head = (f"<b>Incomplete set:</b> {len(ds.disks)} of {ds.expected} disks here"
                    + (f", needs disk{'s' if len(need) > 1 else ''} {', '.join(map(str, sorted(need)))}"
                       if need else "") + ".")
        flags = "".join(f"<br><i>{_esc(_cap(f))}</i>" for f in ds.flags)
        return Note(tone, "disk", f"{head}{flags}<br>" + "<br>".join(lines), on_link=self._note_link)

    def _note_link(self, href):
        """Links in notes: an item number to jump to, or keep:<id> to keep that copy."""
        if href.startswith("keep:"):
            m = self.cat.media_by_id(int(href[5:]))
            if m is not None and self.on_keep:
                self.on_keep(m)
        elif href.startswith("version:"):
            m = self.cat.media_by_id(int(href[8:]))
            if m is not None and self.on_version:
                self.on_version(m)
        else:
            self.on_select_number(int(href))

    def _partly_repaired_note(self, item):
        """A damaged disk with a repaired copy that is still missing files."""
        copy = self.cat.media_by_id(item.repaired_copy)
        if copy is None:
            return
        made = repair.log_for(copy["sha1"] or "")
        back = [f for f, src in made if src]
        still = [f for f, src in made if not src]
        self.notes.addWidget(Note(
            "neutral", "tool",
            f"<b>Partly repaired</b> — <a href='{copy['number']}'>#{copy['number']:04d}</a> has "
            f"{len(back)} of {len(back) + len(still)} damaged files back. Still missing:",
            [_esc(x) for x in still],
            on_link=lambda h: self.on_select_number(int(h)),
            tip=repair.FINISH_IT))

    def _not_fixable_note(self, item, m, kids, bad):
        """Whether the collection can fix a damaged disk with no good copy: the short answer, and
        the reason on hover."""
        win = self.window()
        everything = getattr(win, "all_items", [])
        reasons = explain.why_not_fixable(item, everything)
        found = explain.found_elsewhere(self.cat, bad, [m["id"]] + [k["id"] for k in kids])
        if bad and found:
            missing = [p for p in bad if p not in found]
            head = ("<b>Could be rebuilt</b> — every damaged file is on your other disks"
                    if not missing else
                    f"<b>Partly rebuildable</b> — {len(found)} of {len(bad)} damaged files "
                    f"{'is' if len(found) == 1 else 'are'} on your other disks")
            lines = [f"{os.path.basename(p)}: on #{', #'.join(f'{n:04d}' for n in nums[:3])}"
                     for p, nums in found.items()]
            mid = m["id"]
            self.notes.addWidget(Note(
                "neutral", "tool", head, [_esc(x) for x in lines],
                tip="\n".join(reasons + ([
                    "Not on your other disks: " + ", ".join(os.path.basename(p) for p in missing) + "."]
                    if missing else []) + [
                    "Make repaired copy… shows exactly what TurboCAT would do, and asks first. "
                    "Your original is never changed."]),
                button=("Make repaired copy…",
                        lambda: win.make_repaired_copy(mid) if hasattr(win, "make_repaired_copy") else None)))
            return
        tip = reasons + ([("The damaged file isn't" if len(bad) == 1 else "None of the damaged files are")
                          + " on any of your other disks either."] if bad else [])
        tip.append("To fix it, get a clean copy of the disk (for free disks, from a PD archive such as "
                   "Aminet).")
        self.notes.addWidget(Note("neutral", None, "<b>Can't be fixed from your collection</b> "
                                  "— hover for why", tip="\n".join(tip)))

    def show_item(self, item):
        m = self.cat.media_by_id(item.id)
        if m is None:
            self.clear()
            return
        kids = self._descendants(m["id"])
        kind = m["kind"] or ""
        self.source = m["source"]
        self.item_id = m["id"]
        self.item = item
        self.fav_btn.setIcon(QIcon(icon("star" if item.favourite else "star-off", 16)))
        self.fav_btn.setText("Favourite" if item.favourite else "Add to favourites")
        floppy = any(r["kind"] in gotek.FLOPPY_KINDS and r["status"] != "empty" for r in [m] + kids)
        self.copy_btn.setVisible(floppy and not m["whd_name"])
        ipf = item.game and bool(self.cat.db.execute(
            "SELECT 1 FROM files WHERE media_id=? AND lower(path) LIKE '%.ipf' LIMIT 1", (m["id"],)).fetchone())
        playable = floppy or ipf or (bool(m["whd_name"]) and kind == "lha")
        self.play_ids = list(item.members) if item.members else [m["id"]]
        play_text, play_tip, play_on = "Play in emulator", PLAY_TIP, True
        if not playable and item.cover is not None:
            # An empty copy of a coverdisk: play another copy of the same disk if there is a good one.
            other = self._playable_version(item)
            if other:
                self.play_ids, playable = [other], True
                play_text = "Play a good copy"
                play_tip = (f"This file is empty; #{self.cat.media_by_id(other)['number']:04d} is a good "
                            "copy of the same disk, and Play starts that one")
            elif m["status"] == "empty" or not m["size"]:
                playable, play_on = True, False
                play_tip = ("This file is empty (0 bytes), so there is no disk to play, and no other copy "
                            "of it is catalogued")
        self.play_btn.setText(play_text)
        self.play_btn.setToolTip(play_tip)
        self.play_btn.setEnabled(play_on)
        self.play_btn.setVisible(playable)
        # An archive holding one disk image is described by that disk.
        d = m
        direct = [k for k in kids if k["parent_id"] == m["id"]]
        if kind in ARCHIVE_KINDS and not m["whd_name"] and len(direct) == 1 \
                and direct[0]["kind"] in DISK_KINDS:
            d = direct[0]
        info = _j(d["info"], {})

        own = thumb(item.thumb_icon, 64, 64, upscale=False) if item.thumb_icon else None
        self.big_icon.setPixmap(own if own is not None else icon(item.icon, 64))
        self.big_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._show_picture(item)
        what = KIND_NAME.get(kind, kind.upper())
        if d is not m:
            what = f"{KIND_NAME.get(d['kind'], d['kind'].upper())} in a {KIND_NAME.get(kind, kind)}"
        if m["whd_name"]:
            what = "WHDLoad game · " + what
        self.kicker.setText(f"#{item.number:04d} · {what}")
        self.title.setText(item.title)
        self.title.setFont(ui_font(24, QFont.Weight.Bold, italic=item.from_text))
        self.title.setToolTip("Taken from text found on the disk" if item.from_text else "")
        self.path.setText(_breakable(m["source"]))

        # Facts
        non_dos = "non-DOS" in str(info.get("format", ""))
        if d["status"] == "empty":
            fs = "None (no data)"
        elif non_dos:
            fs = _cap(info["format"]) + (f", {DENSITY[info['density']]}"
                                          if info.get("density") in DENSITY else "")
        elif d["fs"]:
            fs = d["fs"] + (f", {DENSITY[info['density']]}" if info.get("density") in DENSITY else "")
        elif info.get("format"):
            fs = _cap(info["format"])
        elif kind in ("lha", "lzx", "zip"):
            fs = "Archive"
        elif kind == "folder":
            fs = "Folder on this computer"
        else:
            fs = "—"
        self._set_fact("Filesystem", fs)
        self._set_fact("Bootblock", _cap(d["boot_kind"] or "") or "—")

        # For a one-disk archive, count the disk's files, not the archive's single entry.
        others = [k for k in kids if k["id"] != d["id"]]
        n_files = (d["file_count"] or 0) + sum(k["file_count"] or 0 for k in others)
        n_dirs = self.cat.db.execute(
            f"SELECT COUNT(*) FROM files WHERE is_dir=1 AND media_id IN "
            f"({','.join('?' * (len(others) + 1))})", [d["id"]] + [k["id"] for k in others]).fetchone()[0]
        bits = [f"{n_files:,} file{'s' if n_files != 1 else ''}"]
        if n_dirs:
            bits.append(f"{n_dirs:,} folder{'s' if n_dirs != 1 else ''}")
        if others:
            bits.append(f"{len(others)} archives or images inside" if len(others) > 1
                        else "1 archive or image inside")
        if not n_files and not others and (non_dos or d["status"] == "empty" or not d["fs"]):
            contents = "No AmigaDOS files" if d["status"] != "empty" else "Nothing"
        else:
            contents = ", ".join(bits)
        if kind == "kickstart":
            models = info.get("models") or []
            bits = [f"Version {info['kickstart']}" if info.get("kickstart") else "Version unknown"]
            if info.get("rom_size"):
                bits.append(info["rom_size"])
            if info.get("machine"):
                bits.append("made for the " + info["machine"])
            if models:
                bits.append("Play in emulator uses it for the " + " and ".join(models))
            contents = " · ".join(bits)
        self._set_fact("Contents", contents)

        kid_status = {k["status"] for k in kids}
        status = d["status"] if m["status"] == "ok" else m["status"]
        if status == "ok" and "error" in kid_status:
            status = "error"
        elif status == "ok" and "warning" in kid_status:
            status = "warning"
        word = {"ok": ("OK — no problems found", "ok", "ok"),
                "warning": ("Warning — see below", "warning", "warn"),
                "error": ("Problem — see below", "problem", "problem"),
                "empty": ("Empty — no disk data", None, "ink-soft")}.get(status, (status, None, "ink"))
        self._set_fact("Status", word[0], word[1], C[word[2]])
        self._set_fact("Size", _size(m["size"]))
        self._set_fact("Scanned", time.strftime("%-d %b %Y, %H:%M", time.localtime(m["scanned_at"]))
                       if m["scanned_at"] else "—")

        # Notes
        while self.notes.count():
            w = self.notes.takeAt(0).widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        if item.members:
            self.notes.addWidget(self._set_note(item))
        if d["status"] == "empty":
            if not d["size"]:
                self.notes.addWidget(Note(
                    "neutral", None, "<b>Empty file</b> — 0 bytes, so there is no disk in it.",
                    ["The original data was probably lost when the file was copied or synced. "
                     "Look for another copy on an older computer, a backup drive or in your "
                     "cloud storage's version history."]))
            else:
                self.notes.addWidget(Note(
                    "neutral", None, "<b>Blank disk</b> — every track is empty (all zeros).",
                    ["Either nothing was ever written to this disk, or the data was lost when "
                     "the image was made or copied."]))
        acc = C['accent'].name()

        def where(r):
            """#0045 Mods_B1.DMS, and the folder it is in."""
            num = self.cat.top_number(r)
            name = os.path.basename(self.cat.label(r).split(" > ", 1)[0])
            if r["parent_id"]:
                name += " › " + r["inner_path"]
            return f"<a href='{num}' style='color:{acc}'>#{num:04d} {_esc(name)}</a>"

        def folder(r):
            return _esc(os.path.dirname(r["source"]).replace(os.path.expanduser("~"), "~"))

        if item.copies > 1 and item.spare_of:
            keep = self.cat.media_by_id(item.spare_of)
            if keep is not None:
                self.notes.addWidget(Note(
                    "neutral", "duplicate",
                    f"<b>Spare copy</b> of {where(keep)}, in {folder(keep)}. They are the same disk, "
                    f"so TurboCAT shows that copy and hides this one. Nothing is deleted: this file "
                    f"stays where it is.<br><a href='keep:{item.id}' style='color:{acc}'>"
                    f"Keep this copy instead</a>", on_link=self._note_link))
        elif item.copies > 1:
            rows = [r for r in (self.cat.media_by_id(i) for i in item.spares) if r is not None]
            spares = "<br>".join(f"{where(r)} in {folder(r)} · <a href='keep:{r['id']}' "
                                 f"style='color:{acc}'>keep that one instead</a>" for r in rows[:6])
            more = f"<br>and {len(rows) - 6} more" if len(rows) > 6 else ""
            self.notes.addWidget(Note(
                "accent", "duplicate",
                f"<b>{item.copies} copies of this disk.</b> TurboCAT shows this one and hides the "
                f"spare{'s' if len(rows) != 1 else ''} (nothing is deleted):<br>{spares}{more}",
                on_link=self._note_link))
        if item.versions > 1:
            self.notes.addWidget(self._versions_note(item))
        if item.shares:
            own = {m["id"]} | {k["id"] for k in kids}
            mine = {k["sha1"]: k for k in kids if k["sha1"] in item.shares}
            lines = []
            for sha, k in list(mine.items())[:3]:
                others = [r for r in self.cat.media_with_sha1(sha) if r["id"] not in own]
                if others:
                    lines.append(f"{_esc(k['inner_path'])} is also in " + ", ".join(where(r) for r in others[:3]))
            if lines:
                self.notes.addWidget(Note(
                    "neutral", "duplicate",
                    "<b>Shares files with other disks.</b> The same archive is on more than one "
                    "disk, but the disks themselves are different, so both are kept.<br>"
                    + "<br>".join(lines), on_link=self._note_link))
        if item.game and not m["whd_name"]:
            self.notes.addWidget(Note("neutral", "game", f"<b>Game</b> — {_esc(item.game)}"))
        if item.cover is not None and not item.members:
            self._cover_note(item, m)
        if item.tosec_name and not item.members and not (item.cover and item.cover.how == "checksum"):
            t = vers.tags(item.tosec_name)
            meaning = ("<br>" + "; ".join(f"[{_esc(x)}] {_esc(vers.describe(x))}" for x in t)) if t else ""
            same = not _renamed(item)
            self.notes.addWidget(Note(
                "accent", "ok",
                f"<b>Identified by its checksum:</b> {_esc(item.tosec_name)}{meaning}<br>"
                f"From {_esc(item.identified_by)}." + ("" if same else
                f" The file is called {_esc(item.file)}; Tools › Rename files to their proper names… "
                "can rename it (it asks first).")))
        elif not item.members and item.cover is None and not identify.have_list() and \
                identify.GENERIC_FILE.match(os.path.splitext(item.file)[0].strip()):
            self.notes.addWidget(Note(
                "accent", None,
                f"<b>What is {_esc(item.file)}?</b> Its name doesn't say. TurboCAT can find a disk's "
                "proper name from its checksum: choose <b>Tools › Identify disks online…</b> (it asks "
                "before downloading the list of Amiga disks; your files aren't renamed)."
                + (f"<br>Possibly {_esc(item.name_guess)}, going by the folder it is in." if item.name_guess else "")))
        elif item.name_guess:
            self.notes.addWidget(Note(
                "neutral", None,
                f"<b>Possibly {_esc(item.name_guess)}</b> — a guess from the folder it is in; the file "
                f"name and the disk itself don't say. Tools › Identify disks online… can check it "
                "against the TOSEC list of Amiga disks."))
        if item.utility:
            self.notes.addWidget(Note("neutral", "tool", f"<b>Utility</b> — {_esc(item.utility)}"))
        if item.verified and item.verified[0] == "match" and item.status == "error":
            self.notes.addWidget(Note(
                "neutral", None, "<b>Same as the collection's copy</b> — hover for what that means",
                tip=f"This file is exactly the one listed in {item.verified[1]}.\nSo the damage "
                    "was already in the copy that collection holds: it didn't happen to yours."))
        elif item.verified and item.verified[0] == "match":
            self.notes.addWidget(Note(
                "accent", "ok", f"<b>Verified</b> — exactly the file listed in {_esc(item.verified[1])}: "
                "complete and undamaged."))
        elif item.verified:
            self.notes.addWidget(Note(
                "warn", "warning", f"<b>Doesn't match the collection list</b> — {_esc(item.verified[1])} "
                "lists a file of this name with different contents. This copy may be damaged, "
                "or a different version."))
        if m["whd_name"]:
            lines = [x for x in (m["whd_copy"], m["whd_info"]) if x]
            self.notes.addWidget(Note("accent", "game", f"<b>WHDLoad game:</b> {_esc(m['whd_name'])}",
                                      lines))

        if item.repaired:
            made = repair.log_for(item.sha1)
            self.notes.addWidget(Note(
                "accent", "tool", "<b>Repaired copy, not an original dump</b> — made by TurboCAT. "
                "Hover for where its restored files came from.",
                tip="\n".join([f"{f}  from {src}" for f, src in made if src]
                               or ["(not in TurboCAT's repair log)"])
                    + "\n\nThe disk also holds a Repaired-by-TurboCAT note, and each restored file "
                      "has a file note saying where it came from."))
            still = [f for f, src in made if not src]
            if still:
                self.notes.addWidget(Note(
                    "warn", "warning",
                    f"<b>Still missing {_n(len(still), 'file')}</b> — "
                    f"{'it isn' if len(still) == 1 else 'they aren'}'t anywhere in your collection. "
                    "Hover for how to fix it fully.",
                    [_esc(x) for x in still], tip=repair.FINISH_IT))

        def collect(field):
            out = []
            for r in [m] + kids:
                where = f"{r['inner_path']}: " if r["parent_id"] else ""
                out += [where + x for x in _j(r[field], [])]
            return out
        if m["status"] != "empty":
            problems = collect("problems")
            if problems:
                total = int(item.files.replace(",", "")) if item.files.replace(",", "").isdigit() else 0
                bad = explain.damaged_paths(problems)
                self.notes.addWidget(Note(
                    "problem", "problem", f"<b>{_esc(explain.summary(problems, total))}</b>",
                    [_esc(p) for p in bad],
                    tip="What TurboCAT found:\n" + "\n".join(x[:200] for x in problems[:25])
                        + (f"\n… and {len(problems) - 25} more" if len(problems) > 25 else "")))
                if item.repaired_copy and not item.good_copy:
                    self._partly_repaired_note(item)
                full = item.rebuild and item.rebuild[0] == item.rebuild[1]
                if (not item.good_copy and not item.fixable and m["status"] != "empty"
                        and (not item.repaired_copy or full)):
                    self._not_fixable_note(item, m, kids, bad)
        good = self.cat.media_by_id(item.good_copy) if item.good_copy else None
        if good is not None:
            name = os.path.basename(good["source"].rstrip("/"))
            what = [vers.describe(t) for t in vers.tags(name)]
            fixed = (good["sha1"] or "") in repair.repaired_sha1s() or any(
                (k["sha1"] or "") in repair.repaired_sha1s() for k in self._descendants(good["id"]))
            self.notes.addWidget(Note(
                "accent", "ok",
                (f"<b>You have a repaired copy</b> — <a href='{good['number']}'>#{good['number']:04d}</a>, "
                 "made by TurboCAT from this disk and files on your other disks. It isn't an original dump."
                 if fixed else
                 f"<b>Empty file, but you have a working copy</b> — "
                 f"<a href='{good['number']}'>#{good['number']:04d}</a> is the same disk, and it reads "
                 "fully. Nothing is lost; this empty file can be deleted."
                 if item.status == "empty" else
                 f"<b>You have a good copy</b> — <a href='{good['number']}'>#{good['number']:04d}</a> "
                 "is another version of this disk, and it reads fully. Nothing is lost."),
                [_esc(name)] + ([f"That version: {_esc(', '.join(what))}"]
                                if what and item.status != "empty" else []),
                on_link=lambda h: self.on_select_number(int(h))))
        warnings = collect("warnings")
        fs_issues = [w for w in warnings if FS_ISSUE in w]
        warnings = [w for w in warnings if FS_ISSUE not in w]
        if warnings:
            self.notes.addWidget(Note("warn", "warning", "<b>Warning</b>", warnings))
        for prog, pkg, here in readers.local_fixes(collect("problems") + collect("warnings")):
            if here:
                self.notes.addWidget(Note(
                    "accent", "tool", "<b>Can be fixed now</b> — "
                    f"{_esc(prog)} has been installed since this was read. Disk › Recheck "
                    "(Shift+F5) reads it again; so will the next scan of its folder."))
            else:
                self.notes.addWidget(Note(
                    "accent", "tool", "<b>Can be fixed on this computer</b> — "
                    f"install {_esc(pkg)}, then scan this folder again and TurboCAT will read "
                    "it properly. Help › Check setup shows how to install it."))
        if fs_issues:
            self.notes.addWidget(Note(
                "warn", "warning",
                f"<b>Filesystem inconsistencies</b> ({len(fs_issues)}), but every file reads",
                [w.split(FS_ISSUE, 1)[1] for w in fs_issues]))
        notes = []
        for r in [m] + kids:
            ri = _j(r["info"], {})
            notes += ri.get("notes", []) + ([ri["note"]] if ri.get("note") else [])
        if notes:
            self.notes.addWidget(Note("neutral", None, "<b>Notes</b>", [_cap(x) for x in notes]))

        # Contents tree, or the disk's readable text when it has no files
        self.tree.clear()
        total = self._fill_tree(d, others)
        if total:
            self.contents_label.setText("CONTENTS")
            if total <= 300:
                self.tree.expandAll()
        else:
            texts = _j(d["text"], [])
            for t in texts[:200]:
                it = QTreeWidgetItem([t])
                self.tree.addTopLevelItem(it)
                it.setFirstColumnSpanned(True)
            self.contents_label.setText("TEXT FOUND ON THE DISK" if texts else "CONTENTS")
            if not texts and m["status"] != "empty" and m["kind"] != "kickstart":
                it = QTreeWidgetItem(["Nothing to list."])
                it.setForeground(0, C["ink-muted"])
                self.tree.addTopLevelItem(it)
        self._fill_tunes(item)
        has_list = self.tree.topLevelItemCount() > 0
        self.contents_label.setVisible(has_list)
        self.tree.setVisible(has_list)
        self._fit_tree()
        self.stack.setCurrentWidget(self.page)
        self.page.verticalScrollBar().setValue(0)

    def _fill_tunes(self, item):
        self.tunes.clear()
        self.tune_rows = self.cat.db.execute(
            "SELECT * FROM music WHERE key=? ORDER BY rowid", (item.key,)).fetchall() if item.music else []
        for i, r in enumerate(self.tune_rows):
            name = r["file"].rsplit("/", 1)[-1]
            title = r["title"] or re.sub(r"^(mod|med|xm|s3m)\.", "", name, flags=re.I)
            ok = r["fmt"] in music.PLAYABLE
            where = f"{r['fmt']}" + (f" · in {name}" if r["length"] else "")
            it = QTreeWidgetItem([title, where])
            it.setData(0, Qt.ItemDataRole.UserRole, i)
            it.setIcon(0, QIcon(icon("music", 16)))
            it.setForeground(1, C["ink-muted"])
            it.setToolTip(0, r["shown"] + ("" if ok else f"\n{r['fmt']} tunes can't be played yet"))
            if not ok:
                it.setDisabled(True)
            self.tunes.addTopLevelItem(it)
        n = len(self.tune_rows)
        self.music_label.setText(f"MUSIC · {n} MODULE{'S' if n != 1 else ''} · DOUBLE-CLICK TO PLAY")
        self.music_label.setVisible(bool(n))
        self.tunes.setVisible(bool(n))
        if n:
            row_h = max(self.tunes.sizeHintForRow(0), 22)
            self.tunes.setFixedHeight(min(n, 10) * row_h + 10)
            self.tunes.setCurrentItem(self.tunes.topLevelItem(0))

    def _fit_tree(self, max_rows=16):
        """Size the contents list to its rows (up to max_rows; it scrolls beyond that)."""
        rows, it = 0, self.tree.topLevelItem(0)
        while it is not None and rows < max_rows:
            rows += 1
            it = self.tree.itemBelow(it)
        row_h = self.tree.sizeHintForRow(0) if self.tree.topLevelItemCount() else 24
        self.tree.setFixedHeight(max(rows, 2) * max(row_h, 20) + 12)

    def _fill_tree(self, m, kids):
        bold = data_font(12)
        bold.setWeight(QFont.Weight.DemiBold)

        def mk(parent, name, size="", date="", is_dir=False):
            it = QTreeWidgetItem([name, size, date])
            it.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            it.setForeground(1, C["ink-muted"])
            it.setForeground(2, C["ink-muted"])
            if is_dir:
                it.setFont(0, bold)
            if parent is not None:
                parent.addChild(it)
            else:
                self.tree.addTopLevelItem(it)
            return it

        total = 0

        def add_files(parent, mid):
            nonlocal total
            nodes = {}
            rows = self.cat.db.execute(
                "SELECT path, size, date, is_dir FROM files WHERE media_id=? ORDER BY path", (mid,))
            for f in rows:
                total += 1
                parts = f["path"].split("/")
                up = parent
                for i in range(len(parts) - 1):
                    key = "/".join(parts[:i + 1])
                    if key not in nodes:
                        nodes[key] = mk(up, parts[i] + "/", is_dir=True)
                    up = nodes[key]
                if f["is_dir"]:
                    if f["path"] not in nodes:
                        nodes[f["path"]] = mk(up, parts[-1] + "/", "", (f["date"] or "")[:10], True)
                else:
                    mk(up, parts[-1], f"{f['size'] or 0:,}", (f["date"] or "")[:10])

        add_files(None, m["id"])
        for k in kids:
            node = mk(None, f"{k['inner_path']}  ({KIND_NAME.get(k['kind'], k['kind'])})", is_dir=True)
            node.setForeground(0, C["accent"])
            total += 1
            add_files(node, k["id"])
        return total

    def _show_picture(self, item):
        if item.pic and os.path.exists(item.pic):
            self.picture.set_picture(item.pic)
            if item.pic_origin == "cover":
                ident, _, title = item.pic_from.partition("|")
                self.pic_caption.setText(
                    f"The cover of the magazine it came with, from its scan on the "
                    f"<a href='{magcovers.DETAILS.format(id=ident)}'>Internet Archive</a> "
                    f"(“{_esc(title)}”). © its publisher; kept on this computer for your own use.")
            elif item.pic_origin == "online":
                path, _, name = item.pic_from.partition("|")
                kind = {"Named_Titles": "Title screen", "Named_Snaps": "Screenshot",
                        "Named_Boxarts": "Box art"}.get(path.split("/")[0], "Picture")
                self.pic_caption.setText(
                    f"{kind} from the <a href='https://github.com/{pictures.LR_REPO}'>"
                    f"libretro-thumbnails</a> collection, matched by the name "
                    f"“{_esc(name)}”. © its publisher; kept on this computer for your own use.")
            else:
                self.pic_caption.setText("Picture found on the disk: "
                                         + _esc(_breakable(item.pic_from)))
            self.picture.show()
            self.pic_caption.show()
        elif item.game:
            self.picture.hide()
            self.pic_caption.setText("No picture of this game on the disk. "
                                     "<a href='#online'>Find pictures online…</a>")
            self.pic_caption.show()
        else:
            self.picture.hide()
            self.pic_caption.hide()

    def show_in_folder(self):
        if not self.source:
            return
        target = self.source if os.path.isdir(self.source) else os.path.dirname(self.source)
        QDesktopServices.openUrl(QUrl.fromLocalFile(target))


# ---------------------------------------------------------------- scanning

class ScanStopped(Exception):
    pass


class RepairWorker(QThread):
    """Builds repaired copies one after another, with its own database connection."""
    step = Signal(int, int, str)          # done, total, the disk being repaired
    done = Signal(list, list)             # [repair.Result], [(plan, why it failed)]

    def __init__(self, db_path, plans, mark=True):
        super().__init__()
        self.db_path, self.plans, self.mark = db_path, plans, mark
        self.stop_wanted = False

    def run(self):
        cat = Catalogue(self.db_path)
        made, failed = [], []
        try:
            for i, p in enumerate(self.plans):
                if self.stop_wanted:
                    break
                self.step.emit(i, len(self.plans), f"#{p.number:04d} {p.source_file}")
                try:
                    made.append(repair.build(cat, p, mark=self.mark))
                except Exception as ex:
                    failed.append((p, str(ex)))
        finally:
            cat.db.close()
        self.done.emit(made, failed)


class FixAllDialog(QDialog):
    """Fix all…: every damaged disk TurboCAT can fix, what it would do, and a go-ahead."""

    def __init__(self, parent, plans, recheck, about):
        super().__init__(parent)
        self.setWindowTitle("Fix damaged disks")
        self.plans = plans
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 16)
        v.setSpacing(12)
        full = [p for p in plans if p.complete()]
        part = [p for p in plans if not p.complete()]
        head = QLabel("Fix these damaged disks?")
        head.setFont(ui_font(16, QFont.Weight.DemiBold))
        v.addWidget(head)
        intro = []
        if full:
            intro.append(f"<b>{len(full)}</b> can be rebuilt completely: every damaged file is on your "
                         "other disks.")
        if part:
            intro.append(f"<b>{len(part)}</b> can be rebuilt in part: some damaged files aren't anywhere "
                         "else, so those copies would still be missing files"
                         + (". They're unticked; tick any you want too." if full else
                            ", but have more working files than the originals."))
        if recheck:
            intro.append(f"<b>{len(recheck)}</b> will be read again, now that the helper program they "
                         "needed is installed.")
        lab = _wrap_label("<br>".join(intro), ui_font(13))
        lab.setTextFormat(Qt.TextFormat.RichText)
        lab.setFixedWidth(600)
        v.addWidget(lab)

        self.list = QListWidget()
        self.list.setMinimumHeight(220)
        for p in full + part:
            ok = len(p.usable())
            it = QListWidgetItem(f"#{p.number:04d}  {p.source_file}   —   {ok} of {len(p.lost)} "
                                 f"damaged file{'s' if len(p.lost) != 1 else ''} put back")
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            # partial ones are ticked only when there's nothing better: that's what was asked for
            it.setCheckState(Qt.CheckState.Checked if p.complete() or not full else Qt.CheckState.Unchecked)
            it.setToolTip("\n".join(
                f"{'✓' if x in p.usable() else '✗'} {x.path}"
                + (f"  from #{x.use.number:04d} {x.use.name}" if x in p.usable() else
                   "  (several different versions: left out)" if x.confidence == "unsure" else
                   "  (not on your other disks: left out)")
                for x in p.lost))
            it.setData(Qt.ItemDataRole.UserRole, p)
            self.list.addItem(it)
        v.addWidget(self.list)
        self.count = QLabel()
        self.count.setObjectName("muted")
        v.addWidget(self.count)
        self.about = about
        self.list.itemChanged.connect(lambda _=None: self._count())

        does = _wrap_label(
            "<b>What TurboCAT will do</b><br>"
            "• Make a <b>new</b> disk image for each ticked disk, with its damaged files put back. "
            "Your originals stay exactly as they are.<br>"
            "• Mark each one as repaired, not original: <i>[f TurboCAT]</i> in its name, and in the "
            "catalogue. Ones still missing files are also marked <i>[b]</i>.<br>"
            f"• Save them in {_esc(repair.REPAIRED_DIR)} and add them to the catalogue.<br>"
            "• Leave out any file with several different versions: hover over a disk to see each file.",
            ui_font(13))
        does.setTextFormat(Qt.TextFormat.RichText)
        does.setFixedWidth(600)
        v.addWidget(does)
        self.mark_box = QCheckBox("Also mark the disks themselves (recommended)")
        self.mark_box.setChecked(True)
        self.mark_box.setToolTip(f"Adds a {repair.MARKER} text file saying what was done, and a file note "
                                 "on each restored file. Both show on a real Amiga.")
        v.addWidget(self.mark_box)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        self.go = QPushButton("Fix them")
        self.go.setObjectName("primary")
        self.go.setDefault(True)
        cancel.clicked.connect(self.reject)
        self.go.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(self.go)
        v.addLayout(row)
        self.recheck = recheck
        self._count()

    def chosen(self):
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.CheckState.Checked]

    def mark(self):
        return self.mark_box.isChecked()

    def _count(self):
        n = len(self.chosen())
        self.count.setText(f"Ticked: {n} of {self.list.count()} · {self.about(n)} · it runs with a "
                           "progress bar, and Stop keeps the copies already made")
        self.go.setEnabled(bool(n or self.recheck))
        self.go.setToolTip("" if self.go.isEnabled() else "Tick at least one disk above")


class ScanWorker(QThread):
    """Runs a scan or rescan with its own database connection, off the window's thread."""
    line = Signal(str)
    step = Signal(str, int, int, object, object, str)   # phase, done, total, bytes done, bytes total, path
    big_found = Signal(list, float)     # big archives to ask about: [(path, kind, size)], bytes a second
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, db_path, folders=None, files=None):
        super().__init__()
        self.db_path = db_path
        self.folders = folders       # None = rescan everything scanned before
        self.files = files           # recheck just these items' files (and their folders)
        self.stop_wanted = False
        self.big_answer = []
        self._answered = threading.Event()

    def _confirm_big(self, big, rate):
        """Ask the window which big archives to read, and wait for the answer."""
        self._answered.clear()
        self.big_answer = []
        self.big_found.emit(big, rate)
        while not self._answered.wait(0.2):
            if self.stop_wanted:
                raise ScanStopped()
        return self.big_answer

    def answer_big(self, paths):
        self.big_answer = list(paths)
        self._answered.set()

    def _progress(self, text):
        self.line.emit(text)
        if self.stop_wanted:
            raise ScanStopped()

    def _step(self, phase, done, total, done_bytes, total_bytes, path):
        self.step.emit(phase, done, total, done_bytes, total_bytes, path)
        if self.stop_wanted:
            raise ScanStopped()

    def run(self):
        cat = None
        try:
            cat = Catalogue(self.db_path)
            if self.files is not None:
                s = recheck(self.files, cat, progress=self._progress, step=self._step,
                            confirm_big=self._confirm_big)
            elif self.folders is None:
                s = rescan_all(cat, progress=self._progress, step=self._step,
                               confirm_big=self._confirm_big)
            else:
                s = scan(self.folders, cat, progress=self._progress, step=self._step,
                         confirm_big=self._confirm_big)
                s["removed"] = []
            self.done.emit(s)
        except ScanStopped:
            cat.commit()
            self.done.emit({"stopped": True})
        except Exception as ex:          # report, don't take the window down
            self.failed.emit(str(ex))
        finally:
            if cat is not None:
                cat.db.close()



# ---------------------------------------------------------------- music

class ModuleStream(QIODevice):
    """Sound for Qt, rendered by libopenmpt as Qt asks for it."""

    def __init__(self, module, rate):
        super().__init__()
        self.module, self.rate, self.done = module, rate, False
        self.open(QIODevice.OpenModeFlag.ReadOnly)

    def readData(self, maxlen):
        if self.done or self.module.mod is None:
            return b""
        pcm = self.module.render(max(1, min(maxlen // 4, 8192)), self.rate)
        if not pcm:
            self.done = True
        return pcm

    def writeData(self, data):
        return -1

    def bytesAvailable(self):
        return 0 if self.done else 1 << 16

    def isSequential(self):
        return True


class ModulePlayer(QObject):
    """Plays one module at a time through Qt Multimedia (PipeWire, PulseAudio, Windows, macOS)."""
    ended = Signal()

    def __init__(self):
        super().__init__()
        self.sink = self.stream = self.module = None
        self.state = "stopped"          # stopped / playing / paused

    def play(self, data):
        from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioSink, QMediaDevices
        self.stop()
        device = QMediaDevices.defaultAudioOutput()
        fmt = QAudioFormat()
        fmt.setChannelCount(2)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        fmt.setSampleRate(music.RATE)
        if not device.isFormatSupported(fmt):
            fmt.setSampleRate(device.preferredFormat().sampleRate() or 44100)
        module = music.open_module(data, fmt.sampleRate())
        self.module = module
        self.stream = ModuleStream(module, fmt.sampleRate())
        self.sink = QAudioSink(device, fmt, self)
        self.sink.setBufferSize(fmt.sampleRate() * 4 // 5)          # about 0.2 s
        self._idle = QAudio.State.IdleState
        self.sink.stateChanged.connect(self._state_changed)
        self.sink.start(self.stream)
        self.state = "playing"
        return module

    def _state_changed(self, st):
        # Idle after the stream has run dry means the tune has finished.
        if st == self._idle and self.stream is not None and self.stream.done:
            self.state = "stopped"
            QTimer.singleShot(0, self.ended.emit)

    def pause(self):
        if self.sink and self.state == "playing":
            self.sink.suspend()
            self.state = "paused"

    def resume(self):
        if self.sink and self.state == "paused":
            self.sink.resume()
            self.state = "playing"

    def stop(self):
        if self.sink:
            self.sink.stateChanged.disconnect(self._state_changed)
            self.sink.stop()
            self.sink.deleteLater()
        if self.stream:
            self.stream.close()
        if self.module:
            self.module.close()
        self.sink = self.stream = self.module = None
        self.state = "stopped"

    def position(self):
        return self.sink.processedUSecs() / 1e6 if self.sink else 0.0


class PlayerBar(QFrame):
    """'Now playing' strip above the status line; music carries on while you browse."""

    def __init__(self, cat):
        super().__init__()
        self.cat = cat
        self.setObjectName("playerBar")
        self.player = ModulePlayer()
        self.player.ended.connect(self._ended)
        self.playlist, self.index, self.label, self.labels = [], 0, "", None
        h = QHBoxLayout(self)
        h.setContentsMargins(24, 8, 24, 8)
        h.setSpacing(12)
        note = QLabel()
        note.setPixmap(icon("music", 24))
        self.what = QLabel()
        self.what.setFont(ui_font(13, QFont.Weight.DemiBold))
        self.what.setMinimumWidth(40)
        self.what.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.time = QLabel()
        self.time.setObjectName("muted")
        self.time.setFont(data_font(12))
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 1000)
        self.bar.setFixedWidth(160)
        self.pause_btn = QPushButton("Pause")
        self.next_btn = QPushButton("Next")
        self.stop_btn = QPushButton("Stop")
        for b in (self.pause_btn, self.next_btn, self.stop_btn):
            b.setObjectName("small")
            b.setFont(ui_font(13, QFont.Weight.DemiBold))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pause_btn.clicked.connect(self.toggle)
        self.next_btn.clicked.connect(self.next)
        self.stop_btn.clicked.connect(self.stop)
        h.addWidget(note)
        h.addWidget(self.what, 1)
        h.addWidget(self.bar)
        h.addWidget(self.time)
        h.addWidget(self.pause_btn)
        h.addWidget(self.next_btn)
        h.addWidget(self.stop_btn)
        self.timer = QTimer(self, interval=250)
        self.timer.timeout.connect(self._tick)
        self.duration = 0.0
        self.hide()

    def play(self, rows, index, label="", labels=None):
        ok, why = music.available()
        self.show()
        if not ok:
            self.what.setText(f"Can't play music: {why} · Help › Check setup")
            self.time.setText("")
            return
        self.playlist, self.index, self.label = list(rows), index, label
        self.labels = labels
        self._start()

    def _start(self):
        r = self.playlist[self.index]
        name = r["file"].rsplit("/", 1)[-1]
        title = r["title"] or name
        try:
            data = pictures.module_data(self.cat, r)
            mod = self.player.play(data)
        except Exception as ex:
            self.what.setText(f"Can't play {title}: {ex}")
            self.time.setText("")
            return
        self.duration = mod.duration
        kind = mod.meta("type_long") or r["fmt"]
        artist = mod.meta("artist")
        bits = [f"{title}"] + ([f"by {artist}"] if artist else []) + [kind]
        if len(self.playlist) > 1:
            bits.append(f"{self.index + 1} of {len(self.playlist)}")
        label = self.labels[self.index] if self.labels else self.label
        if label:
            bits.append(label)
        self.what.setText(" · ".join(bits))
        self.what.setToolTip(r["shown"])
        self.pause_btn.setText("Pause")
        self.next_btn.setEnabled(len(self.playlist) > 1)
        self.timer.start()
        self._tick()

    def _tick(self):
        pos = min(self.player.position(), self.duration or 0)
        self.time.setText(f"{music.fmt_time(pos)} / {music.fmt_time(self.duration)}")
        self.bar.setValue(int(1000 * pos / self.duration) if self.duration else 0)

    def toggle(self):
        if self.player.state == "playing":
            self.player.pause()
            self.pause_btn.setText("Play")
        elif self.player.state == "paused":
            self.player.resume()
            self.pause_btn.setText("Pause")
        elif self.playlist:
            self._start()

    def _next_playable(self, wrap):
        n = len(self.playlist)
        for step in range(1, n + 1):
            i = self.index + step
            if i >= n and not wrap:
                return None
            if self.playlist[i % n]["fmt"] in music.PLAYABLE:
                return i % n
        return None

    def next(self):
        i = self._next_playable(wrap=True)
        if i is not None:
            self.index = i
            self._start()

    def _ended(self):
        i = self._next_playable(wrap=False)       # carry on through the disk's tunes
        if i is not None:
            self.index = i
            self._start()
            return
        self.timer.stop()
        self.pause_btn.setText("Play")
        self.index = 0
        self._tick()

    def stop(self):
        self.player.stop()
        self.timer.stop()
        self.hide()


# ---------------------------------------------------------------- pictures

class TurboViewWorker(QThread):
    """Rewrite TurboView's catalogue files, off the window's thread (it takes a few seconds)."""

    def __init__(self, db_path):
        super().__init__()
        self.db_path = db_path
        self.stop_wanted = False

    def run(self):
        try:
            cat = Catalogue(self.db_path)
            folder = cat.get_meta("turboview_dir") or turboview.default_folder()
            turboview.export(cat, load_items(cat), folder)
        except Exception:
            pass


class PictureWorker(QThread):
    """Look for icons and pictures on items not yet looked at; optionally online too."""
    progress = Signal(str, int, int, str)      # phase, done, total, what it is looking at
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, db_path, online=False):
        super().__init__()
        self.db_path, self.online = db_path, online
        self.stop_wanted = False

    def run(self):
        try:
            cat = Catalogue(self.db_path)
            stop = lambda: self.stop_wanted
            def name(m):
                try:
                    return os.path.basename(m["source"])
                except Exception:
                    return ""

            res = {}
            # The TOSEC list of Amiga disks, if the user agreed to it (once, then every two months).
            tosec = cat.get_meta(identify.TOSEC_CONSENT, False)
            if (tosec and (not identify.have_tosec() or identify.tosec_is_old())) or (
                    not tosec and cat.get_meta(identify.CONSENT, False)
                    and (not identify.have_list() or identify.list_is_old())):
                try:
                    self.progress.emit("identify", 0, 0, "tosec" if tosec else "")
                    fetch = identify.download_tosec if tosec else identify.download
                    fetch(stop, lambda d, t: self.progress.emit("identify", d // 1024, t // 1024,
                                                                "tosec" if tosec else ""))
                    res["identify_fetched"] = True
                except pictures.Stopped:
                    pass
                except Exception as ex:
                    res["identify_error"] = str(ex)
            known_full = identify.for_catalogue(cat)
            known = {k: v[0] for k, v in known_full.items()}
            res["identified"] = len(known)
            res["disk"] = pictures.build(
                cat, lambda i, n, m, inner=None: self.progress.emit(
                    "disk", i, n, name(m)) if inner is None else self.progress.emit(
                    "disk-inside", inner[0], inner[1], f"{name(m)}\t{inner[2]}"), stop)
            if not self.stop_wanted:
                res["lengths"] = pictures.measure_music(
                    cat, lambda i, n, m: self.progress.emit("lengths", i, n, ""), stop)
            if self.online and not self.stop_wanted:
                res["online"] = pictures.lookup_online(
                    cat, lambda i, n, m: self.progress.emit("online", i, n, name(m)), stop, known=known)
            if self.online and not self.stop_wanted:
                # magazine covers for coverdisks, from the scans on the Internet Archive
                issues = []
                for m in cat.db.execute("SELECT id, source FROM media WHERE parent_id IS NULL"):
                    cd = coverdisks.recognise(m["source"], known_full.get(m["id"]))
                    if cd is not None and cd.magazine and cd.issue:
                        issues.append((cd.magazine, magcovers.issue_key(cd.issue)))
                if issues:
                    res["covers"] = magcovers.lookup(
                        cat, issues, lambda i, n, w: self.progress.emit("covers", i, n, w), stop)
            if not self.stop_wanted:          # keep the Amiga's copy of the catalogue up to date
                try:
                    folder = cat.get_meta("turboview_dir") or turboview.default_folder()
                    turboview.install(folder)
                    res["turboview"] = turboview.export(cat, load_items(cat), folder)
                except Exception as ex:
                    res["turboview_error"] = str(ex)
            self.done.emit(res)
        except Exception as ex:
            self.failed.emit(str(ex))


# ---------------------------------------------------------------- emulators

class PlayDialog(QDialog):
    """Confirm what will be started, and in which emulator and Amiga, then start it."""

    def __init__(self, parent, cat, ids, emulators):
        super().__init__(parent)
        self.cat, self.emulators = cat, emulators
        self.setObjectName("dialog")
        self.setWindowTitle("Play in emulator")
        self.setMinimumWidth(600)
        self.files, self.whdload, skipped, names = emulator.disk_files(cat, ids)
        self.roms = emulator.find_kickstarts()
        guess = emulator.guess_model(names)
        # A disk with no boot block was opened from Workbench: start a Workbench disk first
        self.boots = True if self.whdload or not self.files else emulator.first_disk_boots(cat, ids)
        self.workbenches = emulator.find_workbenches(cat) if self.files and not self.whdload else []

        v = QVBoxLayout(self)
        v.setContentsMargins(24, 22, 24, 20)
        v.setSpacing(12)
        title = names[0] if names else "Nothing to play"
        head = QLabel(_esc(re.split(r"\s*[\(\[]", title, maxsplit=1)[0]) if names else title)
        head.setFont(ui_font(20, QFont.Weight.Bold))
        v.addWidget(head)
        self.what = _wrap_label("", ui_font(13), "muted")
        v.addWidget(self.what)
        self.disk_list = None
        if self.files:
            lst = self.disk_list = QListWidget()
            lst.setObjectName("diskList")
            lst.setFont(ui_font(13))
            lst.setIconSize(QSize(16, 16))
            lst.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
            lst.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            lst.setTextElideMode(Qt.TextElideMode.ElideMiddle)
            lst.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            v.addWidget(lst)
        self.wb_check = self.wb_box = None
        if self.files and not self.whdload:
            if self.workbenches:
                row = QHBoxLayout()
                row.setSpacing(10)
                self.wb_check = QCheckBox("Start Workbench first")
                self.wb_check.setFont(ui_font(13, QFont.Weight.DemiBold))
                self.wb_check.setToolTip("Workbench starts from DF0: and these disks go in DF1: (and the "
                                         "disk swapper), so their icons are on the Workbench screen. For "
                                         "disks that were opened from Workbench rather than started.")
                self.wb_box = QComboBox()
                self.wb_box.setFont(ui_font(13))
                for mid, label, major in self.workbenches:
                    self.wb_box.addItem(label, (mid, major))
                row.addWidget(self.wb_check)
                row.addWidget(self.wb_box, 1)
                v.addLayout(row)
                self.wb_check.setChecked(self.boots is False)
                self.wb_check.toggled.connect(self._wb_changed)
                self.wb_box.currentIndexChanged.connect(self._wb_changed)
            if self.boots is False:
                v.addWidget(_wrap_label(
                    "This disk doesn't start by itself (it has no boot block): it was opened from "
                    "Workbench. " + ("TurboCAT starts Workbench first, with it in DF1: — open it by "
                                     "double-clicking its icon." if self.workbenches else
                                     "No Workbench disk is catalogued. Scan the folder with your "
                                     "Workbench disks (from Amiga Forever, or your own) and Play will "
                                     "start Workbench first."), ui_font(12), "muted"))
        if skipped:
            v.addWidget(_wrap_label("Left out: " + "; ".join(f"{n} ({w})" for n, w in skipped[:4]),
                                    ui_font(12), "muted"))

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        grid.addWidget(QLabel("Emulator"), 0, 0)
        self.emu_box = QComboBox()
        names_ = {"amiberry": "Amiberry", "fs-uae": "FS-UAE"}
        for key in ("amiberry", "fs-uae"):
            if key in emulators:
                self.emu_box.addItem(names_[key], key)
        last = cat.get_meta("emulator", "amiberry")
        if self.whdload:                               # only Amiberry boots WHDLoad archives itself
            i = self.emu_box.findData("amiberry")
            for j in reversed(range(self.emu_box.count())):
                if j != i:
                    self.emu_box.removeItem(j)
        self.emu_box.setCurrentIndex(max(0, self.emu_box.findData(last)))
        grid.addWidget(self.emu_box, 0, 1)
        grid.addWidget(QLabel("Amiga"), 1, 0)
        self.model_box = QComboBox()
        labels = {"A500": "A500 (Kickstart 1.3, OCS)", "A600": "A600 (Kickstart 2.05, ECS)",
                  "A1200": "A1200 (Kickstart 3.1, AGA)"}
        for mdl in emulator.MODELS:
            self.model_box.addItem(labels[mdl] + ("   — suggested" if mdl == guess else ""), mdl)
        self.model_box.setCurrentIndex(emulator.MODELS.index(guess))
        grid.addWidget(self.model_box, 1, 1)
        grid.addWidget(QLabel("Screen"), 2, 0)
        self.display_box = QComboBox()
        size = QGuiApplication.primaryScreen().size() if QGuiApplication.primaryScreen() else None
        for key, label in emulator.DISPLAYS.items():
            if key == "fullscreen" and size is not None:
                label += f" ({size.width()} × {size.height()})"
            self.display_box.addItem(label, key)
        self.display_box.setCurrentIndex(max(0, self.display_box.findData(
            cat.get_meta("emulator_display", "fullscreen"))))
        self.display_box.setToolTip("How big the emulator shows the Amiga (also used by TurboView). "
                                    "The picture keeps the Amiga's shape. In Amiberry, F12 opens its "
                                    "settings, where you can quit or leave full screen.")
        grid.addWidget(self.display_box, 2, 1)
        for w in (self.emu_box, self.model_box, self.display_box):
            w.setFont(ui_font(13))
            w.setMinimumHeight(36)
        for r in range(3):
            grid.itemAtPosition(r, 0).widget().setFont(ui_font(13, QFont.Weight.DemiBold))
        grid.setColumnStretch(1, 1)
        v.addLayout(grid)
        self.rom_note = _wrap_label("", ui_font(12), "muted")
        v.addWidget(self.rom_note)
        self.model_box.currentIndexChanged.connect(self._rom_text)
        self._rom_text()
        self._wb_changed()

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.go = QPushButton("Start")
        self.go.setObjectName("primary")
        self.go.setDefault(True)
        self.go.clicked.connect(self.start)
        self.go.setEnabled(bool(self.files or self.whdload))
        for b in (cancel, self.go):
            b.setFont(ui_font(14, QFont.Weight.DemiBold))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            btns.addWidget(b)
        v.addLayout(btns)

    def _drive_files(self):
        """The files in drive order: Workbench first if it is to start first."""
        if self.wb_check is not None and self.wb_check.isChecked():
            return ["(Workbench)"] + self.files
        return list(self.files)

    def _wb_changed(self, *_):
        files = self._drive_files()
        wb = files[:1] == ["(Workbench)"]
        if self.whdload:
            what = "WHDLoad game, started by Amiberry's WHDLoad booter"
        elif wb:
            what = ("Workbench in DF0:, " + ("the disk in DF1:" if len(self.files) == 1 else
                    "the first disk in DF1:, all of them in the disk swapper"))
        else:
            n = len(self.files)
            what = (f"{n} disk{'s' if n != 1 else ''}: the first in DF0:"
                    + (", the second in DF1:, all of them in the disk swapper" if n > 1 else ""))
        self.what.setText(what)
        if self.wb_box is not None:
            self.wb_box.setEnabled(wb)
        if wb:
            # Workbench 3.1 needs Kickstart 3.1: move up to an Amiga that has it
            major = self.wb_box.currentData()[1]
            mdl = emulator.model_for_workbench(major, self.model_box.currentData())
            self.model_box.setCurrentIndex(emulator.MODELS.index(mdl))
        lst = self.disk_list
        if lst is None:
            return
        lst.clear()
        for i, f in enumerate(files):
            drive = f"DF{i}:  " if i < 2 else "swap:  "
            name = self.wb_box.currentText().split("  ·  ")[0] if f == "(Workbench)" else os.path.basename(f)
            it = QListWidgetItem(drive + name)
            it.setIcon(QIcon(icon("disk", 16)))
            it.setToolTip(self.wb_box.currentText() if f == "(Workbench)" else f)
            lst.addItem(it)
        lst.setFixedHeight(min(len(files), 6) * (max(lst.sizeHintForRow(0), 20) + 6) + 12)

    def _rom_text(self):
        mdl = self.model_box.currentData()
        rom = self.roms.get(mdl)
        self.rom_note.setText(f"Kickstart: {rom}" if rom else
                              "No matching Kickstart ROM found; the emulator will use its own "
                              "choice (or AROS). Help › Check setup says where to get one.")

    def start(self):
        emu = self.emu_box.currentData()
        mdl = self.model_box.currentData()
        display = self.display_box.currentData()
        self.cat.set_meta("emulator", emu)
        self.cat.set_meta("emulator_display", display)
        files = self.files
        if self.wb_check is not None and self.wb_check.isChecked():
            try:
                files = [emulator.workbench_file(self.cat, self.wb_box.currentData()[0])] + files
            except Exception as ex:
                QMessageBox.warning(self, "Play in emulator", f"The Workbench disk couldn't be read: {ex}")
                return
        cmd = emulator.command(emu, self.emulators[emu], mdl, self.roms.get(mdl), files,
                               self.whdload, display=display, fast_floppy=files is not self.files)
        try:
            emulator.launch(cmd)
        except OSError as ex:
            QMessageBox.warning(self, "Play in emulator", f"The emulator could not be started: {ex}")
            return
        self.accept()


# ---------------------------------------------------------------- Gotek

def _mb(n):
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{n / 1e6:.1f} MB"


class CopyWorker(QThread):
    progress = Signal(int, int, str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, db_path, disks, dest, numbered):
        super().__init__()
        self.db_path, self.disks, self.dest, self.numbered = db_path, disks, dest, numbered
        self.stop_wanted = False

    def run(self):
        try:
            cat = Catalogue(self.db_path)
            result = gotek.copy_disks(
                cat, self.disks, self.dest, self.numbered,
                progress=lambda i, n, d: self.progress.emit(i, n, d.name if d else ""),
                stop=lambda: self.stop_wanted)
            self.done.emit(result)
        except Exception as ex:
            self.failed.emit(str(ex))


class GotekDialog(QDialog):
    """Choose a USB stick (or folder) and copy the chosen floppies to it as ADF files."""

    CHOOSE = "__choose__"

    def __init__(self, parent, cat, db_path, top_ids):
        super().__init__(parent)
        self.cat, self.db_path = cat, db_path
        self.setObjectName("dialog")
        self.setWindowTitle("Copy to Gotek stick")
        self.setMinimumWidth(620)
        self.plan = gotek.plan(cat, top_ids)
        self.worker = None
        self.dest = None

        v = QVBoxLayout(self)
        v.setContentsMargins(24, 22, 24, 20)
        v.setSpacing(14)

        n = len(self.plan.disks)
        head = QLabel(f"Copy {n:,} disk{'s' if n != 1 else ''} to a Gotek stick" if n
                      else "Nothing to copy")
        head.setFont(ui_font(20, QFont.Weight.Bold))
        v.addWidget(head)
        sub = _wrap_label("", ui_font(13), "muted")
        if n:
            sub.setText(f"{_mb(self.plan.total)} as plain ADF files, unpacked from ZIP, LHA, DMS "
                        "or ADZ where needed. The stick must be FAT32 formatted.")
        else:
            sub.setText("None of the chosen items holds a floppy disk image a Gotek can use.")
        v.addWidget(sub)

        self.list = QListWidget()
        self.list.setObjectName("diskList")
        self.list.setFont(ui_font(13))
        self.list.setIconSize(QSize(16, 16))
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        bad = 0
        for d in self.plan.disks:
            it = QListWidgetItem(f"#{d.number:04d}  {d.name}")
            if d.status == "error":
                bad += 1
                it.setIcon(QIcon(icon("problem", 16)))
                it.setToolTip("Has problems, but will be copied as it is:\n" + "\n".join(d.problems[:5]))
            elif d.status == "warning":
                it.setIcon(QIcon(icon("warning", 16)))
            else:
                it.setIcon(QIcon(icon("disk", 16)))
            self.list.addItem(it)
        for num, name, why in self.plan.skipped:
            it = QListWidgetItem(f"#{num or 0:04d}  {name}  —  left out: {why}")
            it.setForeground(C["ink-muted"])
            it.setToolTip(why)
            self.list.addItem(it)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        rows = min(self.list.count(), 8)
        row_h = self.list.sizeHintForRow(0) if self.list.count() else 26
        self.list.setFixedHeight(max(1, rows) * (row_h + 6) + 12)
        v.addWidget(self.list)
        notes = []
        if self.plan.skipped:
            k = len(self.plan.skipped)
            notes.append(f"{k:,} left out (greyed above): hover for the reason.")
        if bad:
            notes.append(f"{bad:,} with problems will be copied as they are; they may not load.")
        if notes:
            v.addWidget(_wrap_label(" ".join(notes), ui_font(12), "muted"))

        # Where to
        where = QLabel("Copy to")
        where.setFont(ui_font(13, QFont.Weight.DemiBold))
        v.addWidget(where)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.dest_box = QComboBox()
        self.dest_box.setFont(ui_font(13))
        self.dest_box.setMinimumHeight(40)
        self.dest_box.activated.connect(self._dest_chosen)
        look = QPushButton("Look again")
        look.setFont(ui_font(13, QFont.Weight.DemiBold))
        look.setToolTip("Look again for USB sticks (after plugging one in)")
        look.clicked.connect(self._fill_dests)
        row.addWidget(self.dest_box, 1)
        row.addWidget(look)
        v.addLayout(row)

        names = QLabel("File names")
        names.setFont(ui_font(13, QFont.Weight.DemiBold))
        v.addWidget(names)
        self.by_name = QRadioButton("Disk names, e.g. “Arcade Pool (1994)(Team 17).adf”, for FlashFloppy firmware")
        self.by_number = QRadioButton("Numbered DSKA0000.ADF, DSKA0001.ADF … for stock Gotek or HxC firmware")
        for r in (self.by_name, self.by_number):
            r.setFont(ui_font(13))
            v.addWidget(r)
        numbered = bool(cat.get_meta("gotek_numbered", False))
        (self.by_number if numbered else self.by_name).setChecked(True)

        self.space = _wrap_label("", ui_font(12), "muted")
        v.addWidget(self.space)

        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.hide()
        v.addWidget(self.bar)
        self.status = _wrap_label("", ui_font(13))
        self.status.hide()
        v.addWidget(self.status)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self.open_btn = QPushButton("Open folder")
        self.open_btn.clicked.connect(lambda: self.dest and QDesktopServices.openUrl(QUrl.fromLocalFile(self.dest)))
        self.open_btn.hide()
        self.close_btn = QPushButton("Cancel")
        self.close_btn.clicked.connect(self._close)
        self.copy_btn = QPushButton("Copy")
        self.copy_btn.setObjectName("primary")
        self.copy_btn.setDefault(True)
        self.copy_btn.clicked.connect(self.start)
        for b in (self.open_btn, self.close_btn, self.copy_btn):
            b.setFont(ui_font(14, QFont.Weight.DemiBold))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            btns.addWidget(b)
        v.addLayout(btns)
        self._fill_dests()
        if not n:
            self.copy_btn.setEnabled(False)

    # destination
    def _fill_dests(self):
        last = self.cat.get_meta("gotek_dest", "")
        keep = self.dest
        self.dest_box.clear()
        for mnt, label, free in gotek.find_sticks():
            self.dest_box.addItem(f"{label} — USB stick, {_mb(free)} free", mnt)
        if last and os.path.isdir(last) and self.dest_box.findData(last) < 0:
            self.dest_box.addItem(f"{last} (used last time)", last)
        if keep and os.path.isdir(keep) and self.dest_box.findData(keep) < 0:
            self.dest_box.addItem(keep, keep)
        self.dest_box.addItem("Choose a folder…", self.CHOOSE)
        for want in (keep, last):
            i = self.dest_box.findData(want) if want else -1
            if i >= 0:
                self.dest_box.setCurrentIndex(i)
                break
        else:
            self.dest_box.setCurrentIndex(0)
        self._dest_chosen(self.dest_box.currentIndex())

    def _dest_chosen(self, index):
        data = self.dest_box.itemData(index)
        if data == self.CHOOSE:
            folder = QFileDialog.getExistingDirectory(self, "Copy the disks to this folder",
                                                      self.dest or os.path.expanduser("~"))
            if folder:
                self.dest = folder
                self._fill_dests()
                return
            if self.dest is None:
                self.space.setText("No USB stick found. Plug one in and click Look again, "
                                   "or choose a folder.")
                self.copy_btn.setEnabled(False)
                return
            i = self.dest_box.findData(self.dest)
            self.dest_box.setCurrentIndex(max(i, 0))
            data = self.dest
        self.dest = data
        self._check_space()

    def _check_space(self):
        if not self.dest or not self.plan.disks:
            self.copy_btn.setEnabled(False)
            return
        try:
            free = shutil.disk_usage(self.dest).free
        except OSError:
            self.space.setText("That folder can't be read.")
            self.copy_btn.setEnabled(False)
            return
        if free < self.plan.total:
            self.space.setText(f"Not enough room: the disks need {_mb(self.plan.total)} and "
                               f"there is {_mb(free)} free.")
            self.copy_btn.setEnabled(False)
        else:
            self.space.setText(f"Needs {_mb(self.plan.total)}; {_mb(free)} free there.")
            self.copy_btn.setEnabled(True)

    # copying
    def start(self):
        numbered = self.by_number.isChecked()
        self.cat.set_meta("gotek_dest", self.dest)
        self.cat.set_meta("gotek_numbered", numbered)
        for w in (self.copy_btn, self.dest_box, self.by_name, self.by_number):
            w.setEnabled(False)
        self.close_btn.setText("Stop")
        self.bar.setRange(0, len(self.plan.disks))
        self.bar.setValue(0)
        self.bar.show()
        self.status.show()
        self.worker = CopyWorker(self.db_path, self.plan.disks, self.dest, numbered)
        self.worker.progress.connect(self._progress)
        self.worker.done.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _progress(self, i, n, name):
        self.bar.setValue(i)
        if name:
            self.status.setText(f"Copying {i + 1:,} of {n:,}: {_breakable(name)}")

    def _done(self, result):
        copied, failed, same = result
        self.worker = None
        bits = [f"Copied {len(copied):,} disk{'s' if len(copied) != 1 else ''} to {self.dest}."]
        if same:
            bits.append(f"{len(same):,} {'were' if len(same) != 1 else 'was'} already there.")
        if failed:
            bits.append(f"{len(failed):,} failed: " + "; ".join(
                f"{d.name} ({why})" for d, why in failed[:3]) + (" …" if len(failed) > 3 else ""))
        if copied and gotek.is_removable(self.dest):
            bits.append("Eject the stick from the file manager before you unplug it.")
        self.status.setText(_breakable(" ".join(bits)))
        self.bar.setValue(self.bar.maximum())
        self.close_btn.setText("Close")
        self.open_btn.show()

    def _failed(self, err):
        self.worker = None
        self.status.setText(f"Copy failed: {err}")
        self.close_btn.setText("Close")

    def _close(self):
        if self.worker is not None:
            self.worker.stop_wanted = True
            self.close_btn.setEnabled(False)
            self.worker.wait(30000)
            self.close_btn.setEnabled(True)
            return
        self.accept()

    def reject(self):          # Esc or the window's close button
        if self.worker is not None:
            self._close()
            return
        super().reject()


class ScanFoldersDialog(QDialog):
    """File > Scan folders…: a folder tree with tick boxes, like a cloud drive's selective sync.
    Ticked folders are scanned with everything in them; unticked ones are left out; a half tick
    means some folders inside are left out. Nothing changes until Save; files are never touched."""

    PATH = Qt.ItemDataRole.UserRole

    def __init__(self, parent, cat):
        super().__init__(parent)
        self.setWindowTitle("Scan folders")
        self.resize(720, 620)
        self.cat = cat
        self.old = cat.selection()
        self.sel = cat.selection()
        self.sources = [folders.norm(s) for s in cat.top_sources()]
        self.changed = False
        self.rescan = False
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 16)
        v.setSpacing(10)
        head = QLabel("Choose the folders TurboCAT scans")
        head.setFont(ui_font(16, QFont.Weight.DemiBold))
        v.addWidget(head)
        note = _wrap_label("Ticked folders are scanned, with every folder inside them. Untick a folder to "
                           "leave it out. A half tick means some folders inside are left out.",
                           ui_font(13), "muted")
        note.setToolTip("Changing this never moves, changes or deletes your files.")
        v.addWidget(note)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Folder", "In catalogue"])
        self.tree.setUniformRowHeights(True)
        hdr = self.tree.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        v.addWidget(self.tree, 1)
        self.summary = QLabel()
        self.summary.setObjectName("muted")
        v.addWidget(self.summary)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setDefault(True)
        save.clicked.connect(self._save)
        row.addWidget(cancel)
        row.addWidget(save)
        v.addLayout(row)

        for path, label in self._tops():
            self.tree.addTopLevelItem(self._node(path, label))
        self.tree.itemExpanded.connect(self._expand)
        self.tree.itemChanged.connect(self._clicked)
        for p in self.sel.roots + self.sel.skips:
            self._reveal(p)
        self._paint()

    # ---- the tree
    def _tops(self):
        """Home, then mounted drives (USB sticks, other disks, network shares), then any scanned
        folder outside those (an unplugged drive shows as not found)."""
        home = folders.norm("~")
        tops = [(home, f"Home ({home})")]
        for vol in QStorageInfo.mountedVolumes():
            p = folders.norm(vol.rootPath())
            win_drive = len(p) <= 3 and p[1:2] == ":"
            if not (win_drive or p.startswith(("/media/", "/mnt/", "/run/media/", "/Volumes/"))):
                continue
            if not vol.isValid() or not vol.isReady() or any(folders.within(p, t) for t, _ in tops):
                continue
            tops.append((p, f"{vol.displayName() or os.path.basename(p) or p} ({p})"))
        for p in self.sel.roots + self.sel.skips:
            if not any(folders.within(p, t) for t, _ in tops):
                tops.append((p, p + ("" if os.path.exists(p) else "   (not found: unplugged or moved?)")))
        return tops

    @staticmethod
    def _subfolders(path):
        try:
            with os.scandir(path) as it:
                names = [e.name for e in it if e.is_dir(follow_symlinks=False)
                         and not e.name.startswith((".", "$"))]
        except OSError:
            return []
        return sorted(names, key=str.lower)

    def _node(self, path, label=None):
        it = QTreeWidgetItem([label or os.path.basename(path) or path, ""])
        it.setData(0, self.PATH, path)
        it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        it.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        n = sum(1 for s in self.sources if folders.within(s, path))
        it.setText(1, f"{n:,}" if n else "")
        if os.path.isdir(path) and readers.looks_like_amiga_folder(path):
            it.setToolTip(0, "An Amiga folder: catalogued as one disk, with everything in it")
        elif self._subfolders(path):
            it.addChild(QTreeWidgetItem([""]))        # placeholder until opened
        return it

    def _expand(self, item):
        if item.childCount() == 1 and item.child(0).data(0, self.PATH) is None:
            item.takeChild(0)
            path = item.data(0, self.PATH)
            self.tree.blockSignals(True)
            for name in self._subfolders(path):
                item.addChild(self._node(os.path.join(path, name)))
            self.tree.blockSignals(False)
            self._paint(item)

    def _reveal(self, path):
        """Open the tree down to this folder, so the ticks that matter are in view."""
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            while it is not None and folders.inside(path, it.data(0, self.PATH)):
                it.setExpanded(True)
                nxt = None
                for j in range(it.childCount()):
                    c = it.child(j)
                    cp = c.data(0, self.PATH)
                    if cp and folders.within(path, cp):
                        nxt = c
                        break
                it = nxt

    def _items(self, top=None):
        stack = [top] if top else [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            it = stack.pop()
            if it.data(0, self.PATH):
                yield it
            stack.extend(it.child(j) for j in range(it.childCount()))

    def _paint(self, top=None):
        marks = {"on": Qt.CheckState.Checked, "part": Qt.CheckState.PartiallyChecked,
                 "off": Qt.CheckState.Unchecked}
        self.tree.blockSignals(True)
        for it in self._items(top):
            it.setCheckState(0, marks[self.sel.state(it.data(0, self.PATH))])
        self.tree.blockSignals(False)
        gone = len(self._gone())
        n = len(self.sel.roots)
        text = f"Scanning {n} folder{'s' if n != 1 else ''}" if n else "Nothing is ticked: Rescan has nothing to scan"
        if self.sel.skips:
            k = len(self.sel.skips)
            text += f", leaving out {k} folder{'s' if k != 1 else ''} inside"
        text += "."
        if gone:
            text += f" Unticked folders hold {gone:,} item{'s' if gone != 1 else ''} in the catalogue."
        self.summary.setText(text)

    def _clicked(self, item, col):
        if col != 0:
            return
        path = item.data(0, self.PATH)
        if not path:
            return
        if item.checkState(0) == Qt.CheckState.Checked:
            self.sel.tick(path)
        else:
            self.sel.untick(path)
        self._paint()

    # ---- saving
    def _gone(self):
        return [s for s in self.sources if self.old.included(s) and not self.sel.included(s)]

    def _save(self):
        gone = self._gone()
        if gone:
            box = QMessageBox(self)
            box.setWindowTitle("Scan folders")
            box.setIcon(QMessageBox.Icon.Question)
            box.setText(f"The folders you've unticked hold <b>{len(gone):,}</b> item"
                        f"{'s' if len(gone) != 1 else ''} in the catalogue. Keep them, or take them out?")
            box.setInformativeText("Either way, the files themselves stay where they are. Kept items stay "
                                   "as they are now: a Rescan won't update them or notice if they're deleted.")
            remove = box.addButton("Take them out", QMessageBox.ButtonRole.DestructiveRole)
            keep = box.addButton("Keep them", QMessageBox.ButtonRole.AcceptRole)
            box.addButton(QMessageBox.StandardButton.Cancel)
            box.setDefaultButton(keep)
            box.exec()
            if box.clickedButton() not in (remove, keep):
                return
            if box.clickedButton() is remove:
                self.cat.forget(gone)
        self.cat.save_selection(self.sel)
        self.changed = (self.sel.roots, self.sel.skips) != (self.old.roots, self.old.skips) or bool(gone)
        self.rescan = self.sel.gains(self.old)
        self.accept()


class SetupDialog(QDialog):
    """Help > Check setup: each part TurboCAT uses, whether it is here, and how to get it."""

    ICON = {setupcheck.OK: "ok", setupcheck.PARTIAL: "warning", setupcheck.MISSING: "problem"}

    def __init__(self, parent, on_identify=None):
        super().__init__(parent)
        self.on_identify = on_identify
        self.setObjectName("dialog")
        self.setWindowTitle("Check setup")
        self.setMinimumSize(760, 620)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 22, 24, 20)
        v.setSpacing(10)
        self.head = QLabel()
        self.head.setFont(ui_font(20, QFont.Weight.Bold))
        v.addWidget(self.head)
        self.sub = _wrap_label("", ui_font(13), "muted")
        v.addWidget(self.sub)
        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.area.setFrameShape(QFrame.Shape.NoFrame)
        v.addWidget(self.area, 1)
        buttons = QHBoxLayout()
        again = QPushButton("Check again")
        again.setToolTip("Look again, e.g. after installing something")
        again.clicked.connect(self.fill)
        close = QPushButton("Close")
        close.setObjectName("primary")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        for b in (again, close):
            b.setFont(ui_font(13, QFont.Weight.DemiBold))
        buttons.addWidget(again)
        buttons.addStretch(1)
        buttons.addWidget(close)
        v.addLayout(buttons)
        self.fill()

    def fill(self):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.checks = setupcheck.run()
        finally:
            QApplication.restoreOverrideCursor()
        win = self.parent()
        self.feats = (win.setup_features(self.checks) if hasattr(win, "setup_features")
                      else setupcheck.features(self.checks))
        gaps = [f for f in self.feats if f.status != setupcheck.OK]
        self.head.setText("Everything works on this computer." if not gaps else
                          f"{len(gaps)} feature{'s' if len(gaps) > 1 else ''} not fully working yet")
        self.sub.setText(f"On this computer ({setupcheck.platform_name()}). First what works, then the "
                         "parts TurboCAT uses: each missing part says how to get it.")
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 4, 8, 4)
        lay.setSpacing(8)
        lay.addWidget(self._section("WHAT WORKS"))
        for f in self.feats:
            lay.addWidget(self._feature_row(f))
        lay.addSpacing(10)
        lay.addWidget(self._section("THE PARTS TURBOCAT USES"))
        for c in self.checks:
            lay.addWidget(self._row(c))
        lay.addStretch(1)
        self.area.setWidget(body)

    def _section(self, text):
        lab = QLabel(text)
        lab.setObjectName("muted")
        lab.setFont(ui_font(12, QFont.Weight.DemiBold))
        return lab

    def _feature_row(self, f):
        """One line per feature: a mark, its name, and what that means for this collection."""
        row = QFrame()
        h = QHBoxLayout(row)
        h.setContentsMargins(4, 2, 4, 2)
        h.setSpacing(10)
        pic = QLabel()
        ico = {setupcheck.OK: "ok", setupcheck.PARTIAL: "warning"}.get(f.status, "problem")
        pic.setPixmap(icon(ico if f.important or f.status == setupcheck.OK else "warning", 18))
        pic.setFixedSize(18, 18)
        h.addWidget(pic, 0, Qt.AlignmentFlag.AlignTop)
        text = _wrap_label(f"<b>{_esc(f.name)}</b> — {_esc(f.effect)}"
                           + (" <i>(hover for more)</i>" if f.detail else ""), ui_font(13))
        text.setTextFormat(Qt.TextFormat.RichText)
        h.addWidget(text, 1)
        missing = [c.name for c in self.checks if c.name in f.needs and c.status != setupcheck.OK]
        row.setToolTip((f.detail + "\n\n" if f.detail else "") + "Uses: " + ", ".join(f.needs) + (
            "\nMissing: " + ", ".join(missing) + " (see below for how to get it)" if missing else ""))
        return row

    def _row(self, c):
        box = QFrame()
        box.setObjectName("note_neutral" if c.status == setupcheck.OK else
                          ("note_warn" if c.status == setupcheck.PARTIAL or not c.important else "note_problem"))
        h = QHBoxLayout(box)
        h.setContentsMargins(12, 10, 12, 10)
        h.setSpacing(10)
        pic = QLabel()
        pic.setPixmap(icon(self.ICON[c.status] if c.important or c.status == setupcheck.OK else "warning", 20))
        pic.setFixedSize(20, 20)
        h.addWidget(pic, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(3)
        title = _wrap_label(f"<b>{_esc(c.name)}</b> — {_esc(c.purpose)}", ui_font(13))
        title.setTextFormat(Qt.TextFormat.RichText)
        col.addWidget(title)
        if c.detail:
            col.addWidget(_wrap_label(("Found: " if c.status == setupcheck.OK else "") + c.detail, ui_font(12)))
        if c.status != setupcheck.OK:
            if c.without:
                col.addWidget(_wrap_label(f"Without it: {c.without}.", ui_font(12)))
            if c.advice:
                col.addWidget(_wrap_label(c.advice, ui_font(12)))
            actions = QHBoxLayout()
            actions.setSpacing(8)
            if c.command:
                cmd = QLineEdit(c.command)
                cmd.setReadOnly(True)
                cmd.setFont(data_font(12))
                cmd.setCursorPosition(0)
                copy = QPushButton("Copy")
                copy.setObjectName("small")
                copy.setToolTip("Copy the command, then paste it into a terminal")
                copy.clicked.connect(lambda _=False, t=c.command, b=copy: (
                    QGuiApplication.clipboard().setText(t), b.setText("Copied")))
                actions.addWidget(cmd, 1)
                actions.addWidget(copy)
            if c.url:
                web = QPushButton("Open website")
                web.setObjectName("small")
                web.setToolTip(c.url)
                web.clicked.connect(lambda _=False, u=c.url: QDesktopServices.openUrl(QUrl(u)))
                actions.addWidget(web)
            if "identify" in c.tags and self.on_identify:
                go = QPushButton("Identify disks online…")
                go.setObjectName("small")
                go.clicked.connect(lambda: (self.accept(), self.on_identify()))
                actions.addWidget(go)
            if not c.command:
                actions.addStretch(1)
            if actions.count():
                col.addLayout(actions)
        h.addLayout(col, 1)
        return box


class RenameDialog(QDialog):
    """Show the files that would be renamed to their TOSEC names; rename the ticked ones."""

    LOG = os.path.expanduser("~/.local/share/turbocat/renames.csv")

    def __init__(self, parent, plan):
        super().__init__(parent)
        self.plan = plan
        self.setObjectName("dialog")
        self.setWindowTitle("Rename files to their proper names")
        self.setMinimumSize(820, 460)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 22, 24, 20)
        v.setSpacing(12)
        head = QLabel(f"Rename {_n(len(plan), 'file')} to {'their' if len(plan) > 1 else 'its'} TOSEC "
                      "name?")
        head.setFont(ui_font(18, QFont.Weight.Bold))
        v.addWidget(head)
        v.addWidget(_wrap_label(
            "These disks were identified by their checksums. Only the names change: the files stay "
            "in their folders, their contents are untouched, and TurboCAT's catalogue follows them. "
            "Untick any you want to keep as they are. Files in a synced folder (such as Dropbox) "
            f"are renamed there too. A list of every rename is kept in {self.LOG}.",
            ui_font(13), "muted"))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Now", "Will be"])
        self.tree.setRootIsDecorated(False)
        self.tree.setFont(ui_font(12))
        for it, old, new in plan:
            row = QTreeWidgetItem([os.path.basename(old), os.path.basename(new)])
            row.setCheckState(0, Qt.CheckState.Checked)
            row.setToolTip(0, old)
            row.setToolTip(1, new)
            self.tree.addTopLevelItem(row)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.tree.setColumnWidth(0, 260)
        v.addWidget(self.tree, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Rename")
        ok.setObjectName("primary")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        for b in (cancel, ok):
            b.setFont(ui_font(13, QFont.Weight.DemiBold))
            buttons.addWidget(b)
        v.addLayout(buttons)

    def apply(self, cat):
        """Rename the ticked files and update the catalogue. Returns (renamed, failed)."""
        import csv
        done = failed = 0
        moved = {}
        for i, (it, old, new) in enumerate(self.plan):
            if self.tree.topLevelItem(i).checkState(0) != Qt.CheckState.Checked:
                continue
            if os.path.exists(new):
                failed += 1
                continue
            try:
                os.rename(old, new)
            except OSError:
                failed += 1
                continue
            cat.db.execute("UPDATE media SET source=? WHERE source=?", (new, old))
            moved[old] = new
            done += 1
        cat.db.commit()
        # Choices remembered by path (which copy or version to show) follow the files.
        for key in (dupes.CHOICES, vers.CHOICES):
            c = cat.get_meta(key, {}) or {}
            if any(p in moved for p in c.values()):
                cat.set_meta(key, {k: moved.get(p, p) for k, p in c.items()})
        if moved:
            os.makedirs(os.path.dirname(self.LOG), exist_ok=True)
            new_log = not os.path.exists(self.LOG)
            with open(self.LOG, "a", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                if new_log:
                    w.writerow(["When", "Old name", "New name"])
                for old, new in moved.items():
                    w.writerow([time.strftime("%Y-%m-%d %H:%M"), old, new])
        return done, failed


class AboutDialog(QDialog):
    """About TurboCAT 4: version, the catalogue in use and its safety copies, what it is built on."""

    REPO = "https://github.com/davidhill99/TurboCAT4"

    def __init__(self, parent, cat, db_path):
        super().__init__(parent)
        from . import catalogue as catalogue_mod
        import platform
        import PySide6
        from PySide6.QtCore import qVersion
        self.setObjectName("dialog")
        self.setWindowTitle(f"About {APP_NAME}")
        self.setMinimumWidth(560)
        v = QVBoxLayout(self)
        v.setContentsMargins(28, 24, 28, 20)
        v.setSpacing(14)

        top = QHBoxLayout()
        top.setSpacing(16)
        mark = QLabel()
        mark.setPixmap(icon("mark", 64))
        mark.setFixedSize(64, 64)
        top.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)
        words = QVBoxLayout()
        words.setSpacing(2)
        name = QLabel(f"TurboCAT <span style='color:{C['accent'].name()}'>4</span>")
        name.setFont(ui_font(26, QFont.Weight.Bold))
        name.setTextFormat(Qt.TextFormat.RichText)
        words.addWidget(name)
        ver = QLabel(f"Version {VERSION}")
        ver.setObjectName("muted")
        ver.setFont(data_font(12))
        ver.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        words.addWidget(ver)
        top.addLayout(words, 1)
        v.addLayout(top)

        v.addWidget(_wrap_label(
            "Catalogue and search your Amiga disk images, archives and folders: what is on every "
            "disk, which are games, which have problems or duplicates, their pictures and their "
            "music. A modern revival of TurboCAT and TurboCAT-Pro by David Hill (1994–1996).",
            ui_font(13)))

        def section(title):
            lab = QLabel(title.upper())
            lab.setObjectName("muted")
            lab.setFont(ui_font(11, QFont.Weight.DemiBold))
            v.addWidget(lab)
            grid = QGridLayout()
            grid.setHorizontalSpacing(16)
            grid.setVerticalSpacing(4)
            grid.setColumnStretch(1, 1)
            v.addLayout(grid)
            return grid

        def row(grid, label, value, muted=False):
            r = grid.rowCount()
            k = QLabel(label)
            k.setObjectName("muted")
            k.setFont(ui_font(12))
            k.setMinimumWidth(110)           # both sections line up
            grid.addWidget(k, r, 0, Qt.AlignmentFlag.AlignTop)
            val = _wrap_label(value, ui_font(12), "muted" if muted else None)
            grid.addWidget(val, r, 1)

        # The catalogue in use, and its safety copies
        g = section("Your catalogue")
        st = cat.stats()                 # the same counts as the window's header
        items, files = st["items"], st["files"]
        try:
            size = _short_size(os.path.getsize(db_path))
        except OSError:
            size = "?"
        row(g, "File", db_path)
        row(g, "Holds", f"{_n(items, 'item')}, {files:,} files · {size}")
        self.backup_dir = catalogue_mod.backup_folder(db_path)
        copies = catalogue_mod.backups(db_path)
        if copies:
            newest = time.strftime("%-d %b %Y, %H:%M", time.localtime(copies[0][1]))
            row(g, "Safety copies", f"{len(copies)} cop{'y' if len(copies) == 1 else 'ies'}, newest {newest}\n{self.backup_dir}")
        else:
            row(g, "Safety copies", "None yet: one is made when TurboCAT next starts", muted=True)

        # What it runs on
        g = section("Built with")
        row(g, "Python", platform.python_version())
        row(g, "Qt", f"{qVersion()} (PySide6 {PySide6.__version__})")
        try:
            from importlib.metadata import version as pkg_version
            ami = pkg_version("amitools")
        except Exception:
            ami = "installed"
        row(g, "amitools", f"{ami}: reads Amiga disks and filesystems")
        vers = music.versions()
        row(g, "libopenmpt", f"{vers['libopenmpt']}: plays music modules" if vers["libopenmpt"]
            else "not installed: music can't play (sudo apt install libopenmpt0)",
            muted=not vers["libopenmpt"])
        row(g, "libxmp", f"{vers['libxmp']}: plays OctaMED synth tunes" if vers["libxmp"]
            else "not installed: OctaMED synth tunes stay silent (sudo apt install libxmp4)",
            muted=not vers["libxmp"])
        row(g, "Pictures", "found on your disks first, then in the libretro-thumbnails collection")

        link = QLabel(f"<a href='{self.REPO}' style='color:{C['accent'].name()}'>{self.REPO}</a>")
        link.setFont(ui_font(12))
        link.setTextFormat(Qt.TextFormat.RichText)
        link.setOpenExternalLinks(True)
        v.addWidget(link)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        if copies:
            open_btn = QPushButton("Show safety copies")
            open_btn.setFont(ui_font(13, QFont.Weight.DemiBold))
            open_btn.clicked.connect(
                lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.backup_dir)))
            buttons.addWidget(open_btn)
        close = QPushButton("Close")
        close.setObjectName("primary")
        close.setFont(ui_font(13, QFont.Weight.DemiBold))
        close.setDefault(True)
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        v.addLayout(buttons)


class MainWindow(QMainWindow):
    def __init__(self, db_path):
        super().__init__()
        self.db_path = db_path
        self.cat = Catalogue(db_path)
        self.all_items = load_items(self.cat)
        self.group_sets = bool(self.cat.get_meta("group_sets", True))
        self._make_sets()
        self.setWindowTitle(f"{APP_NAME} — {os.path.basename(db_path)}")
        self.setWindowIcon(QIcon(icon("mark", 64)))
        self.resize(1280, 860)

        root = QWidget()
        root.setObjectName("root")
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # Header: mark, wordmark and counts
        head = QFrame()
        head.setObjectName("header")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(24, 18, 24, 18)
        hl.setSpacing(12)
        mark = QLabel()
        mark.setPixmap(icon("mark", 48))
        mark.setFixedSize(48, 48)
        words = QVBoxLayout()
        words.setSpacing(2)
        name = QLabel(f"TurboCAT <span style='color:{C['accent'].name()}'>4</span>")
        name.setFont(ui_font(26, QFont.Weight.Bold))
        name.setTextFormat(Qt.TextFormat.RichText)
        self.counts = QLabel()
        self.counts.setObjectName("muted")
        self.counts.setFont(ui_font(13))
        words.addWidget(name)
        words.addWidget(self.counts)
        hl.addWidget(mark)
        hl.addLayout(words)
        hl.addStretch(1)
        self.scan_btn = KeyButton("Scan folder…", "Ctrl+O")
        self.scan_btn.setObjectName("primary")
        self.scan_btn.setToolTip("Add a folder of Amiga disk images to the catalogue (Ctrl+O)")
        self.rescan_btn = KeyButton("Rescan", "F5")
        self.rescan_btn.setToolTip("Look again at every folder scanned before: new and changed "
                                   "files are read, deleted ones removed (F5)")
        self.gotek_btn = KeyButton("Copy to Gotek stick", "Ctrl+G")
        self.gotek_btn.setToolTip("Copy the selected disks to a USB stick for a Gotek drive (Ctrl+G). "
                                  "Select several with Ctrl or Shift.")
        self.tv_btn = QPushButton("TurboView")
        self.tv_btn.setToolTip("Start an emulated Amiga with TurboView, the Amiga side of TurboCAT, "
                               "and your collection folders mounted as drives")
        self.online_btn = QPushButton("Find pictures online")
        self.online_btn.setToolTip("Look up title screens for disks that have no picture of their own, "
                                   "in the libretro-thumbnails collection on GitHub, and magazine covers for "
                                   "coverdisks on the Internet Archive")
        self.setup_btn = QPushButton("Setup")
        self.setup_btn.setIcon(QIcon(icon("ok", 16)))
        self.setup_btn.setToolTip("What works on this computer, and what to install for the rest")
        for b in (self.scan_btn, self.rescan_btn, self.gotek_btn, self.online_btn, self.tv_btn,
                  self.setup_btn):
            b.setFont(ui_font(14, QFont.Weight.DemiBold))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            hl.addWidget(b)
        self.setup_btn.clicked.connect(self.check_setup)
        self.scan_btn.clicked.connect(self.scan_folder)
        self.rescan_btn.clicked.connect(self.rescan)
        self.gotek_btn.clicked.connect(lambda: self.copy_to_gotek())
        self.online_btn.clicked.connect(self.find_online)
        self.tv_btn.clicked.connect(self.start_turboview)
        v.addWidget(head)

        # Search
        sw = QWidget()
        sl = QVBoxLayout(sw)
        sl.setContentsMargins(24, 18, 24, 8)
        sl.setSpacing(10)
        self.search = SearchBox()
        self.result_label = QLabel()
        self.result_label.setObjectName("muted")
        self.result_label.setFont(ui_font(13))
        sl.addWidget(self.search)
        chips = FlowLayout(spacing=8)          # wraps onto a second line in a narrow window
        self.filter = "all"
        self.chips = {}
        self.chip_group = QButtonGroup(self)
        self.chip_group.setExclusive(True)
        for key, label, ico, _ in FILTERS:
            b = QPushButton(label)
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setFont(ui_font(13, QFont.Weight.DemiBold))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            if ico:
                label = " " + label
                b.setIcon(QIcon(icon(ico, 16)))
                b.setIconSize(QSize(16, 16))
            b.setProperty("hasIcon", bool(ico))
            b.setText(label)
            b.clicked.connect(lambda _=False, k=key: self.set_filter(k))
            self.chip_group.addButton(b)
            self.chips[key] = (b, label)
            chips.addWidget(b)
        self.chips["all"][0].setChecked(True)
        sl.addLayout(chips)
        self.scan_bar = QFrame()
        self.scan_bar.setObjectName("scanBar")
        bar_rows = QVBoxLayout(self.scan_bar)
        bar_rows.setContentsMargins(12, 6, 8, 6)
        bar_rows.setSpacing(6)
        sb = QHBoxLayout()
        sb.setSpacing(12)
        bar_rows.addLayout(sb)
        self.scan_busy = QProgressBar()
        self.scan_busy.setObjectName("scanMeter")
        self.scan_busy.setRange(0, 0)
        self.scan_busy.setFixedWidth(260)
        self.scan_busy.setTextVisible(False)
        self.scan_text = QLabel()
        self.scan_text.setFont(ui_font(13, QFont.Weight.DemiBold))
        self.scan_file = QLabel()
        self.scan_file.setObjectName("scanFile")
        self.scan_file.setFont(ui_font(12))
        self.scan_file.setMinimumWidth(40)
        self.scan_file.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setFont(ui_font(13, QFont.Weight.DemiBold))
        self.stop_btn.setObjectName("small")
        self.stop_btn.clicked.connect(self._stop_clicked)
        sb.addWidget(self.scan_busy)
        sb.addWidget(self.scan_text)
        sb.addWidget(self.scan_file, 1)
        sb.addWidget(self.stop_btn)
        # A second row while one big file is read: how far into it, and how long it has left.
        self.sub_row = QWidget()
        sr = QHBoxLayout(self.sub_row)
        sr.setContentsMargins(0, 0, 4, 2)
        sr.setSpacing(12)
        self.sub_text = QLabel()
        self.sub_text.setFont(ui_font(12, QFont.Weight.DemiBold))
        self.sub_meter = QProgressBar()
        self.sub_meter.setObjectName("scanMeter")
        self.sub_meter.setRange(0, 1000)
        self.sub_meter.setTextVisible(False)
        self.sub_left = QLabel()
        self.sub_left.setObjectName("scanFile")
        self.sub_left.setFont(ui_font(12))
        sr.addWidget(self.sub_text)
        sr.addWidget(self.sub_meter, 1)
        sr.addWidget(self.sub_left)
        self.sub_row.hide()
        bar_rows.addWidget(self.sub_row)
        self.scan_bar.hide()
        sl.addWidget(self.scan_bar)
        res_row = QHBoxLayout()
        res_row.setSpacing(8)
        # long summaries wrap rather than widen the window
        self.result_label.setWordWrap(True)
        self.result_label.setMinimumWidth(120)
        self.result_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        res_row.addWidget(self.result_label, 1)
        self.fix_btn = QPushButton("Fix all…")
        self.fix_btn.setFont(ui_font(12, QFont.Weight.DemiBold))
        self.fix_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fix_btn.setToolTip("Shows what TurboCAT would do for each of these, and asks first. "
                                "Your original disk images are never changed.")
        self.fix_btn.clicked.connect(self.fix_all)
        self.fix_btn.hide()
        res_row.addWidget(self.fix_btn)
        self.group_btn = QPushButton("Group sets and versions")
        self.group_btn.setObjectName("segment")
        self.group_btn.setCheckable(True)
        self.group_btn.setChecked(self.group_sets)
        self.group_btn.setFont(ui_font(12, QFont.Weight.DemiBold))
        self.group_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.group_btn.setToolTip("On: each multi-disk game or program is one row, showing whether the "
                                  "set is complete, and each disk shows one of its versions (TOSEC [h], "
                                  "[m], [o]... variants are hidden). Off: every disk and version on its own row.")
        self.group_btn.toggled.connect(self.set_grouping)
        res_row.addWidget(self.group_btn)
        res_row.addSpacing(8)
        self.view_disks = QPushButton("Disks")
        self.view_tunes = QPushButton("Tunes")
        self.view_group = QButtonGroup(self)
        for b in (self.view_disks, self.view_tunes):
            b.setObjectName("segment")
            b.setCheckable(True)
            b.setFont(ui_font(12, QFont.Weight.DemiBold))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            self.view_group.addButton(b)
            res_row.addWidget(b)
        self.view_disks.setChecked(True)
        self.view_disks.setToolTip("One row per disk or archive that has music on it")
        self.view_tunes.setToolTip("One row per tune: every module TurboCAT has found")
        self.view_disks.clicked.connect(lambda: self.set_tune_view(False))
        self.view_tunes.clicked.connect(lambda: self.set_tune_view(True))
        self.export_tunes_btn = QPushButton("Export list…")
        self.export_tunes_btn.setObjectName("segment")
        self.export_tunes_btn.setFont(ui_font(12, QFont.Weight.DemiBold))
        self.export_tunes_btn.setToolTip("Save this list of tunes as a spreadsheet (CSV)")
        self.export_tunes_btn.clicked.connect(self.export_tunes)
        self.fav_tunes_btn = QPushButton("Favourites")
        self.fav_tunes_btn.setObjectName("segment")
        self.fav_tunes_btn.setCheckable(True)
        self.fav_tunes_btn.setIcon(QIcon(icon("star", 16)))
        self.fav_tunes_btn.setFont(ui_font(12, QFont.Weight.DemiBold))
        self.fav_tunes_btn.setToolTip("Only your favourite tunes (star a tune with Ctrl+D, or click its note)")
        self.fav_tunes_btn.toggled.connect(lambda _: self.run_search())
        res_row.addSpacing(8)
        res_row.addWidget(self.fav_tunes_btn)
        res_row.addWidget(self.export_tunes_btn)
        sl.addLayout(res_row)
        self.tune_view = False
        v.addWidget(sw)

        # List (or an empty / nothing-found message)
        self.model = ItemModel()
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setItemDelegate(RowDelegate(self.table))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setMouseTracking(False)
        self.table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(56)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        hh = self.table.horizontalHeader()
        hf = ui_font(12, QFont.Weight.DemiBold)
        hf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.6)
        hh.setFont(hf)
        hh.setHighlightSections(False)
        hh.setSectionsClickable(False)
        hh.setMinimumSectionSize(60)
        # Every divider can be dragged (double-click one to fit the column to its contents);
        # the Status column takes up whatever room is left. Widths are remembered.
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hh.setStretchLastSection(True)
        hh.setCascadingSectionResizes(False)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.widths_set = False
        self.save_widths = QTimer(self, singleShot=True, interval=600)
        self.save_widths.timeout.connect(
            lambda: self.cat.set_meta("column_widths", [hh.sectionSize(c) for c in range(4)]))
        hh.sectionResized.connect(lambda *_: self.widths_set and self.save_widths.start())

        self.message = QLabel()
        self.message.setObjectName("message")
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setWordWrap(True)
        self.message.setFont(ui_font(15))
        self.message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.tune_model = TuneModel()
        self.tune_proxy = QSortFilterProxyModel(self)
        self.tune_proxy.setSourceModel(self.tune_model)
        self.tune_proxy.setSortRole(SORT_ROLE)
        self.tunes_table = QTableView()
        self.tunes_table.setModel(self.tune_proxy)
        self.tunes_table.setObjectName("tunesTable")
        self.tunes_table.setSortingEnabled(True)
        self.tunes_table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.tunes_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tunes_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tunes_table.setShowGrid(False)
        self.tunes_table.setWordWrap(False)
        self.tunes_table.setIconSize(QSize(16, 16))
        self.tunes_table.verticalHeader().hide()
        self.tunes_table.verticalHeader().setDefaultSectionSize(40)
        self.tunes_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tunes_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.tunes_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        th2 = self.tunes_table.horizontalHeader()
        th2.setFont(hf)
        th2.setHighlightSections(False)
        th2.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        th2.setStretchLastSection(True)
        for col, width in enumerate((300, 160, 170, 80, 80, 70)):
            self.tunes_table.setColumnWidth(col, width)
        self.tunes_table.doubleClicked.connect(self._play_tune)
        self.tunes_table.activated.connect(self._play_tune)
        self.tunes_table.selectionModel().currentRowChanged.connect(self._tune_row_changed)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.table)
        self.stack.addWidget(self.message)
        self.stack.addWidget(self.tunes_table)
        panel = QFrame()
        panel.setObjectName("panel")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(1, 1, 1, 1)
        pl.addWidget(self.stack)
        self.details = DetailsPanel(self.cat, self.select_number, self.copy_to_gotek, self.find_online,
                                    self.play_music, self.play_in_emulator)
        self.details.on_keep = self.keep_copy
        self.details.on_favourite = self.toggle_favourite
        self.details.on_recheck = lambda: self.recheck_items(
            list(self.details.item.members) if self.details.item is not None and self.details.item.members
            else [self.details.item_id] if self.details.item_id else [])
        self.table.clicked.connect(self._row_clicked)
        self.tunes_table.clicked.connect(self._tune_clicked)
        self.tv_timer = QTimer(self, singleShot=True, interval=4000)
        self.tv_timer.timeout.connect(self._update_turboview)
        self.tv_worker = None
        self.details.on_version = self.show_version
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setObjectName("split")
        split.setHandleWidth(20)
        split.setChildrenCollapsible(False)
        split.addWidget(panel)
        split.addWidget(self.details)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setSizes([820, 420])
        lw = QWidget()
        ll = QVBoxLayout(lw)
        ll.setContentsMargins(24, 4, 24, 24)
        ll.addWidget(split)
        v.addWidget(lw, 1)

        self.player_bar = PlayerBar(self.cat)
        v.addWidget(self.player_bar)

        # Status line
        foot = QFrame()
        foot.setObjectName("footer")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(24, 10, 24, 10)
        fl.setSpacing(20)
        self.foot_left = ElidedLabel()
        self.foot_right = ElidedLabel(f"{APP_NAME} {VERSION} · {db_path}")
        for lab in (self.foot_left, self.foot_right):
            lab.setObjectName("muted")
            lab.setFont(ui_font(12))
        self.foot_right.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        fl.addWidget(self.foot_left, 1)
        fl.addWidget(self.foot_right, 1)
        v.addWidget(foot)

        self.setCentralWidget(root)
        self._style()

        self.timer = QTimer(self, singleShot=True, interval=200)
        self.timer.timeout.connect(self.run_search)
        self.search.edit.textChanged.connect(lambda _: self.timer.start())
        self.search.edit.returnPressed.connect(self.run_search)
        QShortcut(QKeySequence.StandardKey.Find, self, activated=self.focus_search)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self.search.edit, activated=self.search.edit.clear)
        self.table.doubleClicked.connect(lambda _i: self.play_selected())
        self._build_menus()
        QTimer.singleShot(1500, self._setup_on_start)
        self.emulators = None
        self.worker = None
        self.bar_mode = "scan"
        self.pic_asked = self.pic_shown = False
        self.spares_hidden = 0
        self.versions_hidden = 0
        self.closing = False
        self.close_timer = QTimer(self, singleShot=True, interval=15000)
        self.close_timer.timeout.connect(self._close_slow)
        self.hide_bar = QTimer(self, singleShot=True, interval=10000)
        self.hide_bar.timeout.connect(self.scan_bar.hide)
        self.live = QTimer(self, interval=4000)      # show new items while a scan runs
        self.live.timeout.connect(self._live_reload)
        self.current_id = None
        self.table.selectionModel().currentRowChanged.connect(self._row_changed)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._selection_changed())

        self.pic_worker = None
        self.pic_refresh = QTimer(self, interval=8000)   # show pictures as they are found
        self.pic_refresh.timeout.connect(self.reload)
        self._fill_counts()
        self.run_search()
        self.search.edit.setFocus()
        QTimer.singleShot(1500, self.find_pictures)

    def _row_changed(self, current, _previous):
        if not current.isValid():
            self.details.clear()
            return
        it = self.model.items[current.row()]
        self.current_id = it.id
        self.details.show_item(it)

    def selected_ids(self):
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        if not rows and self.table.currentIndex().isValid():
            rows = [self.table.currentIndex().row()]
        return [self.model.items[r].id for r in rows if r < len(self.model.items)]

    def _build_menus(self):
        """The menu bar: every command, with its keyboard shortcut. The header buttons are
        shortcuts to the most used ones."""
        bar = self.menuBar()

        def add(menu, text, slot, keys=None, tip=None):
            a = QAction(text, self)
            if keys:
                a.setShortcut(QKeySequence(keys))
            if tip:
                a.setStatusTip(tip)
                a.setToolTip(tip)
            a.triggered.connect(lambda _=False: slot())
            menu.addAction(a)
            return a

        m = bar.addMenu("&File")
        self.act_scan = add(m, "&Scan folder…", self.scan_folder, "Ctrl+O",
                            "Add a folder of Amiga disk images to the catalogue")
        self.act_rescan = add(m, "&Rescan", self.rescan, "F5",
                              "Look again at every folder scanned before")
        self.act_folders = add(m, "Scan f&olders…", self.manage_scan_folders, None,
                               "See the folders TurboCAT scans; stop scanning one, or leave out a folder "
                               "inside one")
        m.addSeparator()
        add(m, "&Export tune list…", self.export_tune_list, None,
            "Save every tune found as a spreadsheet")
        add(m, "Export &sets to complete…", self.export_sets, None,
            "Save the disk sets with missing or damaged disks, and what each needs, as a spreadsheet")
        m.addSeparator()
        add(m, "&Quit", self.close, "Ctrl+Q")

        m = bar.addMenu("&Disk")
        self.act_play = add(m, "&Play", self.play_selected, "Ctrl+P",
                            "Start the disk in an emulator, or play a tune in TurboCAT")
        self.act_gotek = add(m, "Copy to &Gotek stick…", lambda: self.copy_to_gotek(), "Ctrl+G")
        self.act_fav = add(m, "Add to &favourites", self.toggle_favourite, "Ctrl+D",
                           "Star the selected disks, games, utilities or tune; they show under Favourites "
                           "here and in TurboView")
        self.act_folder = add(m, "Show in &folder", self.show_selected_in_folder, "Ctrl+Shift+O",
                              "Open the folder holding the selected item")
        self.act_recheck = add(m, "&Recheck", lambda: self.recheck_items(), "Shift+F5", RECHECK_TIP)
        self.act_repair = add(m, "Make re&paired copy…", lambda: self.make_repaired_copy(), None,
                              "Rebuild the selected damaged disk as a new image, putting back its damaged "
                              "files from copies on your other disks (asks first; the original isn't changed)")

        m = bar.addMenu("&Tools")
        self.act_online = add(m, "Find pictures &online", self.find_online, None,
                              "Look up title screens in the libretro-thumbnails collection, and magazine covers for coverdisks on the Internet Archive")
        self.act_identify = add(m, "&Identify disks online…", self.identify_online, None,
                                "Find each disk's proper name from its checksum, in the TOSEC list of Amiga disks")
        add(m, "&Rename files to their proper names…", self.rename_to_tosec, None,
            "Rename identified disks' files to their TOSEC names (shows the list first)")
        add(m, "Start &TurboView", self.start_turboview, None,
            "Start an emulated Amiga with TurboView and your collection mounted")

        m = bar.addMenu("&Help")
        add(m, "&Check setup…", self.check_setup, None,
            "What TurboCAT uses (emulator, Kickstart ROMs, music players…), what's missing and how to get it")
        m.addSeparator()
        add(m, f"&About {APP_NAME}", self.show_about, "F1")
        add(m, f"{APP_NAME} on &GitHub", lambda: QDesktopServices.openUrl(QUrl(AboutDialog.REPO)))
        self._selection_changed()
        # Right-click on the list: the Disk menu's commands for what is selected
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._list_menu)

    def _list_menu(self, pos):
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        if not self.table.selectionModel().isRowSelected(index.row(), QModelIndex()):
            self.table.selectRow(index.row())
        menu = QMenu(self)
        for a in (self.act_play, self.act_recheck, self.act_folder, None, self.act_gotek, self.act_fav):
            if a is None:
                menu.addSeparator()
            else:
                menu.addAction(a)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def show_selected_in_folder(self):
        ids = self.selected_ids()
        m = self.cat.media_by_id(ids[0]) if ids else None
        if m is None:
            return
        src = m["source"]
        QDesktopServices.openUrl(QUrl.fromLocalFile(src if os.path.isdir(src) else os.path.dirname(src)))

    def export_tune_list(self):
        """File > Export tune list: the Tunes view's list, switching to it if needed."""
        if self.filter != "music":
            self.set_filter("music")
        self.set_tune_view(True)
        self.export_tunes()

    def _selection_changed(self):
        n = len(self.table.selectionModel().selectedRows())
        self.gotek_btn.setText(f"Copy {n:,} to Gotek stick" if n > 1 else "Copy to Gotek stick")
        if hasattr(self, "act_play"):
            ids = self.selected_ids()
            chosen = [it for it in self.model.items if it.id in set(ids)]
            tunes = bool(chosen) and all(it.type == "Module" for it in chosen)
            self.act_play.setText("&Play tune" if tunes else "&Play in emulator")
            self.act_gotek.setText(f"Copy {n:,} to &Gotek stick…" if n > 1 else "Copy to &Gotek stick…")
            for a in (self.act_play, self.act_gotek, self.act_folder, self.act_recheck):
                a.setEnabled(bool(ids))
            self.act_repair.setEnabled(any(it.status == "error" and not it.repaired for it in chosen))
            self.act_recheck.setText(f"&Recheck {n:,} items" if n > 1 else "&Recheck")
            self.act_fav.setText("Remove from &favourites" if chosen and all(c.favourite for c in chosen)
                                 else "Add to &favourites")

    def _make_sets(self):
        self.set_rows, self.member_of, self.disk_no = make_set_items(self.all_items)

    def _grouped(self, shown, text):
        """Replace the disks of each multi-disk set with the set's own row (where its first
        listed disk was). A search hit on any disk brings in the set."""
        out, seen = [], set()
        for it in shown:
            row = self.member_of.get(it.id)
            if row is None:
                out.append(it)
                continue
            if row.id in seen:
                continue
            seen.add(row.id)
            row.found = (f"disk {self.disk_no[it.id]}: {it.found}" if text and it.found else "")
            out.append(row)
        return out

    def set_grouping(self, on):
        self.group_sets = bool(on)
        self.cat.set_meta("group_sets", self.group_sets)
        if self.group_btn.isChecked() != self.group_sets:
            self.group_btn.setChecked(self.group_sets)
        self.run_search()

    def _expand(self, ids):
        """Selected rows -> catalogue ids: a disk set's row stands for all its disks."""
        rows = {it.id: it for it in self.model.items}
        out = []
        for i in ids:
            it = rows.get(i)
            out += list(it.members) if it is not None and it.members else [i]
        return out

    def export_sets(self):
        """File > Export sets to complete: each incomplete set and the disks it needs."""
        todo = [r for r in self.set_rows if r.set_problem]
        if not todo:
            QMessageBox.information(self, "Sets to complete", "Every disk set is complete.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save the list of sets to complete",
                                              os.path.expanduser("~/TurboCAT sets to complete.csv"),
                                              "Spreadsheet (*.csv)")
        if not path:
            return
        import csv
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["Set", "Disks in set", "Disks you have", "Missing", "Damaged", "Notes", "Folder"])
            for r in todo:
                ds = r.dset
                w.writerow([ds.key, ds.expected, ", ".join(str(n) for n, _, _ in ds.disks),
                            ", ".join(map(str, ds.missing)), ", ".join(map(str, ds.problem_disks)),
                            "; ".join(ds.flags), os.path.dirname(r.path)])
        self.result_label.setText(f"Saved {_n(len(todo), 'set')} to complete to {path}")

    def show_version(self, m):
        """Show this version of a disk (the others are hidden while grouping is on)."""
        it = next((x for x in self.all_items if x.id == m["id"]), None)
        if it is None or not it.version_key:
            return
        vers.choose(self.cat, it.version_key, it.path)
        self.reload()
        if not self.group_sets:
            self.set_grouping(True)
        self.select_number(it.number)
        self.result_label.setText(f"Showing #{it.number:04d} {it.file}; the other versions are hidden "
                                  "while grouping is on (nothing is deleted)")

    # -------------------------------------------------------------- favourites
    def toggle_favourite(self):
        """Star or unstar: the tune picked in the Tunes list, else the selected rows (a disk set's
        row stars all its disks)."""
        if self.filter == "music" and self.tune_view and self.stack.currentWidget() is self.tunes_table:
            idx = self.tunes_table.currentIndex()
            if idx.isValid():
                r, _ = self.tune_model.rows[self.tune_proxy.mapToSource(idx).row()]
                self._star_tunes([r])
            return
        ids = set(self.selected_ids())
        rows = [it for it in self.model.items if it.id in ids]
        if rows:
            self._star_items(rows, not all(it.favourite for it in rows))

    def _star_items(self, rows, on):
        by_id = {it.id: it for it in self.all_items}
        targets = []
        for row in rows:
            targets += [by_id[i] for i in row.members if i in by_id] if row.members else [by_id.get(row.id, row)]
        favs.set_favourite(self.cat, {favs.item_key(it.key) for it in targets}, on)
        for it in targets:
            it.favourite = on
        for row in self.set_rows:
            row.favourite = any(by_id[i].favourite for i in row.members if i in by_id)
        self.run_search()
        n = len(rows)
        self.result_label.setText(("Added to" if on else "Removed from") + f" favourites: "
                                  + (rows[0].file if n == 1 else _n(n, "item")))
        self.tv_timer.start()

    def _star_tunes(self, tunes):
        keys = {favs.tune_key(r) for r in tunes}
        on = not keys <= self.tune_model.starred
        favs.set_favourite(self.cat, keys, on)
        self.tune_model.starred = {k for k in favs.load(self.cat) if k[0] == "tune"}
        if self.fav_tunes_btn.isChecked():
            self._fill_tunes(self.search.edit.text().strip())
        else:
            self.tune_model.refresh()
        self.result_label.setText(("Added to" if on else "Removed from") + " favourite tunes: "
                                  + TuneModel.title(tunes[0]))
        self.tv_timer.start()

    def _row_clicked(self, index):
        """A click on a row's star stars or unstars it."""
        if index.column() != 0:
            return
        pos = self.table.viewport().mapFromGlobal(QCursor.pos())
        if star_rect(self.table.visualRect(index)).adjusted(-4, -4, 4, 4).contains(pos):
            it = self.model.items[index.row()]
            self._star_items([it], not it.favourite)

    def _tune_clicked(self, index):
        """A click on a tune's note (or star) stars or unstars it."""
        if index.column() != 0:
            return
        pos = self.tunes_table.viewport().mapFromGlobal(QCursor.pos())
        if pos.x() - self.tunes_table.visualRect(index).left() <= 26:
            r, _ = self.tune_model.rows[self.tune_proxy.mapToSource(index).row()]
            self._star_tunes([r])

    def _update_turboview(self):
        """Write TurboView's copy of the catalogue (with the favourites), in the background."""
        if self.tv_worker is not None or self.pic_worker is not None or self.worker is not None:
            self.tv_timer.start()          # busy: try again shortly
            return
        self.tv_worker = TurboViewWorker(self.db_path)
        self.tv_worker.finished.connect(lambda: setattr(self, "tv_worker", None))
        self.tv_worker.start()

    def keep_copy(self, m):
        """Keep this copy of a duplicate disk: it is shown, the others become spares."""
        it = next((x for x in self.all_items if x.id == m["id"]), None)
        if it is None or not it.dup_key:
            return
        dupes.choose(self.cat, it.dup_key, it.path)
        self.reload()
        self.select_number(it.number)
        self.result_label.setText(f"Keeping #{it.number:04d} {it.file}; the other "
                                  f"cop{'y is' if it.copies == 2 else 'ies are'} now spare "
                                  f"(nothing is deleted)")

    def _missing_emulator(self, title):
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Icon.Information)
        box.setText("No Amiga emulator was found.")
        box.setInformativeText("TurboCAT starts disks in Amiberry or FS-UAE. Check setup shows how to "
                               "install one on this computer.")
        go = box.addButton("Check setup…", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Close)
        box.exec()
        if box.clickedButton() is go:
            self.check_setup()

    def check_setup(self):
        dlg = SetupDialog(self, on_identify=self.identify_online)
        dlg.exec()
        missing = sorted(c.name for c in dlg.checks if c.status != setupcheck.OK and c.important)
        self.cat.set_meta("setup_seen", missing)
        self._show_setup_status(dlg.feats)
        dlg.deleteLater()

    def setup_features(self, checks):
        try:
            imp = setupcheck.impact(self.cat)
        except Exception:
            imp = {}
        return setupcheck.features(checks, imp, emulator.find_kickstarts())

    def _show_setup_status(self, feats):
        """The toolbar's Setup button: a green, amber or red mark, and what isn't working on hover."""
        state = setupcheck.overall(feats)
        self.setup_btn.setIcon(QIcon(icon({setupcheck.OK: "ok", setupcheck.PARTIAL: "warning"}.get(
            state, "problem"), 16)))
        gaps = [f for f in feats if f.status != setupcheck.OK]
        self.setup_btn.setToolTip(
            "Everything works on this computer." if not gaps else
            "Not everything works yet:\n" + "\n".join(f"• {f.name}: {f.effect}" for f in gaps)
            + "\n\nClick for what to install.")

    def _setup_on_start(self):
        """Once, if something important is missing (and again if what is missing changes)."""
        try:
            checks = setupcheck.run(music_versions=music.versions())
        except Exception:
            return
        self._show_setup_status(self.setup_features(checks))
        missing = sorted(c.name for c in checks if c.status != setupcheck.OK and c.important)
        if missing and missing != self.cat.get_meta("setup_seen"):
            self.check_setup()

    def show_about(self):
        dlg = AboutDialog(self, self.cat, self.db_path)
        dlg.exec()
        dlg.deleteLater()      # don't leave it to Python's shutdown (that crashed on exit)

    def play_selected(self):
        """Double-click / Ctrl+P: a tune on its own plays in TurboCAT's player; disks start in
        the emulator."""
        ids = self.selected_ids()
        chosen = [it for it in self.model.items if it.id in set(ids)]
        ids = self._expand(ids)
        if chosen and all(it.type == "Module" for it in chosen):
            rows, labels = [], []
            for it in chosen:
                for r in self.cat.db.execute("SELECT * FROM music WHERE key=? ORDER BY rowid", (it.key,)):
                    rows.append(r)
                    labels.append(f"#{it.number:04d}")
            if rows:
                self.player_bar.play(rows, 0, labels=labels)
            return
        if len(chosen) == 1 and self.details.item is chosen[0] and self.details.play_ids:
            if not self.details.play_btn.isEnabled():       # an empty file with no good copy
                self.result_label.setText(self.details.play_btn.toolTip())
                return
            ids = self.details.play_ids                     # e.g. a good copy of an empty coverdisk
        self.play_in_emulator(ids)

    def play_in_emulator(self, ids=None):
        """Start the selected disks in Amiberry or FS-UAE (a single disk brings its whole set)."""
        ids = ids or self.selected_ids()
        if not ids:
            return
        if self.emulators is None:
            self.emulators = emulator.find_emulators()
        if not self.emulators:
            self._missing_emulator("Play in emulator")
            return
        dlg = PlayDialog(self, self.cat, ids, self.emulators)
        dlg.exec()

    def start_turboview(self):
        """Boot an emulated A1200 from the TurboView folder, with the collection mounted."""
        folder = self.cat.get_meta("turboview_dir") or turboview.default_folder()
        if not turboview.install(folder) or not os.path.exists(os.path.join(folder, "TurboCAT.cat")):
            missing = "the TurboView program" if not os.path.exists(os.path.join(folder, "TurboView")) \
                else "the catalogue (it is written after the next look through the disks)"
            QMessageBox.information(self, "TurboView", f"TurboView can't start yet: {missing} "
                                    f"is not in {folder}.")
            return
        if self.emulators is None:
            self.emulators = emulator.find_emulators()
        emu = self.cat.get_meta("emulator", "amiberry")
        if emu not in (self.emulators or {}):
            emu = next(iter(self.emulators or {}), None)
        if emu is None:
            self._missing_emulator("TurboView")
            return
        rom = emulator.find_kickstarts().get("A1200")
        cmd = emulator.turboview_command(emu, self.emulators[emu], rom, folder,
                                         turboview.roots_with_volumes(self.cat),
                                         display=self.cat.get_meta("emulator_display", "fullscreen"))
        emulator.launch(cmd)

    def play_music(self, rows, index):
        it = next((x for x in self.model.items if x.id == self.current_id), None)
        self.player_bar.play(rows, index, f"#{it.number:04d}" if it else "")

    def copy_to_gotek(self, ids=None):
        ids = ids or self._expand(self.selected_ids())
        if not ids:
            return
        GotekDialog(self, self.cat, self.db_path, ids).exec()

    def _select_row(self, row):
        self.table.setCurrentIndex(self.model.index(row, 0))
        self.table.scrollTo(self.model.index(row, 0), QAbstractItemView.ScrollHint.EnsureVisible)

    def select_number(self, number):
        """Select item #number, clearing the search if it is filtered out (used by links)."""
        for attempt in range(3):
            for row, it in enumerate(self.model.items):
                if it.number == number:
                    self._select_row(row)
                    return
            if self.group_sets and any(it.number == number for it in self.all_items
                                       if it.id in self.member_of or it.version_of):
                self.set_grouping(False)       # a disk of a set: show the disks one per row
                continue
            # Not on show: clear the search and chips; a hidden spare copy is in Duplicates.
            self.filter = "all" if attempt == 0 else "dups"
            self.chips[self.filter][0].setChecked(True)
            self.search.edit.clear()
            self.run_search()

    def set_filter(self, key):
        self.filter = key
        self.chips[key][0].setChecked(True)
        self.run_search()

    def _fill_chips(self, matched, everything=None):
        """Show each chip's count within the current search; hide empty ones.
        matched: what the list shows (spares hidden); everything: spares too."""
        for key, (b, label) in self.chips.items():
            hits = [it for it in matched if FILTER_TEST[key](it)
                    and (key == "empty" or it.status != "empty")]   # empty files: only under Empty
            if key == "dups":
                n = len({it.dup_key for it in (everything or matched) if it.copies > 1})
                b.setText(f"{label}  {n:,}")
            else:
                n = len(hits)
                b.setText(f"{label}  {n:,}")
            b.setVisible(key in ("all", self.filter) or n > 0)

    def focus_search(self):
        self.search.edit.setFocus()
        self.search.edit.selectAll()

    # -------------------------------------------------------------- scanning
    def scan_folder(self):
        start = (self.cat.scan_roots() or [os.path.expanduser("~")])[0]
        folder = QFileDialog.getExistingDirectory(self, "Scan a folder of Amiga disk images", start)
        if folder:
            sel = self.cat.selection()          # ticks it in Scan folders, even if it was left out
            sel.tick(folder)
            self.cat.save_selection(sel)
            self._start_scan([folder], f"Scanning {folder}…")

    def manage_scan_folders(self):
        """File > Scan folders…: change which folders are scanned, then scan any added back."""
        if self.worker is not None:
            self.result_label.setText("Wait for the scan to finish, then change the scan folders.")
            return
        dlg = ScanFoldersDialog(self, self.cat)
        dlg.exec()
        if not dlg.changed:
            return
        self.reload()
        if dlg.rescan:
            self.rescan()                      # unchanged files are skipped, so this is quick
        else:
            self.result_label.setText("Scan folders saved.")

    def rescan(self):
        roots = self.cat.scan_roots()
        if not roots:
            self.scan_folder()
            return
        self._start_scan(None, f"Rescanning {len(roots)} folder{'s' if len(roots) > 1 else ''}…")
        self.scan_bar.setToolTip("Rescanning:\n" + "\n".join(roots))

    def make_repaired_copy(self, media_id=None):
        """Disk > Make repaired copy…: say what would be done, ask, then build it."""
        if self.worker is not None:
            self.result_label.setText("Wait for the scan to finish, then try again.")
            return
        ids = [media_id] if media_id else self._expand(self.selected_ids())
        p = next((x for x in (repair.plan(self.cat, i) for i in ids) if x), None)
        if p is None:
            QMessageBox.information(self, "Make repaired copy",
                                    "None of the selected disks has damaged files that TurboCAT can "
                                    "put back. (It can only rebuild AmigaDOS floppy disks.)")
            return
        if not p.usable(with_unsure=True):
            QMessageBox.information(
                self, "Make repaired copy",
                f"#{p.number:04d} can't be repaired from your collection: none of its damaged files "
                "are on your other disks.")
            return
        ask = RepairDialog(self, p)
        if ask.exec() != QDialog.DialogCode.Accepted:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            res = repair.build(self.cat, p, with_unsure=ask.with_unsure(), mark=ask.mark())
        except Exception as ex:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Make repaired copy",
                                f"The repaired copy wasn't made: {ex}\n\nNothing was written, and your "
                                "original is unchanged.")
            return
        QApplication.restoreOverrideCursor()
        self._start_scan([repair.REPAIRED_DIR], "Adding the repaired copy to the catalogue…")
        self.result_label.setText(
            f"Made {os.path.basename(res.path)}: {len(res.restored)} file"
            f"{'s' if len(res.restored) != 1 else ''} put back"
            + (f", {len(res.missing)} still missing" if res.missing else "")
            + f" · in {repair.REPAIRED_DIR}")

    def _save_missing(self, results):
        """Save the files the repaired copies still lack, as a spreadsheet to work from."""
        import csv
        path, _ = QFileDialog.getSaveFileName(self, "Save the list of missing files",
                                              os.path.expanduser("~/TurboCAT missing files.csv"),
                                              "Spreadsheet (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["Disk", "Missing file", "Size (bytes)", "Repaired copy"])
            for r in results:
                for x in r.missing:
                    w.writerow([r.original, x.path, x.size, os.path.basename(r.path)])
        self.result_label.setText(f"Saved the missing files to {path}")

    def fix_all(self):
        """Fix all…: rebuild every damaged disk that files on other disks can fix, and read again
        those a newly installed helper program can read. Shows what it will do and asks first."""
        if self.worker is not None or getattr(self, "repairer", None) is not None:
            return
        ids = set(self._expand([it.id for it in self.model.items if can_fix(it)]))
        disks = [it for it in self.all_items if it.id in ids and can_fix(it)]
        recheck = [it for it in disks if any(here for _, _, here in it.fixable)]
        plans = list(repair.plan_all(self.cat, [it.id for it in disks
                                                if it.rebuild and it.rebuild[0]]).values())
        plans = [p for p in plans if p.usable()]
        if not plans and not recheck:
            return
        per = 0.6                                   # seconds per disk, measured on a MacBook

        def about(n):
            secs = n * per
            return ("a few seconds" if secs < 10 else f"about {int(secs) + 1} seconds" if secs < 60
                    else self._about(secs))
        dlg = FixAllDialog(self, plans, recheck, about)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        chosen, files = dlg.chosen(), [it.path for it in recheck]
        if not chosen:
            if files:
                self._start_scan(None, "Reading them again…", files=files)
            return
        prog = QProgressDialog("Getting ready…", "Stop", 0, len(chosen), self)
        prog.setWindowTitle("Fixing damaged disks")
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(0)
        prog.setMinimumWidth(520)
        started = time.monotonic()
        self.cat.add_scan_roots([repair.REPAIRED_DIR])     # so a Rescan finds them, whatever happens
        w = self.repairer = RepairWorker(self.db_path, chosen, dlg.mark())

        def step(done, total, name):
            prog.setValue(done)
            left = ""
            if done:
                secs = (time.monotonic() - started) / done * (total - done)
                left = " · " + ("a few seconds left" if secs < 10 else
                                f"about {int(secs) + 1} seconds left" if secs < 60 else
                                self._about(secs) + " left")
            prog.setLabelText(f"Repairing {done + 1} of {total}{left}\n{name}")

        def finished(made, failed):
            prog.setValue(len(chosen))
            prog.close()
            self.repairer = None
            if getattr(self, "closing", False):
                return                  # closing: what's made is on disk; the next scan adds it
            if made or files:
                self._start_scan(None, "Adding the repaired copies to the catalogue…",
                                 files=[r.path for r in made] + files)
            stopped = len(made) + len(failed) < len(chosen)
            short = [r for r in made if r.missing]
            self.result_label.setText(
                f"Made {_n(len(made), 'repaired copy')}".replace("copys", "copies")
                + (f" · {len(short)} still missing files (marked [b])" if short else "")
                + (f" · {len(failed)} couldn't be made" if failed else "")
                + (" · stopped: the rest were left" if stopped else "")
                + f" · in {repair.REPAIRED_DIR}")
            lines = [f"Made {_n(len(made), 'repaired copy')}.".replace("copys", "copies")]
            if short:
                lines.append(f"\n{len(short)} of them are still missing files, because those files "
                             "aren't anywhere in your collection. They're marked [b]:")
                for r in short[:8]:
                    names = ", ".join(x.name for x in r.missing[:4]) + (" …" if len(r.missing) > 4 else "")
                    disk = os.path.splitext(r.original)[0]
                    disk = disk if len(disk) <= 50 else disk[:49] + "…"
                    lines.append(f"   {disk}: {names}")
                if len(short) > 8:
                    lines.append(f"   … and {len(short) - 8} more (Save list… has them all)")
                lines.append("\n" + repair.FINISH_IT)
            if stopped:
                lines.append("Stopped: the rest were left as they were.")
            if failed:
                lines.append(f"\n{len(failed)} couldn't be made, and nothing was written for them:")
                lines += [f"   #{p.number:04d} {p.source_file}: {why}" for p, why in failed[:15]]
            lines.append(f"\nThey're in {repair.REPAIRED_DIR}, and are being added to the catalogue now. "
                         "Your original disk images haven't been changed.")
            box = QMessageBox(QMessageBox.Icon.Warning if failed else QMessageBox.Icon.Information,
                              "Fixing damaged disks", "\n".join(lines), parent=self)
            save = box.addButton("Save list of missing files…", QMessageBox.ButtonRole.ActionRole) \
                if short else None
            box.addButton(QMessageBox.StandardButton.Ok)
            box.exec()
            if save is not None and box.clickedButton() is save:
                self._save_missing(short)

        w.step.connect(step)
        w.done.connect(finished)
        prog.canceled.connect(lambda: setattr(w, "stop_wanted", True))
        w.start()

    def recheck_items(self, ids=None):
        """Disk > Recheck: read the chosen items again, and look in their folders for disks
        replaced, added or deleted, without rescanning every folder."""
        ids = ids if ids is not None else self._expand(self.selected_ids())
        files = []
        for i in ids:
            m = self.cat.media_by_id(i)
            while m is not None and m["parent_id"]:
                m = self.cat.media_by_id(m["parent_id"])
            if m is not None and m["source"] not in files:
                files.append(m["source"])
        if not files:
            return
        folders = sorted({os.path.dirname(f) for f in files})
        what = (os.path.basename(files[0]) if len(files) == 1 else f"{len(files)} files")
        self.recheck_focus = files
        self._start_scan(None, f"Rechecking {what}…", files=files)
        self.scan_bar.setToolTip("Rechecking, and looking for new, changed and deleted files in:\n"
                                 + "\n".join(folders))

    def _start_scan(self, folders, text, files=None):
        if self.worker is not None:
            return
        self.hide_bar.stop()
        self.scan_text.setText(text)
        self.scan_file.setText("")
        self.bar_mode = "scan"
        self.scan_busy.setRange(0, 0)          # busy until the first progress report
        self.read_started = None
        self.read_file = None            # the file being read: (bytes before it, its size, started)
        self.sub_row.hide()
        self.scan_busy.show()
        self.stop_btn.show()
        self.stop_btn.setEnabled(True)
        self.scan_bar.show()
        self.scan_btn.setEnabled(False)
        self.act_scan.setEnabled(False)
        self.rescan_btn.setEnabled(False)
        self.act_rescan.setEnabled(False)
        self.details.recheck_btn.setEnabled(False)
        self.found_count = 0
        self.stop_pictures()
        self.worker = ScanWorker(self.db_path, folders, files)
        self.rechecking = files is not None
        self.worker.line.connect(self._scan_line)
        self.worker.step.connect(self._scan_step)
        self.worker.big_found.connect(self._ask_big)
        self.worker.done.connect(self._scan_done)
        self.worker.failed.connect(self._scan_failed)
        self.worker.finished.connect(self._scan_finished)
        self.worker.start()
        self.live.start()

    def _stop_clicked(self):
        if self.bar_mode == "pictures":
            if self.pic_worker is not None:
                self.pic_worker.stop_wanted = True
                self.stop_btn.setEnabled(False)
                self.scan_text.setText("Stopping after the current disk…")
                self.scan_file.setText("")
        else:
            self.stop_scan()

    def stop_scan(self):
        if self.worker is not None:
            self.worker.stop_wanted = True
            self.stop_btn.setEnabled(False)
            self.scan_text.setText("Stopping after the current file…")
            self.scan_file.setText("")

    def _scan_line(self, text):
        if text.startswith("#"):
            self.found_count += 1

    @staticmethod
    def _about(seconds):
        """'less than a minute', 'about 5 min', 'about 1 h 20 min'."""
        if seconds < 60:
            return "less than a minute"
        minutes = int(seconds // 60) + 1
        if minutes < 90:
            return f"about {minutes} min"
        return f"about {minutes // 60} h {minutes % 60} min"

    @classmethod
    def _time_left(cls, seconds):
        return cls._about(seconds) + " left"

    def _ask_big(self, big, rate):
        """Before a scan reads them: list the big archives found, say how long each will take,
        and let the user untick any to leave for now."""
        worker = self.worker
        if worker is None:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Big archives found")
        v = QVBoxLayout(dlg)
        v.setContentsMargins(24, 20, 24, 16)
        v.setSpacing(12)
        n = len(big)
        head = QLabel(f"{'These archives are' if n > 1 else 'This archive is'} big")
        head.setFont(ui_font(16, QFont.Weight.DemiBold))
        v.addWidget(head)
        intro = QLabel(
            f"TurboCAT opens every disk and archive inside {'an archive' if n > 1 else 'it'}, so "
            f"reading {'one this big' if n > 1 else 'it'} takes minutes, and the rest of the scan "
            f"waits until it is done. Untick any you'd rather leave for now: they are left out of "
            f"the catalogue this time, and the next scan asks again. You can stop a scan at any "
            f"time; an archive stopped part way through is left out too.")
        intro.setWordWrap(True)
        intro.setFixedWidth(560)                 # so its height is worked out for this width
        v.addWidget(intro)
        boxes = QWidget()
        bl = QVBoxLayout(boxes)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(6)
        checks = []
        for path, kind, size in big:
            cb = QCheckBox(f"{os.path.basename(path)}  ·  {size / (1 << 20):,.0f} MB  ·  "
                           f"{self._about(size / rate)}")
            cb.setChecked(True)
            cb.setToolTip(path)
            bl.addWidget(cb)
            checks.append((cb, path, size))
        if n > 8:
            area = QScrollArea()
            area.setWidget(boxes)
            area.setWidgetResizable(True)
            area.setMinimumHeight(220)
            v.addWidget(area)
        else:
            v.addWidget(boxes)
        total = QLabel()
        total.setObjectName("muted")
        v.addWidget(total)

        def count():
            ticked = [sz for cb, _p, sz in checks if cb.isChecked()]
            total.setText(f"Ticked: {len(ticked)} of {n}, {self._about(sum(ticked) / rate)} to read"
                          if ticked else "None ticked: all of them are left for now")
        for cb, _p, _s in checks:
            cb.toggled.connect(lambda _=False: count())
        count()
        row = QHBoxLayout()
        row.addStretch(1)
        skip = QPushButton("Leave them all for now" if n > 1 else "Leave it for now")
        go = QPushButton("Scan the ticked ones" if n > 1 else "Scan it")
        go.setObjectName("primary")
        go.setDefault(True)
        skip.clicked.connect(dlg.reject)        # closing the window leaves them too
        go.clicked.connect(dlg.accept)
        row.addWidget(skip)
        row.addWidget(go)
        v.addLayout(row)
        ok = dlg.exec() == QDialog.DialogCode.Accepted
        worker.answer_big([p for cb, p, _s in checks if ok and cb.isChecked()])

    def _scan_step(self, phase, done, total, done_bytes, total_bytes, path):
        if self.worker is None or self.worker.stop_wanted:
            return
        if phase.startswith("inside"):
            self._inside_step(phase, done, total, done_bytes, total_bytes, path)
            return
        if phase == "reading":
            self.read_file = (done, total, done_bytes, total_bytes, time.monotonic())
            self.sub_row.hide()
        self.scan_busy.setRange(0, 1000)
        if phase == "checking":
            self.scan_busy.setValue(int(1000 * done / total) if total else 0)
            self.scan_text.setText(f"Looking for new and changed files… {done:,} of {total:,}")
        else:
            if self.read_started is None:
                self.read_started = (time.monotonic(), done_bytes)
            if not total:
                self.scan_busy.setValue(1000)
                self.scan_text.setText("Nothing new or changed")
            else:
                frac = done_bytes / total_bytes if total_bytes else done / total
                self.scan_busy.setValue(int(1000 * frac))
                text = f"Reading {min(done + 1, total):,} of {total:,} new or changed · {frac:.0%}"
                t0, b0 = self.read_started
                elapsed = time.monotonic() - t0
                if elapsed >= 3 and done_bytes > b0 and done < total:
                    rate = (done_bytes - b0) / elapsed
                    text += " · " + self._time_left((total_bytes - done_bytes) / rate)
                self.scan_text.setText(text)
        # "outer.zip › inner.zip › disk.adf": the file, then where it has got to inside it
        name = " › ".join(os.path.basename(x.rstrip("/")) for x in path.split(" › ")) if path else ""
        fm = QFontMetrics(self.scan_file.font())
        self.scan_file.setText(fm.elidedText(name, Qt.TextElideMode.ElideMiddle,
                                             max(40, self.scan_file.width())))
        self.scan_file.setToolTip(path)

    def _inside_step(self, phase, done, total, file_done, file_size, path):
        """Progress inside one file: the main bar moves on through it, and for a big one (or
        one that is taking a while) a second bar shows how far into it the scan has got."""
        if self.read_file is None:
            return
        i, n, before, all_bytes, started = self.read_file
        self._scan_step_main(i, n, before + file_done, all_bytes)
        outer, _, inner = path.partition(" › ")
        name = os.path.basename(outer)
        elapsed = time.monotonic() - started
        if file_size < BIG_ARCHIVE // 4 and elapsed < 3:
            return
        frac = file_done / file_size if file_size else 0
        self.sub_meter.setValue(int(1000 * frac))
        if phase == "inside-load":
            self.sub_meter.setValue(int(1000 * done / total) if total else 0)   # how much has loaded
            self.sub_text.setText(f"Loading {name}: {done:,} of {total:,} MB")
        else:
            what = "files listed" if phase == "inside-read" else "opened"
            self.sub_text.setText(f"Inside {name}: {done:,} of {total:,} {what}")
        left = ""
        if elapsed >= 5 and frac > 0.02:
            left = self._time_left(elapsed * (1 - frac) / frac) + " for this file"
        self.sub_left.setText(left)
        self.sub_row.show()
        inner_name = " › ".join(os.path.basename(x.rstrip("/")) for x in inner.split(" › ")) if inner else name
        fm = QFontMetrics(self.scan_file.font())
        self.scan_file.setText(fm.elidedText(inner_name, Qt.TextElideMode.ElideMiddle,
                                             max(40, self.scan_file.width())))
        self.scan_file.setToolTip(path)

    def _scan_step_main(self, done, total, done_bytes, total_bytes):
        """The main bar and its words, part way through a file."""
        frac = done_bytes / total_bytes if total_bytes else 0
        self.scan_busy.setRange(0, 1000)
        self.scan_busy.setValue(int(1000 * frac))
        text = f"Reading {min(done + 1, total):,} of {total:,} new or changed · {frac:.0%}"
        if self.read_started is not None:
            t0, b0 = self.read_started
            elapsed = time.monotonic() - t0
            if elapsed >= 3 and done_bytes > b0:
                rate = (done_bytes - b0) / elapsed
                text += " · " + self._time_left((total_bytes - done_bytes) / rate)
        self.scan_text.setText(text)

    def _scan_done(self, s):
        if s.get("stopped"):
            msg = f"Scan stopped. {self.found_count:,} new or changed item(s) were added first."
        else:
            if getattr(self, "rechecking", False):
                bits = [f"{s.get('scanned', 0):,} read again or new",
                        f"{s.get('skipped', 0):,} other file{'' if s.get('skipped', 0) == 1 else 's'} "
                        f"in the folder unchanged"]
            else:
                bits = [f"{s.get('scanned', 0):,} new or changed", f"{s.get('skipped', 0):,} unchanged"]
            if s.get("removed"):
                bits.append(f"{len(s['removed']):,} removed (files deleted)")
            if s.get("missing"):
                bits.append(f"{len(s['missing'])} folder(s) not found")
            if s.get("left_out"):
                n = len(s["left_out"])
                bits.append(f"{n} folder{'s' if n > 1 else ''} left out (File > Scan folders)")
            msg = ("Recheck finished: " if getattr(self, "rechecking", False) else "Scan finished: ") \
                + ", ".join(bits) + "."
            if s.get("held_back"):
                n = len(s["held_back"])
                msg += (f" {n} big archive{'s were' if n > 1 else ' was'} left for now; "
                        f"the next scan offers {'them' if n > 1 else 'it'} again.")
        self._show_result(msg)

    def _scan_failed(self, err):
        self._show_result(f"Scan failed: {err}")

    def _show_result(self, msg):
        self.sub_row.hide()
        self.scan_text.setText(msg)
        self.scan_file.setText("")
        self.scan_busy.hide()
        self.stop_btn.hide()
        self.reload()
        if getattr(self, "rechecking", False) and getattr(self, "recheck_focus", None):
            self._select_paths(self.recheck_focus)    # back on what was rechecked (it has new ids)
            self.recheck_focus = None

    def _select_paths(self, paths):
        """Select the row (a disk, or the set it belongs to) for the first of these files."""
        paths = set(paths)
        by_id = {it.id: it for it in self.all_items}
        for row, it in enumerate(self.model.items):
            mine = [it.path] + [by_id[i].path for i in (it.members or []) if i in by_id]
            if paths & set(mine):
                self._select_row(row)
                return
        self.hide_bar.start()

    def _live_reload(self):
        if self.found_count:
            self.reload()

    def _scan_finished(self):
        self.live.stop()
        self.worker = None
        self.scan_btn.setEnabled(True)
        self.act_scan.setEnabled(True)
        self.rescan_btn.setEnabled(True)
        self.act_rescan.setEnabled(True)
        self.details.recheck_btn.setEnabled(True)
        if not self.closing:
            self.find_pictures()

    # -------------------------------------------------------------- pictures
    def find_pictures(self, online=None, asked=False):
        """Look for pictures on new items (and online, once the user has agreed to that).
        asked: the user asked for this, so the progress bar shows from the start."""
        if self.pic_worker is not None or self.worker is not None or self.closing:
            return
        if online is None:
            online = bool(self.cat.get_meta("online_pictures", False))
        self.pic_asked = asked
        self.pic_shown = False
        if asked:
            self._pic_bar("Getting ready…", 0, 0, "")
        self.pic_worker = PictureWorker(self.db_path, online)
        self.pic_worker.progress.connect(self._pic_progress)
        self.pic_worker.done.connect(self._pic_done)
        self.pic_worker.failed.connect(self._pic_failed)
        self.pic_worker.finished.connect(self._pic_finished)
        self.pic_worker.finished.connect(self._pic_finished_then)
        self.online_btn.setEnabled(False)
        self.act_online.setEnabled(False)
        self.pic_worker.start()
        self.pic_refresh.start()

    def identify_online(self):
        """Tools > Identify disks online: download the TOSEC list once (asking first)."""
        if not self.cat.get_meta(identify.TOSEC_CONSENT, False):
            box = QMessageBox(self)
            box.setWindowTitle("Identify disks online")
            box.setIcon(QMessageBox.Icon.Question)
            box.setText("Identify disks by their checksums?")
            box.setInformativeText(
                f"TurboCAT downloads TOSEC's catalogue of disks from tosecdev.org (about "
                f"{identify.PACK_SIZE_MB} MB, once, then about twice a year when TOSEC publishes a new "
                "one), keeps only its 68 lists of Amiga floppy disks (about 35 MB, close to 100,000 "
                "disks: games, applications, magazine coverdisks, demos, diskmags…) and looks up each "
                "disk's checksum in them. A disk called Disk1.adf can then show its proper name, such "
                "as Superfrog (1993)(Team 17)(Disk 1 of 4), and coverdisks their magazine, issue and "
                "date.\n\nOnly the lists are downloaded: nothing about your disks is sent anywhere. "
                "Your files are not renamed.")
            box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
            box.button(QMessageBox.StandardButton.Yes).setText("Download the lists")
            if box.exec() != QMessageBox.StandardButton.Yes:
                return
            self.cat.set_meta(identify.TOSEC_CONSENT, True)
        elif identify.have_tosec() and not identify.tosec_is_old():
            self.reload()
            n = sum(1 for it in self.all_items if it.tosec_name)
            self.result_label.setText(f"{n:,} disks identified by their checksums (the list is up to date)")
            return
        if self.pic_worker is not None:          # after the search that is running now
            self.identify_pending = True
            return
        self.find_pictures(asked=True)

    def rename_to_tosec(self):
        """Tools > Rename files to their proper names: show every rename, do them on request."""
        plan = identify.rename_plan([it for it in self.all_items if not it.members])
        if not plan:
            QMessageBox.information(self, "Rename files", "There is nothing to rename: every identified "
                                    "disk's file already has its proper name." if any(
                                        it.tosec_name for it in self.all_items) else
                                    "No disks have been identified yet. Tools › Identify disks online… "
                                    "finds their proper names first.")
            return
        dlg = RenameDialog(self, plan)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        done, failed = dlg.apply(self.cat)
        self.reload()
        msg = f"Renamed {_n(done, 'file')}" + (f"; {failed} couldn't be renamed" if failed else "") + \
              f" · the old and new names are listed in {RenameDialog.LOG}"
        self.result_label.setText(msg)

    def find_online(self):
        if not self.cat.get_meta("online_pictures", False):
            box = QMessageBox(self)
            box.setWindowTitle("Find pictures online")
            box.setIcon(QMessageBox.Icon.Question)
            box.setText("Look up pictures online for disks that have none of their own?")
            box.setInformativeText(
                "TurboCAT matches each disk's title against the libretro-thumbnails collection "
                "(the pictures RetroArch uses), on GitHub, and downloads a title screen when the "
                "name matches exactly. For magazine coverdisks it fetches the cover of the issue "
                "from the magazine scans on the Internet Archive (only the magazine's name is "
                "searched for).\n\nThese pictures belong to their publishers. They "
                "are kept on this computer for your own use. After this, new disks are looked up "
                "automatically after each scan.")
            box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
            box.button(QMessageBox.StandardButton.Yes).setText("Look online")
            if box.exec() != QMessageBox.StandardButton.Yes:
                return
            self.cat.set_meta("online_pictures", True)
        if self.pic_worker is not None:      # finish the disk search first, then go online
            self.pic_worker.online = True
            self.pic_asked = True
            if not self.pic_shown:
                self._pic_bar("Finishing the search on your disks, then going online…", 0, 0, "")
            return
        self.find_pictures(online=True, asked=True)

    def stop_pictures(self):
        if self.pic_worker is not None:
            self.pic_worker.stop_wanted = True
            self.pic_worker.wait(30000)

    def _pic_note(self, text):
        self.foot_left.setText(text)

    def _pic_bar(self, text, i, n, what):
        """Show the picture search in the progress bar under the search box (with Stop)."""
        self.bar_mode = "pictures"
        self.pic_shown = True
        self.hide_bar.stop()
        if n:
            self.scan_busy.setRange(0, n)
            self.scan_busy.setValue(i)
        else:
            self.scan_busy.setRange(0, 0)       # moving bar: working, length unknown
        self.scan_text.setText(text)
        self.scan_file.setText(what)
        self.scan_bar.setToolTip("")
        self.stop_btn.show()
        self.stop_btn.setEnabled(not (self.pic_worker and self.pic_worker.stop_wanted))
        self.scan_bar.show()

    def _pic_progress(self, phase, i, n, what=""):
        if phase == "disk-inside":
            # a big item (an archive of a thousand disks): how far through what's inside it
            outer, _, inner = what.partition("\t")
            if not self.pic_shown:
                self._pic_bar("Looking for pictures and music on disks…", 0, 0, outer)
            self.sub_meter.setValue(int(1000 * i / n) if n else 0)
            self.sub_text.setText(f"Inside {outer}: {i:,} of {n:,}")
            self.sub_left.setText("")
            fm = QFontMetrics(self.scan_file.font())
            self.scan_file.setText(fm.elidedText(f"{outer} › {inner}", Qt.TextElideMode.ElideMiddle,
                                                 max(40, self.scan_file.width())))
            self.sub_row.show()
            return
        if phase != "identify":
            self.sub_row.hide()
        if phase == "identify":
            size = f"{i / 1024:.1f} of {n / 1024:.1f} MB" if n else ""
            if what == "tosec":
                self._pic_bar("Getting TOSEC's lists of Amiga disks from tosecdev.org…", i, n,
                              size or f"about {identify.PACK_SIZE_MB} MB, once")
            else:
                self._pic_bar("Getting the TOSEC list of Amiga disks from GitHub…", i, n,
                              size or "libretro-database, about 12 MB, once")
            return
        if phase == "online" and not n:
            self._pic_bar("Getting the list of pictures from GitHub…", 0, 0,
                          "libretro-thumbnails, Commodore Amiga")
            return
        if not n or i >= n:
            return
        text = {"disk": "Looking for pictures and music on disks…",
                "lengths": "Measuring tunes…",
                "online": "Looking for pictures online…",
                "covers": "Looking for magazine covers on the Internet Archive…"}[phase]
        self._pic_note(f"{text} {i:,} of {n:,}")
        # Little jobs in the background stay in the footer; anything bigger, or anything the
        # user asked for, gets the progress bar.
        if self.pic_asked or self.pic_shown or phase == "online" or n >= 20:
            self._pic_bar(f"{text} {i + 1:,} of {n:,}", i, n, what)

    def _pic_done(self, res):
        bits = []
        if res["disk"]["looked"]:
            bits.append(f"{res['disk']['found']:,} of {res['disk']['looked']:,} new items had pictures "
                        "or icons on the disk")
        if res.get("identify_fetched"):
            bits.append(f"{res['identified']:,} disks identified by their checksums")
        if res.get("identify_error"):
            bits.append(f"TOSEC's lists couldn't be downloaded: {res['identify_error']}")
        if res.get("turboview_error"):
            bits.append(f"TurboView catalogue not written: {res['turboview_error']}")
        if "online" in res and res["online"]["looked"]:
            n, looked = res["online"]["found"], res["online"]["looked"]
            bits.append(f"{n:,} picture{'' if n == 1 else 's'} found online for "
                        f"{looked:,} disk{'' if looked == 1 else 's'} looked up")
        if res.get("covers", {}).get("looked"):
            n, looked = res["covers"]["found"], res["covers"]["looked"]
            bits.append(f"{n:,} magazine cover{'' if n == 1 else 's'} found for "
                        f"{looked:,} issue{'' if looked == 1 else 's'} with coverdisks")
        if res.get("online", {}).get("stopped") or res.get("covers", {}).get("stopped") \
                or res["disk"].get("stopped"):
            bits.insert(0, "Stopped")
        if self.pic_shown and "online" in res and not res["online"]["looked"] \
                and not res["online"].get("stopped"):
            bits.append("every disk without a picture has been looked up online already")
        self.reload()
        if bits:
            self._pic_note(" · ".join(bits))
            QTimer.singleShot(15000, self._fill_counts)
        if self.pic_shown:
            self._pic_bar_end(_cap(" · ".join(bits)) if bits else "Finished: nothing new found")

    def _pic_bar_end(self, text):
        self.sub_row.hide()
        self.scan_busy.setRange(0, 1)
        self.scan_busy.setValue(1)
        self.scan_text.setText(text)
        self.scan_file.setText("")
        self.stop_btn.hide()
        self.hide_bar.start()

    def _pic_failed(self, err):
        self._pic_note(f"Finding pictures failed: {err}")
        if self.pic_shown:
            self._pic_bar_end(f"Finding pictures failed: {err}")

    def _pic_finished_then(self):
        if getattr(self, "identify_pending", False) and not self.closing:
            self.identify_pending = False
            QTimer.singleShot(0, lambda: self.find_pictures(asked=True))

    def _pic_finished(self):
        self.pic_worker = None
        self.pic_refresh.stop()
        self.online_btn.setEnabled(True)
        self.act_online.setEnabled(True)

    def reload(self):
        """Re-read the catalogue after a scan, keeping the search and selection."""
        before = {it.id: (it.pic, it.thumb_icon) for it in self.all_items}
        self.all_items = load_items(self.cat)
        self._make_sets()
        if self.pic_worker is None:
            self._fill_counts()
        self.run_search()
        cur = next((it for it in self.model.items if it.id == self.current_id), None)
        if cur is not None and before.get(cur.id) != (cur.pic, cur.thumb_icon):
            self.details.show_item(cur)        # a picture was just found for it

    def showEvent(self, event):
        super().showEvent(event)
        if not self.widths_set:
            QTimer.singleShot(0, self._set_widths)

    def _set_widths(self):
        """Remembered column widths, or a fair share of the list's width the first time."""
        saved = self.cat.get_meta("column_widths")
        if isinstance(saved, list) and len(saved) == 4 and all(isinstance(x, int) for x in saved):
            widths = saved
        else:
            room = max(400, self.table.viewport().width() - 84 - 80 - 210)
            widths = [84, room // 2, room - room // 2, 80]
        for col, width in enumerate(widths):
            self.table.setColumnWidth(col, max(60, width))
        # Status gets the rest of the room, but never less than its pills need.
        rest = self.table.viewport().width() - sum(max(60, x) for x in widths)
        self.table.setColumnWidth(4, max(210, rest))
        self.widths_set = True

    def _busy(self):
        """What is still running in the background, in words (empty if nothing)."""
        return " and ".join(w for w, t in (("the scan", self.worker), ("the picture search", self.pic_worker),
                                           ("updating TurboView", getattr(self, "tv_worker", None)),
                                           ("the repairs", getattr(self, "repairer", None)))
                            if t is not None)

    def closeEvent(self, event):
        """Close without freezing: ask background work to stop, show that TurboCAT is closing,
        and close for real once it has (each item is saved as it is done, so nothing is lost)."""
        self.closing = True
        self.player_bar.player.stop()
        if self.tv_timer.isActive() and self.worker is None and self.pic_worker is None:
            self.tv_timer.stop()             # favourites just changed: give TurboView them first
            self._update_turboview()
        busy = self._busy()
        if not busy:
            super().closeEvent(event)
            return
        event.ignore()
        for t in (self.worker, self.pic_worker, self.tv_worker, getattr(self, "repairer", None)):
            if t is not None:
                t.stop_wanted = True
                t.finished.connect(self._close_when_idle)
        if not self.close_timer.isActive():
            self.centralWidget().setEnabled(False)
            self.menuBar().setEnabled(False)
            self.bar_mode = "closing"
            self.hide_bar.stop()
            self.scan_busy.setRange(0, 0)
            self.scan_text.setText(f"Closing: stopping {busy} first…")
            self.scan_file.setText("")
            self.stop_btn.hide()
            self.scan_bar.show()
            self.close_timer.start()

    def _close_when_idle(self):
        if self.closing and not self._busy():
            self.close_timer.stop()
            QTimer.singleShot(0, self.close)

    def _close_slow(self):
        """Still busy after a while (a huge disk image, a stalled download): offer to quit now."""
        busy = self._busy()
        if not busy:
            return
        box = QMessageBox(self)
        box.setWindowTitle(f"Closing {APP_NAME}")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(f"TurboCAT is still waiting for {busy} to stop.")
        box.setInformativeText("Quit now? Everything catalogued so far is already saved; only the "
                               "item being read at this moment would be looked at again next time.")
        quit_btn = box.addButton("Quit now", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Keep waiting", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is quit_btn and self._busy():
            sys.stdout.flush()
            os._exit(0)            # the threads can't be stopped mid-read; SQLite keeps the data safe
        elif self._busy():
            self.close_timer.start()

    def _fill_counts(self):
        st = self.cat.stats()
        self.counts.setText(f"{st['items']:,} items · {st['files']:,} files")
        last = self.cat.db.execute("SELECT MAX(scanned_at) FROM media").fetchone()[0]
        bits = []
        if last:
            bits.append("Catalogue of " + time.strftime("%-d %b %Y, %H:%M", time.localtime(last)))
        bits.append(f"{st['errors']} with problems, {st['warnings']} with warnings, "
                    f"{st['empty']} empty")
        self.foot_left.setText(" · ".join(bits))

    def run_search(self):
        text = self.search.edit.text().strip()
        if not text:
            for it in self.all_items:
                it.found = ""
            shown = self.all_items
        else:
            hits = self.cat.search_items(text)
            words = search_words(text)
            shown = []
            for it in self.all_items:
                h = hits.get(it.id)
                if h is None:
                    # Disks identified by checksum are found by their proper name too.
                    if it.tosec_name and matches(words, it.tosec_name):
                        it.found = f"identified as {it.tosec_name}"
                        shown.append(it)
                    continue
                why = list(dict.fromkeys(h["why"]))
                if h["files"]:
                    more = h["files"] - 1
                    why.insert(0, f"file {h['first_file']}"
                               + (f" and {more:,} more file{'s' if more > 1 else ''}" if more else ""))
                it.found = " · ".join(why) if why else "image file name"
                shown.append(it)
        # Spare copies of a duplicate stay out of sight, except in the Duplicates view, or when a
        # search finds the spare but not the copy kept (it was found by its own file name).
        found_ids = {it.id for it in shown}
        everything = shown
        shown = [it for it in shown if not it.spare_of or (text and it.spare_of not in found_ids)]
        self.spares_hidden = len(everything) - len(shown)
        grouped = self.group_sets and self.filter != "dups"
        self.versions_hidden = 0
        if grouped:
            # Other versions of a disk stay out of sight too (unless only they match a search).
            before = len(shown)
            shown = [it for it in shown if not it.version_of or (text and it.version_of not in found_ids)]
            self.versions_hidden = before - len(shown)
            shown = self._grouped(shown, text)
        self._fill_chips(shown, everything)
        matched = sum(1 for it in shown if it.status != "empty" or self.filter == "empty")
        test = FILTER_TEST[self.filter]
        if self.filter == "dups":
            # Each set together: the copy kept, then its spares.
            first = {}
            for it in everything:
                if it.copies > 1:
                    first[it.dup_key] = min(first.get(it.dup_key, it.number), it.number)
            shown = sorted((it for it in everything if test(it)),
                           key=lambda it: (first[it.dup_key], bool(it.spare_of), it.number))
        else:
            shown = [it for it in shown if test(it)]
        # Empty files (0 bytes: nothing to read or play) are listed under the Empty chip only
        empty_hidden = 0
        if self.filter not in ("empty", "dups"):
            before = len(shown)
            shown = [it for it in shown if it.status != "empty"]
            empty_hidden = before - len(shown)
        label = dict((k, l) for k, l, _, _ in FILTERS)[self.filter]
        if self.filter == "music":
            label = "Items with music"
        if text and self.filter != "all":
            self.result_label.setText(f"{len(shown):,} {label.lower()} among the {matched:,} "
                                      f"items that match “{text}”")
        elif text:
            self.result_label.setText(
                f"{len(shown):,} of {len(self.all_items):,} items match “{text}”")
        elif self.filter == "sets":
            self.result_label.setText(
                f"{_n(len(shown), 'disk set')} with missing or damaged disks · "
                "File › Export sets to complete… saves what each one needs")
        elif self.filter == "problems" and not text:
            spared = sum(1 for it in everything if it.status == "error" and it.good_copy
                         and not it.spare_of and (not grouped or not it.version_of))
            self.result_label.setText(
                f"Problems {len(shown):,} of {len(self.all_items):,} items" + (
                    f" · {_n(spared, 'damaged disk')} not counted: you have a good copy"
                    if spared else ""))
        elif self.filter == "empty" and not text:
            spared = sum(1 for it in everything if it.status == "empty" and it.good_copy)
            self.result_label.setText(
                f"Empty {len(shown):,} of {len(self.all_items):,} items: files of 0 bytes, nothing in them"
                + (f" · {_n(spared, 'more empty file')} not listed: you have a working copy of each"
                   if spared else ""))
        elif self.filter == "fixable":
            full = sum(1 for it in shown if it.rebuild and it.rebuild[0] == it.rebuild[1])
            part = sum(1 for it in shown if it.rebuild and 0 < it.rebuild[0] < it.rebuild[1])
            now = [it for it in shown if any(here for _, _, here in it.fixable)]
            need = sorted({pkg for it in shown for _, pkg, here in it.fixable if not here})
            bits = ([f"{full:,} can be rebuilt from files on your other disks"] if full else []) + (
                [f"{part:,} partly"] if part else []) + (
                [f"{len(now):,} can be read now that a helper program is installed"] if now else []) + (
                [f"install {', '.join(need)} for {'the rest' if (full or part or now) else 'these'} "
                 "(Help › Check setup)"] if need else [])
            self.result_label.setText(f"{_n(len(shown), 'damaged item')} can be fixed · " + " · ".join(bits))
        elif self.filter == "dups":
            sets = len({it.dup_key for it in shown})
            self.result_label.setText(
                f"{_n(sets, 'disk')} catalogued more than once · TurboCAT shows one copy of each and "
                f"hides the {_n(len(shown) - sets, 'spare')} · nothing is deleted")
        elif self.filter != "all":
            self.result_label.setText(f"{label} {len(shown):,} of {len(self.all_items):,} items")
        else:
            n_sets = sum(1 for it in shown if it.members) if grouped else 0
            self.result_label.setText(f"All items {len(shown):,}" + (
                f" · {_n(n_sets, 'disk set')} on one row each" if n_sets else "") + (
                f" · {_n(self.versions_hidden, 'other version')} hidden" if self.versions_hidden else "") + (
                f" · {_n(self.spares_hidden, 'spare copy')} hidden (see Duplicates)"
                .replace("copys", "copies") if self.spares_hidden else ""))
        if empty_hidden:
            self.result_label.setText(self.result_label.text() + f" · {_n(empty_hidden, 'empty file')} "
                                      "hidden (see Empty)")
        self.fix_btn.setVisible(self.filter == "fixable" and self.worker is None and any(
            any(here for _, _, here in it.fixable) or (it.rebuild and it.rebuild[0]) for it in shown))
        keep = set(self.selected_ids()) if self.model.items else set()
        self.model.set_items(shown)
        if shown:
            ids = [it.id for it in shown]
            cur = self.current_id
            if grouped and cur in self.member_of:
                cur = self.member_of[cur].id          # a disk of a set: select the set's row
            self._select_row(ids.index(cur) if cur in ids else 0)
            if len(keep) > 1:          # keep a multiple selection across rescans and searches
                sm = self.table.selectionModel()
                flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
                for row, i in enumerate(ids):
                    if i in keep:
                        sm.select(self.model.index(row, 0), flags)
        else:
            self.details.clear()
        music_view = self.filter == "music"
        for b in (self.view_disks, self.view_tunes):
            b.setVisible(music_view)
        self.group_btn.setVisible(not (music_view and self.tune_view) and self.filter != "dups")
        self.export_tunes_btn.setVisible(music_view and self.tune_view)
        self.fav_tunes_btn.setVisible(music_view and self.tune_view)
        if not self.all_items:
            self.message.setText(
                "The catalogue is empty.\n\nClick Scan folder… and choose the folder where you "
                "keep your Amiga disk images.")
            self.stack.setCurrentWidget(self.message)
        elif music_view and self.tune_view:
            self._fill_tunes(text)
        elif not shown and text and self.filter != "all":
            self.message.setText(f"No {label.lower()} among the items that match “{text}”.")
            self.stack.setCurrentWidget(self.message)
        elif not shown and text:
            self.message.setText(f"Nothing found for “{text}”.")
            self.stack.setCurrentWidget(self.message)
        elif not shown:
            self.message.setText(f"No {label.lower()} in the catalogue.")
            self.stack.setCurrentWidget(self.message)
        else:
            self.stack.setCurrentWidget(self.table)

    # -------------------------------------------------------------- tunes view
    def set_tune_view(self, on):
        self.tune_view = on
        (self.view_tunes if on else self.view_disks).setChecked(True)
        self.run_search()

    def _fill_tunes(self, text):
        """Every tune found, or those whose name, format, file or disk matches the search."""
        self.tune_model.starred = {k for k in favs.load(self.cat) if k[0] == "tune"}
        by_key = {}
        for it in self.all_items:
            by_key.setdefault(it.key, it)
        rows = []
        words = search_words(text)
        for key, tunes in pictures.music_by_key(self.cat).items():
            it = by_key.get(key)
            if it is None:
                continue
            for r in tunes:
                if words and not matches(words, r["title"], TuneModel.artist(r), r["file"], r["shown"],
                                         r["fmt"], it.file, it.title):
                    continue
                if self.fav_tunes_btn.isChecked() and favs.tune_key(r) not in self.tune_model.starred:
                    continue
                rows.append((r, it))
        keep = self._current_tune()
        self.tune_model.starred = {k for k in favs.load(self.cat) if k[0] == "tune"}
        self.tune_model.set_rows(rows)
        # Most Amiga modules don't record an artist: show the column only when some do.
        self.tunes_table.setColumnHidden(1, not any(TuneModel.artist(r) for r, _ in rows))
        total = sum(r["duration"] for r, _ in rows if r["duration"] and r["duration"] > 0)
        hours = f"{total / 3600:.1f} hours" if total >= 3600 else f"{total / 60:.0f} minutes"
        items = len({it.id for _, it in rows})
        what = f"{_n(len(rows), 'tune')} in {_n(items, 'item')}, {hours} of music"
        self.result_label.setText(what + (f" · matching “{text}”" if text else ""))
        if not rows:
            self.message.setText(f"No tunes match “{text}”." if text else
                                 "No music modules found yet. TurboCAT looks for them in the "
                                 "background after each scan.")
            self.stack.setCurrentWidget(self.message)
            return
        self.stack.setCurrentWidget(self.tunes_table)
        row = 0
        if keep is not None:
            for i in range(self.tune_proxy.rowCount()):
                r, _ = self.tune_model.rows[self.tune_proxy.mapToSource(self.tune_proxy.index(i, 0)).row()]
                if (r["key"], r["file"], r["offset"]) == keep:
                    row = i
                    break
        self.tunes_table.setCurrentIndex(self.tune_proxy.index(row, 0))

    def _current_tune(self):
        idx = self.tunes_table.currentIndex()
        if not idx.isValid() or not self.tune_model.rows:
            return None
        r, _ = self.tune_model.rows[self.tune_proxy.mapToSource(idx).row()]
        return (r["key"], r["file"], r["offset"])

    def _tune_row_changed(self, current, _previous):
        if not current.isValid():
            return
        _, it = self.tune_model.rows[self.tune_proxy.mapToSource(current).row()]
        if it.id != self.current_id:
            self.current_id = it.id
            self.details.show_item(it)

    def _play_tune(self, index):
        """Play the tune, then carry on down the list as it is sorted."""
        rows, labels = [], []
        for i in range(self.tune_proxy.rowCount()):
            r, it = self.tune_model.rows[self.tune_proxy.mapToSource(self.tune_proxy.index(i, 0)).row()]
            rows.append(r)
            labels.append(f"#{it.number:04d}")
        self.player_bar.play(rows, index.row(), labels=labels)

    def export_tunes(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save the list of tunes",
                                              os.path.expanduser("~/TurboCAT tunes.csv"),
                                              "Spreadsheet (*.csv)")
        if not path:
            return
        import csv
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["Tune", "Artist", "Format", "Size (bytes)", "Length", "Item", "Item file", "Where"])
            for i in range(self.tune_proxy.rowCount()):
                r, it = self.tune_model.rows[self.tune_proxy.mapToSource(self.tune_proxy.index(i, 0)).row()]
                dur = r["duration"]
                w.writerow([TuneModel.title(r), TuneModel.artist(r), r["fmt"], r["size"],
                            music.fmt_time(dur) if dur and dur > 0 else "",
                            f"#{it.number:04d}", it.path, r["shown"]])
        self.result_label.setText(f"Saved {self.tune_proxy.rowCount():,} tunes to {path}")

    def _style(self):
        c = {k: v.name() for k, v in C.items()}
        self.setStyleSheet(f"""
            #root {{ background: {c['surface']}; }}
            QLabel {{ color: {c['ink']}; }}
            QLabel#muted {{ color: {c['ink-muted']}; }}
            QLabel#message {{ color: {c['ink-muted']}; background: {c['surface']}; padding: 40px; }}
            #header {{ border-bottom: 1px solid {c['line']}; background: {c['surface']}; }}
            #footer {{ background: {c['chrome']}; border-top: 1px solid {c['line']}; }}
            #searchBox {{ border: 2px solid {c['accent']}; border-radius: 8px; background: {c['surface']}; }}
            #searchEdit {{ border: none; background: transparent; color: {c['ink']};
                           selection-background-color: {c['accent']}; }}
            QLabel#keyHint {{ color: {c['ink-muted']}; border: 1px solid {c['control-edge']};
                              border-radius: 4px; padding: 2px 6px; }}
            QLabel#buttonWords {{ color: {c['ink']}; background: transparent; }}
            QPushButton#primary QLabel#buttonWords {{ color: {c['on-accent']}; }}
            QPushButton#primary QLabel#keyHint {{ color: {c['on-accent']}; border-color: {c['on-accent']}; }}
            QLabel#buttonWords[off="true"] {{ color: {c['ink-muted']}; }}
            #panel {{ border: 1px solid {c['line']}; border-radius: 8px; background: {c['surface']}; }}
            QTableView {{ border: none; background: {c['surface']}; outline: 0; }}
            QHeaderView::section {{ background: {c['chrome']}; color: {c['ink-muted']}; border: none;
                                    border-bottom: 1px solid {c['line']}; padding: 10px 12px;
                                    border-right: 1px solid {c['row-line']}; }}
            QHeaderView::section:last {{ border-right: none; }}
            #details {{ border: 1px solid {c['line']}; border-radius: 8px; background: {c['surface']}; }}
            #detailsPage {{ background: {c['surface']}; border-radius: 8px; }}
            QLabel#section {{ color: {c['ink-muted']}; }}
            QSplitter#split::handle {{ background: transparent; }}
            #note_accent {{ background: {c['accent-tint']}; border-radius: 8px; }}
            #note_accent QLabel {{ color: {c['accent-ink']}; background: transparent; }}
            #note_warn {{ background: {c['warn-tint']}; border-radius: 8px; }}
            #note_warn QLabel {{ color: {c['warn']}; background: transparent; }}
            #note_problem {{ background: {c['problem-tint']}; border-radius: 8px; }}
            #note_problem QLabel {{ color: {c['problem']}; background: transparent; }}
            #note_neutral {{ background: {c['neutral-tint']}; border-radius: 8px; }}
            #note_neutral QLabel {{ color: {c['ink-soft']}; background: transparent; }}
            QTreeWidget {{ border: 1px solid {c['line']}; border-radius: 8px; background: {c['surface']};
                           color: {c['ink']}; outline: 0; padding: 4px 0; }}
            QTreeWidget::item {{ padding: 3px 4px; border-bottom: 1px solid {c['neutral-tint']}; }}
            QPushButton {{ color: {c['ink']}; background: {c['surface']}; border: 1px solid {c['control-edge']};
                           border-radius: 8px; padding: 0 14px; min-height: 42px; }}
            QPushButton:hover {{ background: {c['chrome']}; }}
            QPushButton:focus {{ border: 2px solid {c['accent']}; }}
            QPushButton:disabled {{ color: {c['ink-muted']}; border-color: {c['line']}; background: {c['chrome']}; }}
            QPushButton#primary {{ background: {c['accent']}; border: 1px solid {c['accent']}; color: {c['on-accent']};
                                   padding: 0 18px; min-height: 42px; }}
            QPushButton#primary:hover {{ background: {c['accent-ink']}; }}
            QPushButton#primary:disabled {{ background: {c['line']}; border-color: {c['line']};
                                            color: {c['ink-muted']}; }}
            QMenuBar {{ background: {c['chrome']}; color: {c['ink']}; border-bottom: 1px solid {c['line']};
                        padding: 2px 8px; }}
            QMenuBar::item {{ padding: 5px 10px; border-radius: 4px; background: transparent; }}
            QMenuBar::item:selected, QMenuBar::item:pressed {{ background: {c['accent-tint']}; }}
            QMenu::item:disabled {{ color: {c['ink-muted']}; }}
            QMenu::separator {{ height: 1px; background: {c['line']}; margin: 4px 8px; }}
            QMenu {{ background: {c['surface']}; color: {c['ink']}; border: 1px solid {c['line']};
                     padding: 4px; }}
            QMenu::item {{ padding: 6px 20px 6px 12px; border-radius: 4px; }}
            QMenu::item:selected {{ background: {c['accent-tint']}; color: {c['ink']}; }}
            QPushButton#chip {{ border-radius: 17px; min-height: 34px; padding: 0 14px; }}
            QPushButton#chip[hasIcon="true"] {{ padding-left: 10px; }}
            QPushButton#chip:checked {{ background: {c['accent-tint']}; border: 1px solid {c['accent']};
                                        color: {c['accent-ink']}; }}
            QPushButton#chip:focus {{ border: 2px solid {c['accent']}; }}
            #dialog {{ background: {c['surface']}; }}
            QListWidget#diskList {{ border: 1px solid {c['line']}; border-radius: 8px; background: {c['surface']};
                                   color: {c['ink']}; padding: 4px 0; outline: 0; }}
            QListWidget#diskList::item {{ padding: 3px 8px; }}
            QRadioButton {{ color: {c['ink']}; spacing: 8px; }}
            QComboBox {{ color: {c['ink']}; background: {c['surface']}; border: 1px solid {c['control-edge']};
                         border-radius: 8px; padding: 0 12px; }}
            QComboBox:focus {{ border: 2px solid {c['accent']}; }}
            QComboBox QAbstractItemView {{ color: {c['ink']}; background: {c['surface']};
                                           selection-background-color: {c['accent-tint']};
                                           selection-color: {c['accent-ink']}; }}
            QPushButton#segment {{ min-height: 28px; padding: 0 12px; border-radius: 6px; }}
            QPushButton#segment:checked {{ background: {c['accent-tint']}; border: 1px solid {c['accent']};
                                           color: {c['accent-ink']}; }}
            QTableView#tunesTable::item {{ padding: 0 8px; border-bottom: 1px solid {c['row-line']}; }}
            QTableView#tunesTable::item:selected {{ background: {c['accent-tint']}; color: {c['accent-ink']}; }}
            QPushButton#small {{ min-height: 30px; padding: 0 12px; }}
            #playerBar {{ background: {c['accent-tint']}; border-top: 1px solid {c['line']}; }}
            #playerBar QLabel {{ color: {c['accent-ink']}; }}
            QTreeWidget#tunes::item {{ padding: 3px 4px; }}
            QTreeWidget#tunes::item:selected {{ background: {c['accent-tint']}; color: {c['accent-ink']}; }}
            #scanBar {{ background: {c['accent-tint']}; border-radius: 8px; }}
            #scanBar QLabel {{ color: {c['accent-ink']}; }}
            #scanBar QLabel#scanFile {{ color: {c['ink-muted']}; }}
            QProgressBar {{ border: none; background: {c['surface']}; border-radius: 3px; max-height: 6px; }}
            QProgressBar::chunk {{ background: {c['accent']}; border-radius: 3px; }}
            QProgressBar#scanMeter {{ min-height: 10px; max-height: 10px; border-radius: 5px; }}
            QProgressBar#scanMeter::chunk {{ border-radius: 5px; }}
            QScrollBar:vertical {{ background: {c['surface']}; width: 12px; margin: 0; }}
            QScrollBar:horizontal {{ background: {c['surface']}; height: 12px; margin: 0; }}
            QScrollBar::handle:horizontal {{ background: {c['line']}; border-radius: 4px; min-width: 30px;
                                             margin: 2px; }}
            QScrollBar::handle:vertical {{ background: {c['line']}; border-radius: 4px; min-height: 30px;
                                           margin: 2px; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
            QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
        """)


def _catalogue_ready(db_path):
    """Check the catalogue before opening it. A healthy one gets a safety copy; a damaged one is
    offered its newest copy back. False if the window can't open."""
    from . import catalogue as C
    ok, why = C.check(db_path)
    if ok:
        try:
            C.make_backup(db_path)
        except Exception as ex:          # a copy that fails must never stop TurboCAT starting
            print(f"Couldn't make a safety copy of the catalogue: {ex}", file=sys.stderr)
        return True
    copies = C.backups(db_path)
    box = QMessageBox()
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle(f"{APP_NAME}: the catalogue is damaged")
    text = (f"The catalogue file can't be read:\n{db_path}\n\nSQLite says: {why}\n\n")
    if not copies:
        box.setText(text + "There is no safety copy to put back. The damaged file has been left as "
                           "it is. Scanning your folders again into a new catalogue will rebuild it.")
        box.setStandardButtons(QMessageBox.Close)
        box.exec()
        return False
    f, made, items = copies[0]
    box.setText(text + f"TurboCAT has a safety copy from {time.strftime('%d %b %Y, %H:%M', time.localtime(made))} "
                       f"with {items:,} items. Put it back?\n\nThe damaged file is kept beside it, renamed, "
                       "and anything changed after that copy was made will need scanning again.")
    restore = box.addButton("Put the copy back", QMessageBox.AcceptRole)
    box.addButton("Quit", QMessageBox.RejectRole)
    box.setDefaultButton(restore)
    box.exec()
    if box.clickedButton() is not restore:
        return False
    try:
        damaged = C.restore(db_path, f)
    except Exception as ex:
        QMessageBox.critical(None, APP_NAME, f"The copy couldn't be put back: {ex}")
        return False
    QMessageBox.information(None, APP_NAME, f"The safety copy is back in place.\n\n"
                                            f"The damaged file is kept as:\n{damaged}")
    return True


def run(db_path):
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(VERSION)
    _pick_theme()
    app.setFont(ui_font(14))
    if not _catalogue_ready(db_path):
        return 1
    w = MainWindow(db_path)
    w.show()
    return app.exec()
