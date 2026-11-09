"""TurboCAT 4 desktop window.

Follows the "TurboCAT 4 Window" design: wordmark header, a search box, the
numbered disk list with type icons and status pills, a details panel for the
selected item, and a status line.
Run with:  python -m turbocat window   (add --db FILE for another catalogue)
"""

import json
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field

from PySide6.QtCore import (QAbstractTableModel, QIODevice, QItemSelectionModel, QModelIndex,
                            QObject, QRectF, QSize, QSortFilterProxyModel, Qt, QThread, QTimer,
                            QUrl, Signal)
from PySide6.QtGui import (QColor, QDesktopServices, QFont, QFontMetrics, QGuiApplication, QIcon,
                           QAction, QKeySequence, QPainter, QPen, QPixmap, QShortcut)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDialog, QFileDialog,
                               QFrame, QGridLayout, QListWidget, QListWidgetItem, QMenu, QMessageBox,
                               QRadioButton,
                               QButtonGroup, QHBoxLayout, QProgressBar,
                               QHeaderView, QLabel, QLineEdit, QMainWindow, QPushButton,
                               QScrollArea, QSizePolicy, QSplitter, QStackedWidget, QStyle, QStyledItemDelegate,
                               QTableView, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import APP_NAME, VERSION
from .bootblock import best_title
from .catalogue import Catalogue, matches, search_words
from . import dups as dupes, emulator, games, gotek, music, pictures, turboview
from .scanner import rescan_all, scan

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
             "module": "music"}
STATUS = {"ok": ("OK", "ok", "ok-tint", None),
          "warning": ("Warning", "warn", "warn-tint", "warning"),
          "error": ("Problem", "problem", "problem-tint", "problem"),
          "empty": ("Empty", "ink-soft", "neutral-tint", None)}

# Filter chips above the list: key, label, icon, test for an item.
FILTERS = [
    ("all", "All items", None, lambda it: True),
    ("games", "Games", "game", lambda it: bool(it.game)),
    ("music", "Music", "music", lambda it: it.music > 0),
    ("problems", "Problems", "problem", lambda it: it.status == "error"),
    ("warnings", "Warnings", "warning", lambda it: it.status == "warning"),
    ("dups", "Duplicates", "duplicate", lambda it: it.copies > 1),
    ("whd", "WHDLoad games", "game", lambda it: it.type == "WHDLoad"),
    ("nondos", "Non-DOS disks", "disk", lambda it: it.non_dos),
    ("hd", "Hard drives", "harddrive", lambda it: it.hard_drive),
    ("empty", "Empty", None, lambda it: it.status == "empty"),
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
    shares: frozenset = frozenset()   # fingerprints of archives/disks it shares with other items
    non_dos: bool = False
    hard_drive: bool = False
    thumb_icon: str = ""        # the disk's own Workbench icon (PNG path)
    pic: str = ""               # best picture: on the disk, or found online
    pic_from: str = ""
    pic_origin: str = ""
    game: str = ""              # why it counts as a game ("" if it doesn't)
    key: str = ""               # pictures / music key
    music: int = 0              # music modules found inside
    search_blob: str = field(default="", repr=False)


def load_items(cat):
    rows = cat.db.execute("SELECT * FROM media WHERE parent_id IS NULL ORDER BY number").fetchall()
    shared_sha = {r["sha1"] for r in cat.duplicate_images()}
    thumbs = pictures.thumbs_by_key(cat)
    game_why = games.classify(cat)
    tunes = {k: len(v) for k, v in pictures.music_by_key(cat).items()}
    top = cat.top_ids()
    inside = {}      # top-level id -> every archive / image found inside it
    for r in cat.db.execute("SELECT * FROM media WHERE parent_id IS NOT NULL ORDER BY id"):
        inside.setdefault(top.get(r["id"]), []).append(r)
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
            typ, ico = ({"folder": "Folder", "module": "Module"}.get(kind, kind.upper()),
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

        if disk is m:
            n = (m["file_count"] or 0) + sum(k["file_count"] or 0 for k in kids)
        else:
            n = (disk["file_count"] or 0) + sum(k["file_count"] or 0 for k in kids if k is not disk)
        files = f"{n:,}" if n or (disk["volume"] and not non_dos) else "—"
        if status == "empty":
            files = "—"
        # Things inside it that also turn up elsewhere (not counting the item's own disk,
        # which is what makes a true duplicate).
        own_key = disk["sha1"] or m["sha1"] or ""
        shares = frozenset({r["sha1"] for r in kids if r["kind"] in IMAGE_KINDS} & shared_sha
                           - {own_key})
        th = thumbs.get(pictures.item_key(m))
        items.append(Item(
            id=m["id"], number=m["number"] or 0, file=os.path.basename(m["source"].rstrip("/")),
            path=m["source"], type=typ, icon=ico, title=title, from_text=from_text, files=files,
            status=status, sha1=own_key, dup_key=own_key if dkind != "folder" else "", shares=shares,
            non_dos=non_dos and status != "empty",
            hard_drive=dkind in ("hdf", "folder") or any(k["kind"] == "hdf" for k in kids),
            thumb_icon=pictures.picture_path(th["icon"]) or "" if th else "",
            pic=pictures.picture_path(th["pic"]) or "" if th else "",
            pic_from=(th["pic_from"] or "") if th else "",
            pic_origin=(th["origin"] or "") if th else "",
            game=game_why.get(m["id"], ""),
            key=pictures.item_key(m), music=tunes.get(pictures.item_key(m), 0)))
    dupes.mark(items, cat)
    return items


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
                return it.path if role == Qt.ItemDataRole.ToolTipRole else it.file
            if col == 2:
                return it.title + (f"\nFound: {it.found}" if it.found else "")
            if col == 3:
                return it.files
            return STATUS.get(it.status, STATUS["ok"])[0] + _dup_word(it, long=True)
        return None


def _dup_word(it, long=False):
    """The duplicate pill: "Spare copy" on a hidden spare, "2 copies" on the copy kept."""
    if it.copies < 2:
        return ""
    word = "Spare copy" if it.spare_of else f"{it.copies} copies"
    return f" · {word}" if long else word


TUNE_COLUMNS = ["TUNE", "FORMAT", "SIZE", "LENGTH", "NO.", "WHERE"]
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
                return int((Qt.AlignmentFlag.AlignRight if section in (2, 3) else Qt.AlignmentFlag.AlignLeft)
                           | Qt.AlignmentFlag.AlignVCenter)
        return None

    @staticmethod
    def title(r):
        name = r["file"].rsplit("/", 1)[-1]
        return r["title"] or re.sub(r"^(mod|med|xm|s3m)\.", "", name, flags=re.I)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        r, it = self.rows[index.row()]
        col = index.column()
        dur = r["duration"]
        if role == Qt.ItemDataRole.DisplayRole:
            return [self.title(r),
                    r["fmt"] + (" (in a program)" if r["length"] else ""),
                    _short_size(r["size"] or 0),
                    music.fmt_time(dur) if dur and dur > 0 else ("can't play" if dur is not None else "…"),
                    f"#{it.number:04d}",
                    r["shown"]][col]
        if role == SORT_ROLE:
            return [self.title(r).lower(), r["fmt"], r["size"] or 0, dur or 0, it.number,
                    r["shown"].lower()][col]
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{self.title(r)}\n{r['shown']}\nDouble-click to play"
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int((Qt.AlignmentFlag.AlignRight if col in (2, 3) else Qt.AlignmentFlag.AlignLeft)
                       | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ForegroundRole and col in (1, 4, 5):
            return C["ink-muted"]
        if role == Qt.ItemDataRole.FontRole:
            return data_font(12) if col in (2, 3, 4) else (ui_font(13, QFont.Weight.Medium) if col == 0
                                                         else ui_font(12))
        if role == Qt.ItemDataRole.DecorationRole and col == 0:
            return QIcon(icon("music", 16))
        return None


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
        elif col == 1:
            self._paint_thumb(p, it, x, r)
            tx, tw = x + self.SLOT_W + 10, w - self.SLOT_W - 10
            f1, f2 = ui_font(14, QFont.Weight.Medium), data_font(12)
            h = QFontMetrics(f1).height() + QFontMetrics(f2).height()
            y = r.top() + (r.height() - h) / 2
            p.setFont(f1)
            p.setPen(C["ink"])
            p.drawText(QRectF(tx, y, tw, QFontMetrics(f1).height()), Qt.AlignmentFlag.AlignLeft,
                       QFontMetrics(f1).elidedText(it.file, Qt.TextElideMode.ElideMiddle, int(tw)))
            p.setFont(f2)
            p.setPen(C["ink-muted"])
            p.drawText(QRectF(tx, y + QFontMetrics(f1).height(), tw, QFontMetrics(f2).height()),
                       Qt.AlignmentFlag.AlignLeft, it.type)
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
        else:
            word, fg, bg, ico = STATUS.get(it.status, STATUS["ok"])
            px = self._pill(p, x, r, word, C[fg], C[bg], ico)
            if it.copies > 1:
                self._pill(p, px + 6, r, _dup_word(it), C["ink-soft"], C["neutral-tint"], "duplicate")
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
                w = 120 + (130 if it.copies > 1 else 0)
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
             "zip": "ZIP archive", "folder": "Amiga folder"}
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

    def __init__(self, tone, ico, heading, lines=(), on_link=None):
        super().__init__()
        self.setObjectName("note_" + tone)
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
        lay.addLayout(body, 1)


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


class DetailsPanel(QFrame):
    """Everything about the selected item: the right-hand panel of the design."""
    FACTS = ["Filesystem", "Bootblock", "Contents", "Status", "Size", "Scanned"]

    def __init__(self, cat, on_select_number, on_copy=None, on_online=None, on_play=None,
                 on_start=None):
        super().__init__()
        self.cat = cat
        self.on_select_number = on_select_number
        self.on_keep = None          # keep this copy of a duplicate (set by the window)
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

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.show_btn = QPushButton("Show in folder")
        self.show_btn.setFont(ui_font(13, QFont.Weight.DemiBold))
        self.show_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.show_btn.clicked.connect(self.show_in_folder)
        buttons.addWidget(self.show_btn)
        self.play_btn = QPushButton("Play in emulator")
        self.play_btn.setObjectName("primary")
        self.play_btn.setFont(ui_font(13, QFont.Weight.DemiBold))
        self.play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play_btn.setToolTip("Start this disk (and the rest of its set) in Amiberry or FS-UAE "
                                 "(Ctrl+P, or double-click it in the list)")
        self.play_btn.clicked.connect(lambda: on_start and self.item_id and on_start([self.item_id]))
        buttons.insertWidget(0, self.play_btn)
        self.copy_btn = QPushButton("Copy to Gotek stick")
        self.copy_btn.setFont(ui_font(13, QFont.Weight.DemiBold))
        self.copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_btn.setToolTip("Copy this disk to a USB stick for a Gotek drive")
        self.copy_btn.clicked.connect(lambda: on_copy and self.item_id and on_copy([self.item_id]))
        buttons.addWidget(self.copy_btn)
        buttons.addStretch(1)
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

    def _set_fact(self, name, text, ico=None, color=None):
        pic, val = self.facts[name]
        val.setText(_breakable(text))
        val.setStyleSheet(f"color: {color.name()};" if color else "")
        if ico:
            pic.setPixmap(icon(ico, 16))
            pic.show()
        else:
            pic.hide()

    def _note_link(self, href):
        """Links in notes: an item number to jump to, or keep:<id> to keep that copy."""
        if href.startswith("keep:"):
            m = self.cat.media_by_id(int(href[5:]))
            if m is not None and self.on_keep:
                self.on_keep(m)
        else:
            self.on_select_number(int(href))

    def show_item(self, item):
        m = self.cat.media_by_id(item.id)
        if m is None:
            self.clear()
            return
        kids = self._descendants(m["id"])
        kind = m["kind"] or ""
        self.source = m["source"]
        self.item_id = m["id"]
        floppy = any(r["kind"] in gotek.FLOPPY_KINDS and r["status"] != "empty" for r in [m] + kids)
        self.copy_btn.setVisible(floppy and not m["whd_name"])
        ipf = item.game and bool(self.cat.db.execute(
            "SELECT 1 FROM files WHERE media_id=? AND lower(path) LIKE '%.ipf' LIMIT 1", (m["id"],)).fetchone())
        self.play_btn.setVisible(floppy or ipf or (bool(m["whd_name"]) and kind == "lha"))
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
        if m["whd_name"]:
            lines = [x for x in (m["whd_copy"], m["whd_info"]) if x]
            self.notes.addWidget(Note("accent", "game", f"<b>WHDLoad game:</b> {_esc(m['whd_name'])}",
                                      lines))

        def collect(field):
            out = []
            for r in [m] + kids:
                where = f"{r['inner_path']}: " if r["parent_id"] else ""
                out += [where + x for x in _j(r[field], [])]
            return out
        if m["status"] != "empty":
            problems = collect("problems")
            if problems:
                self.notes.addWidget(Note("problem", "problem", "<b>Problem</b>", problems))
        warnings = collect("warnings")
        fs_issues = [w for w in warnings if FS_ISSUE in w]
        warnings = [w for w in warnings if FS_ISSUE not in w]
        if warnings:
            self.notes.addWidget(Note("warn", "warning", "<b>Warning</b>", warnings))
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
            if not texts and m["status"] != "empty":
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
            if item.pic_origin == "online":
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


class ScanWorker(QThread):
    """Runs a scan or rescan with its own database connection, off the window's thread."""
    line = Signal(str)
    step = Signal(str, int, int, object, object, str)   # phase, done, total, bytes done, bytes total, path
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, db_path, folders=None):
        super().__init__()
        self.db_path = db_path
        self.folders = folders       # None = rescan everything scanned before
        self.stop_wanted = False

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
            if self.folders is None:
                s = rescan_all(cat, progress=self._progress, step=self._step)
            else:
                s = scan(self.folders, cat, progress=self._progress, step=self._step)
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
            self.what.setText(f"Can't play music: {why}")
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

            res = {"disk": pictures.build(
                cat, lambda i, n, m: self.progress.emit("disk", i, n, name(m)), stop)}
            if not self.stop_wanted:
                res["lengths"] = pictures.measure_music(
                    cat, lambda i, n, m: self.progress.emit("lengths", i, n, ""), stop)
            if self.online and not self.stop_wanted:
                res["online"] = pictures.lookup_online(
                    cat, lambda i, n, m: self.progress.emit("online", i, n, name(m)), stop)
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

        v = QVBoxLayout(self)
        v.setContentsMargins(24, 22, 24, 20)
        v.setSpacing(12)
        title = names[0] if names else "Nothing to play"
        head = QLabel(_esc(re.split(r"\s*[\(\[]", title, maxsplit=1)[0]) if names else title)
        head.setFont(ui_font(20, QFont.Weight.Bold))
        v.addWidget(head)
        if self.whdload:
            what = "WHDLoad game, started by Amiberry's WHDLoad booter"
        else:
            n = len(self.files)
            what = (f"{n} disk{'s' if n != 1 else ''}: the first in DF0:"
                    + (", the second in DF1:, all of them in the disk swapper" if n > 1 else ""))
        v.addWidget(_wrap_label(what, ui_font(13), "muted"))
        if self.files:
            lst = QListWidget()
            lst.setObjectName("diskList")
            lst.setFont(ui_font(13))
            lst.setIconSize(QSize(16, 16))
            lst.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
            lst.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            lst.setTextElideMode(Qt.TextElideMode.ElideMiddle)
            lst.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            for i, f in enumerate(self.files):
                drive = f"DF{i}:  " if i < 2 else "swap:  "
                it = QListWidgetItem(drive + os.path.basename(f))
                it.setIcon(QIcon(icon("disk", 16)))
                it.setToolTip(f)
                lst.addItem(it)
            lst.setFixedHeight(min(len(self.files), 6) * (max(lst.sizeHintForRow(0), 20) + 6) + 12)
            v.addWidget(lst)
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
        for w in (self.emu_box, self.model_box):
            w.setFont(ui_font(13))
            w.setMinimumHeight(36)
        for r in range(2):
            grid.itemAtPosition(r, 0).widget().setFont(ui_font(13, QFont.Weight.DemiBold))
        grid.setColumnStretch(1, 1)
        v.addLayout(grid)
        self.rom_note = _wrap_label("", ui_font(12), "muted")
        v.addWidget(self.rom_note)
        self.model_box.currentIndexChanged.connect(self._rom_text)
        self._rom_text()

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

    def _rom_text(self):
        mdl = self.model_box.currentData()
        rom = self.roms.get(mdl)
        self.rom_note.setText(f"Kickstart: {rom}" if rom else
                              "No matching Kickstart ROM found; the emulator will use its own "
                              "choice (or AROS).")

    def start(self):
        emu = self.emu_box.currentData()
        mdl = self.model_box.currentData()
        self.cat.set_meta("emulator", emu)
        cmd = emulator.command(emu, self.emulators[emu], mdl, self.roms.get(mdl), self.files,
                               self.whdload)
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
        self.scan_btn = QPushButton("Scan folder…")
        self.scan_btn.setObjectName("primary")
        self.scan_btn.setToolTip("Add a folder of Amiga disk images to the catalogue")
        self.rescan_btn = QPushButton("Rescan")
        self.rescan_btn.setToolTip("Look again at every folder scanned before: new and changed "
                                   "files are read, deleted ones removed (F5)")
        self.gotek_btn = QPushButton("Copy to Gotek stick")
        self.gotek_btn.setToolTip("Copy the selected disks to a USB stick for a Gotek drive (Ctrl+G). "
                                  "Select several with Ctrl or Shift.")
        self.tv_btn = QPushButton("TurboView")
        self.tv_btn.setToolTip("Start an emulated Amiga with TurboView, the Amiga side of TurboCAT, "
                               "and your collection folders mounted as drives")
        self.online_btn = QPushButton("Find pictures online")
        self.online_btn.setToolTip("Look up title screens for disks that have no picture of their own, "
                                   "in the libretro-thumbnails collection on GitHub")
        for b in (self.scan_btn, self.rescan_btn, self.gotek_btn, self.online_btn, self.tv_btn):
            b.setFont(ui_font(14, QFont.Weight.DemiBold))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            hl.addWidget(b)
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
        chips = QHBoxLayout()
        chips.setSpacing(8)
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
        chips.addStretch(1)
        self.chips["all"][0].setChecked(True)
        sl.addLayout(chips)
        self.scan_bar = QFrame()
        self.scan_bar.setObjectName("scanBar")
        sb = QHBoxLayout(self.scan_bar)
        sb.setContentsMargins(12, 6, 8, 6)
        sb.setSpacing(12)
        self.scan_busy = QProgressBar()
        self.scan_busy.setRange(0, 0)
        self.scan_busy.setFixedWidth(220)
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
        self.scan_bar.hide()
        sl.addWidget(self.scan_bar)
        res_row = QHBoxLayout()
        res_row.setSpacing(8)
        res_row.addWidget(self.result_label, 1)
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
        res_row.addSpacing(8)
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
        self.tunes_table.verticalHeader().setDefaultSectionSize(34)
        self.tunes_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tunes_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.tunes_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        th2 = self.tunes_table.horizontalHeader()
        th2.setFont(hf)
        th2.setHighlightSections(False)
        th2.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        th2.setStretchLastSection(True)
        for col, width in enumerate((260, 170, 80, 80, 70)):
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
        self.foot_left = QLabel()
        self.foot_right = QLabel(f"{APP_NAME} {VERSION} · {db_path}")
        for lab in (self.foot_left, self.foot_right):
            lab.setObjectName("muted")
            lab.setFont(ui_font(12))
        fl.addWidget(self.foot_left)
        fl.addStretch(1)
        fl.addWidget(self.foot_right)
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
        self.emulators = None
        self.worker = None
        self.bar_mode = "scan"
        self.pic_asked = self.pic_shown = False
        self.spares_hidden = 0
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
        m.addSeparator()
        add(m, "&Export tune list…", self.export_tune_list, None,
            "Save every tune found as a spreadsheet")
        m.addSeparator()
        add(m, "&Quit", self.close, "Ctrl+Q")

        m = bar.addMenu("&Disk")
        self.act_play = add(m, "&Play", self.play_selected, "Ctrl+P",
                            "Start the disk in an emulator, or play a tune in TurboCAT")
        self.act_gotek = add(m, "Copy to &Gotek stick…", lambda: self.copy_to_gotek(), "Ctrl+G")
        self.act_folder = add(m, "Show in &folder", self.show_selected_in_folder, "Ctrl+Shift+O",
                              "Open the folder holding the selected item")

        m = bar.addMenu("&Tools")
        self.act_online = add(m, "Find pictures &online", self.find_online, None,
                              "Look up title screens in the libretro-thumbnails collection")
        add(m, "Start &TurboView", self.start_turboview, None,
            "Start an emulated Amiga with TurboView and your collection mounted")

        m = bar.addMenu("&Help")
        add(m, f"&About {APP_NAME}", self.show_about, "F1")
        add(m, f"{APP_NAME} on &GitHub", lambda: QDesktopServices.openUrl(QUrl(AboutDialog.REPO)))
        self._selection_changed()

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
            for a in (self.act_play, self.act_gotek, self.act_folder):
                a.setEnabled(bool(ids))

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

    def show_about(self):
        dlg = AboutDialog(self, self.cat, self.db_path)
        dlg.exec()
        dlg.deleteLater()      # don't leave it to Python's shutdown (that crashed on exit)

    def play_selected(self):
        """Double-click / Ctrl+P: a tune on its own plays in TurboCAT's player; disks start in
        the emulator."""
        ids = self.selected_ids()
        chosen = [it for it in self.model.items if it.id in set(ids)]
        if chosen and all(it.type == "Module" for it in chosen):
            rows, labels = [], []
            for it in chosen:
                for r in self.cat.db.execute("SELECT * FROM music WHERE key=? ORDER BY rowid", (it.key,)):
                    rows.append(r)
                    labels.append(f"#{it.number:04d}")
            if rows:
                self.player_bar.play(rows, 0, labels=labels)
            return
        self.play_in_emulator(ids)

    def play_in_emulator(self, ids=None):
        """Start the selected disks in Amiberry or FS-UAE (a single disk brings its whole set)."""
        ids = ids or self.selected_ids()
        if not ids:
            return
        if self.emulators is None:
            self.emulators = emulator.find_emulators()
        if not self.emulators:
            QMessageBox.information(self, "Play in emulator",
                                    "Neither Amiberry nor FS-UAE was found. Install one of them "
                                    "(Amiberry is on Flathub) and try again.")
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
            QMessageBox.information(self, "TurboView", "Neither Amiberry nor FS-UAE was found.")
            return
        rom = emulator.find_kickstarts().get("A1200")
        cmd = emulator.turboview_command(emu, self.emulators[emu], rom, folder,
                                         turboview.roots_with_volumes(self.cat))
        emulator.launch(cmd)

    def play_music(self, rows, index):
        it = next((x for x in self.model.items if x.id == self.current_id), None)
        self.player_bar.play(rows, index, f"#{it.number:04d}" if it else "")

    def copy_to_gotek(self, ids=None):
        ids = ids or self.selected_ids()
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
            hits = [it for it in matched if FILTER_TEST[key](it)]
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
            self._start_scan([folder], f"Scanning {folder}…")

    def rescan(self):
        roots = self.cat.scan_roots()
        if not roots:
            self.scan_folder()
            return
        self._start_scan(None, f"Rescanning {len(roots)} folder{'s' if len(roots) > 1 else ''}…")
        self.scan_bar.setToolTip("Rescanning:\n" + "\n".join(roots))

    def _start_scan(self, folders, text):
        if self.worker is not None:
            return
        self.hide_bar.stop()
        self.scan_text.setText(text)
        self.scan_file.setText("")
        self.bar_mode = "scan"
        self.scan_busy.setRange(0, 0)          # busy until the first progress report
        self.read_started = None
        self.scan_busy.show()
        self.stop_btn.show()
        self.stop_btn.setEnabled(True)
        self.scan_bar.show()
        self.scan_btn.setEnabled(False)
        self.act_scan.setEnabled(False)
        self.rescan_btn.setEnabled(False)
        self.act_rescan.setEnabled(False)
        self.found_count = 0
        self.stop_pictures()
        self.worker = ScanWorker(self.db_path, folders)
        self.worker.line.connect(self._scan_line)
        self.worker.step.connect(self._scan_step)
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
    def _time_left(seconds):
        if seconds < 60:
            return "less than a minute left"
        minutes = int(seconds // 60) + 1
        if minutes < 90:
            return f"about {minutes} min left"
        return f"about {minutes // 60} h {minutes % 60} min left"

    def _scan_step(self, phase, done, total, done_bytes, total_bytes, path):
        if self.worker is None or self.worker.stop_wanted:
            return
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
        name = os.path.basename(path) if path else ""
        fm = QFontMetrics(self.scan_file.font())
        self.scan_file.setText(fm.elidedText(name, Qt.TextElideMode.ElideMiddle,
                                             max(40, self.scan_file.width())))
        self.scan_file.setToolTip(path)

    def _scan_done(self, s):
        if s.get("stopped"):
            msg = f"Scan stopped. {self.found_count:,} new or changed item(s) were added first."
        else:
            bits = [f"{s.get('scanned', 0):,} new or changed", f"{s.get('skipped', 0):,} unchanged"]
            if s.get("removed"):
                bits.append(f"{len(s['removed']):,} removed (files deleted)")
            if s.get("missing"):
                bits.append(f"{len(s['missing'])} folder(s) not found")
            msg = "Scan finished: " + ", ".join(bits) + "."
        self._show_result(msg)

    def _scan_failed(self, err):
        self._show_result(f"Scan failed: {err}")

    def _show_result(self, msg):
        self.scan_text.setText(msg)
        self.scan_file.setText("")
        self.scan_busy.hide()
        self.stop_btn.hide()
        self.reload()
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
        self.find_pictures()

    # -------------------------------------------------------------- pictures
    def find_pictures(self, online=None, asked=False):
        """Look for pictures on new items (and online, once the user has agreed to that).
        asked: the user asked for this, so the progress bar shows from the start."""
        if self.pic_worker is not None or self.worker is not None:
            return
        if online is None:
            online = bool(self.cat.get_meta("online_pictures", False))
        self.pic_asked = asked
        self.pic_shown = False
        if asked:
            self._pic_bar("Getting ready to look for pictures online…", 0, 0, "")
        self.pic_worker = PictureWorker(self.db_path, online)
        self.pic_worker.progress.connect(self._pic_progress)
        self.pic_worker.done.connect(self._pic_done)
        self.pic_worker.failed.connect(self._pic_failed)
        self.pic_worker.finished.connect(self._pic_finished)
        self.online_btn.setEnabled(False)
        self.act_online.setEnabled(False)
        self.pic_worker.start()
        self.pic_refresh.start()

    def find_online(self):
        if not self.cat.get_meta("online_pictures", False):
            box = QMessageBox(self)
            box.setWindowTitle("Find pictures online")
            box.setIcon(QMessageBox.Icon.Question)
            box.setText("Look up pictures online for disks that have none of their own?")
            box.setInformativeText(
                "TurboCAT matches each disk's title against the libretro-thumbnails collection "
                "(the pictures RetroArch uses), on GitHub, and downloads a title screen when the "
                "name matches exactly.\n\nThese pictures belong to the games' publishers. They "
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
        if phase == "online" and not n:
            self._pic_bar("Getting the list of pictures from GitHub…", 0, 0,
                          "libretro-thumbnails, Commodore Amiga")
            return
        if not n or i >= n:
            return
        text = {"disk": "Looking for pictures and music on disks…",
                "lengths": "Measuring tunes…",
                "online": "Looking for pictures online…"}[phase]
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
        if res.get("turboview_error"):
            bits.append(f"TurboView catalogue not written: {res['turboview_error']}")
        if "online" in res and res["online"]["looked"]:
            n, looked = res["online"]["found"], res["online"]["looked"]
            bits.append(f"{n:,} picture{'' if n == 1 else 's'} found online for "
                        f"{looked:,} disk{'' if looked == 1 else 's'} looked up")
        if res.get("online", {}).get("stopped"):
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

    def _pic_finished(self):
        self.pic_worker = None
        self.pic_refresh.stop()
        self.online_btn.setEnabled(True)
        self.act_online.setEnabled(True)

    def reload(self):
        """Re-read the catalogue after a scan, keeping the search and selection."""
        before = {it.id: (it.pic, it.thumb_icon) for it in self.all_items}
        self.all_items = load_items(self.cat)
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

    def closeEvent(self, event):
        self.player_bar.player.stop()
        self.stop_pictures()
        if self.worker is not None:
            self.worker.stop_wanted = True
            self.worker.wait(30000)
        super().closeEvent(event)

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
            shown = []
            for it in self.all_items:
                h = hits.get(it.id)
                if h is None:
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
        self._fill_chips(shown, everything)
        matched = len(shown)
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
        label = dict((k, l) for k, l, _, _ in FILTERS)[self.filter]
        if self.filter == "music":
            label = "Items with music"
        if text and self.filter != "all":
            self.result_label.setText(f"{len(shown):,} {label.lower()} among the {matched:,} "
                                      f"items that match “{text}”")
        elif text:
            self.result_label.setText(
                f"{len(shown):,} of {len(self.all_items):,} items match “{text}”")
        elif self.filter == "dups":
            sets = len({it.dup_key for it in shown})
            self.result_label.setText(
                f"{_n(sets, 'disk')} catalogued more than once · TurboCAT shows one copy of each and "
                f"hides the {_n(len(shown) - sets, 'spare')} · nothing is deleted")
        elif self.filter != "all":
            self.result_label.setText(f"{label} {len(shown):,} of {len(self.all_items):,} items")
        else:
            self.result_label.setText(f"All items {len(shown):,}" + (
                f" · {_n(self.spares_hidden, 'spare copy')} hidden (see Duplicates)"
                .replace("copys", "copies") if self.spares_hidden else ""))
        keep = set(self.selected_ids()) if self.model.items else set()
        self.model.set_items(shown)
        if shown:
            ids = [it.id for it in shown]
            self._select_row(ids.index(self.current_id) if self.current_id in ids else 0)
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
        self.export_tunes_btn.setVisible(music_view and self.tune_view)
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
                if words and not matches(words, r["title"], r["file"], r["shown"], r["fmt"],
                                         it.file, it.title):
                    continue
                rows.append((r, it))
        keep = self._current_tune()
        self.tune_model.set_rows(rows)
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
            w.writerow(["Tune", "Format", "Size (bytes)", "Length", "Item", "Item file", "Where"])
            for i in range(self.tune_proxy.rowCount()):
                r, it = self.tune_model.rows[self.tune_proxy.mapToSource(self.tune_proxy.index(i, 0)).row()]
                dur = r["duration"]
                w.writerow([TuneModel.title(r), r["fmt"], r["size"],
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
