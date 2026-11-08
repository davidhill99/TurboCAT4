"""TurboCAT 4 desktop window.

Follows the "TurboCAT 4 Window" design: wordmark header, a search box, the
numbered disk list with type icons and status pills, a details panel for the
selected item, and a status line.
Run with:  python -m turbocat window   (add --db FILE for another catalogue)
"""

import json
import os
import sys
import time
from dataclasses import dataclass, field

from PySide6.QtCore import (QAbstractTableModel, QModelIndex, QRectF, QSize, Qt, QThread, QTimer,
                            QUrl, Signal)
from PySide6.QtGui import (QColor, QDesktopServices, QFont, QFontMetrics, QGuiApplication, QIcon,
                           QKeySequence, QPainter, QPen, QPixmap, QShortcut)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFileDialog, QFrame, QGridLayout,
                               QHBoxLayout, QProgressBar,
                               QHeaderView, QLabel, QLineEdit, QMainWindow, QPushButton,
                               QScrollArea, QSizePolicy, QSplitter, QStackedWidget, QStyle, QStyledItemDelegate,
                               QTableView, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import APP_NAME, VERSION
from .bootblock import best_title
from .catalogue import Catalogue
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
             "lha": "archive", "lzx": "archive", "zip": "archive", "folder": "folder"}
STATUS = {"ok": ("OK", "ok", "ok-tint", None),
          "warning": ("Warning", "warn", "warn-tint", "warning"),
          "error": ("Problem", "problem", "problem-tint", "problem"),
          "empty": ("Empty", "ink-soft", "neutral-tint", None)}


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
    dup: bool = False
    found: str = ""
    search_blob: str = field(default="", repr=False)


def load_items(cat):
    rows = cat.db.execute("SELECT * FROM media WHERE parent_id IS NULL ORDER BY number").fetchall()
    dup_sha = {r["sha1"] for r in cat.duplicate_images()}
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
            typ, ico = ("Folder" if kind == "folder" else kind.upper()), KIND_ICON.get(kind, "disk")

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
        shas = {r["sha1"] for r in [m] + kids if r["kind"] in IMAGE_KINDS}
        items.append(Item(
            id=m["id"], number=m["number"] or 0, file=os.path.basename(m["source"].rstrip("/")),
            path=m["source"], type=typ, icon=ico, title=title, from_text=from_text, files=files,
            status=status, sha1=disk["sha1"] or m["sha1"] or "", dup=bool(shas & dup_sha)))
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
            return STATUS.get(it.status, STATUS["ok"])[0] + (" · Duplicate" if it.dup else "")
        return None


class RowDelegate(QStyledItemDelegate):
    """Paints rows the way the design draws them."""
    PAD = 12

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
            p.drawPixmap(x, r.top() + (r.height() - 32) // 2, icon(it.icon, 32))
            tx, tw = x + 42, w - 42
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
            if it.dup:
                self._pill(p, px + 6, r, "Duplicate", C["ink-soft"], C["neutral-tint"], "duplicate")
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

    def sizeHint(self, opt, index):
        return QSize(100, 52)


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


def _wrap_label(text="", font=None, obj=None):
    lab = QLabel(text)
    lab.setWordWrap(True)
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


class DetailsPanel(QFrame):
    """Everything about the selected item: the right-hand panel of the design."""
    FACTS = ["Filesystem", "Bootblock", "Contents", "Status", "Size", "Scanned"]

    def __init__(self, cat, on_select_number):
        super().__init__()
        self.cat = cat
        self.on_select_number = on_select_number
        self.source = None
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

        self.contents_label = QLabel("CONTENTS")
        self.contents_label.setObjectName("section")
        lf = ui_font(12, QFont.Weight.DemiBold)
        lf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.6)
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

    def show_item(self, item):
        m = self.cat.media_by_id(item.id)
        if m is None:
            self.clear()
            return
        kids = self._descendants(m["id"])
        kind = m["kind"] or ""
        self.source = m["source"]
        # An archive holding one disk image is described by that disk.
        d = m
        direct = [k for k in kids if k["parent_id"] == m["id"]]
        if kind in ARCHIVE_KINDS and not m["whd_name"] and len(direct) == 1 \
                and direct[0]["kind"] in DISK_KINDS:
            d = direct[0]
        info = _j(d["info"], {})

        self.big_icon.setPixmap(icon(item.icon, 64))
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
        if item.dup and item.sha1:
            own = {m["id"]} | {k["id"] for k in kids}
            others = [r for r in self.cat.media_with_sha1(item.sha1) if r["id"] not in own]
            links = []
            for r in others[:6]:
                num = self.cat.top_number(r)
                name = os.path.basename(self.cat.label(r).split(" > ", 1)[0])
                if r["parent_id"]:
                    name += " › " + r["inner_path"]
                links.append(f"<a href='{num}' style='color:{C['accent'].name()}'>"
                             f"#{num:04d} {_esc(name)}</a>")
            more = f" and {len(others) - 6} more" if len(others) > 6 else ""
            self.notes.addWidget(Note(
                "accent", "duplicate",
                f"<b>Duplicate:</b> same disk as {', '.join(links)}{more}. You only need to keep one.",
                on_link=lambda n: self.on_select_number(int(n))))
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
        has_list = self.tree.topLevelItemCount() > 0
        self.contents_label.setVisible(has_list)
        self.tree.setVisible(has_list)
        self._fit_tree()
        self.stack.setCurrentWidget(self.page)
        self.page.verticalScrollBar().setValue(0)

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

    def run(self):
        cat = None
        try:
            cat = Catalogue(self.db_path)
            if self.folders is None:
                s = rescan_all(cat, progress=self._progress)
            else:
                s = scan(self.folders, cat, progress=self._progress)
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
        for b in (self.scan_btn, self.rescan_btn):
            b.setFont(ui_font(14, QFont.Weight.DemiBold))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            hl.addWidget(b)
        self.scan_btn.clicked.connect(self.scan_folder)
        self.rescan_btn.clicked.connect(self.rescan)
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
        self.scan_bar = QFrame()
        self.scan_bar.setObjectName("scanBar")
        sb = QHBoxLayout(self.scan_bar)
        sb.setContentsMargins(12, 6, 8, 6)
        sb.setSpacing(12)
        self.scan_busy = QProgressBar()
        self.scan_busy.setRange(0, 0)
        self.scan_busy.setFixedWidth(120)
        self.scan_busy.setTextVisible(False)
        self.scan_text = QLabel()
        self.scan_text.setFont(ui_font(13))
        self.scan_text.setMinimumWidth(40)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setFont(ui_font(13, QFont.Weight.DemiBold))
        self.stop_btn.setObjectName("small")
        self.stop_btn.clicked.connect(self.stop_scan)
        sb.addWidget(self.scan_busy)
        sb.addWidget(self.scan_text, 1)
        sb.addWidget(self.stop_btn)
        self.scan_bar.hide()
        sl.addWidget(self.scan_bar)
        sl.addWidget(self.result_label)
        v.addWidget(sw)

        # List (or an empty / nothing-found message)
        self.model = ItemModel()
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setItemDelegate(RowDelegate(self.table))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setMouseTracking(False)
        self.table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(52)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        hh = self.table.horizontalHeader()
        hf = ui_font(12, QFont.Weight.DemiBold)
        hf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.6)
        hh.setFont(hf)
        hh.setHighlightSections(False)
        hh.setSectionsClickable(False)
        hh.setMinimumSectionSize(60)
        for col, mode, width in ((0, QHeaderView.ResizeMode.Fixed, 84),
                                 (1, QHeaderView.ResizeMode.Stretch, 0),
                                 (2, QHeaderView.ResizeMode.Stretch, 0),
                                 (3, QHeaderView.ResizeMode.Fixed, 80),
                                 (4, QHeaderView.ResizeMode.Fixed, 210)):
            hh.setSectionResizeMode(col, mode)
            if width:
                self.table.setColumnWidth(col, width)

        self.message = QLabel()
        self.message.setObjectName("message")
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setWordWrap(True)
        self.message.setFont(ui_font(15))
        self.message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.table)
        self.stack.addWidget(self.message)
        panel = QFrame()
        panel.setObjectName("panel")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(1, 1, 1, 1)
        pl.addWidget(self.stack)
        self.details = DetailsPanel(self.cat, self.select_number)
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
        QShortcut(QKeySequence(Qt.Key.Key_F5), self, activated=self.rescan)
        self.worker = None
        self.hide_bar = QTimer(self, singleShot=True, interval=10000)
        self.hide_bar.timeout.connect(self.scan_bar.hide)
        self.live = QTimer(self, interval=4000)      # show new items while a scan runs
        self.live.timeout.connect(self._live_reload)
        self.current_id = None
        self.table.selectionModel().currentRowChanged.connect(self._row_changed)

        self._fill_counts()
        self.run_search()
        self.search.edit.setFocus()

    def _row_changed(self, current, _previous):
        if not current.isValid():
            self.details.clear()
            return
        it = self.model.items[current.row()]
        self.current_id = it.id
        self.details.show_item(it)

    def _select_row(self, row):
        self.table.setCurrentIndex(self.model.index(row, 0))
        self.table.scrollTo(self.model.index(row, 0), QAbstractItemView.ScrollHint.EnsureVisible)

    def select_number(self, number):
        """Select item #number, clearing the search if it is filtered out (used by links)."""
        for _ in range(2):
            for row, it in enumerate(self.model.items):
                if it.number == number:
                    self._select_row(row)
                    return
            self.search.edit.clear()
            self.run_search()

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
        self.scan_busy.show()
        self.stop_btn.show()
        self.stop_btn.setEnabled(True)
        self.scan_bar.show()
        self.scan_btn.setEnabled(False)
        self.rescan_btn.setEnabled(False)
        self.found_count = 0
        self.worker = ScanWorker(self.db_path, folders)
        self.worker.line.connect(self._scan_line)
        self.worker.done.connect(self._scan_done)
        self.worker.failed.connect(self._scan_failed)
        self.worker.finished.connect(self._scan_finished)
        self.worker.start()
        self.live.start()

    def stop_scan(self):
        if self.worker is not None:
            self.worker.stop_wanted = True
            self.stop_btn.setEnabled(False)
            self.scan_text.setText("Stopping after the current file…")

    def _scan_line(self, text):
        if text.startswith("#"):
            self.found_count += 1
            text = f"{self.found_count:,} read · " + text.split(" ", 2)[-1].strip()
        if not self.worker.stop_wanted:
            self.scan_text.setText(text)

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
        self.rescan_btn.setEnabled(True)

    def reload(self):
        """Re-read the catalogue after a scan, keeping the search and selection."""
        self.all_items = load_items(self.cat)
        self._fill_counts()
        self.run_search()

    def closeEvent(self, event):
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
            self.result_label.setText(f"All items {len(shown):,}")
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
            self.result_label.setText(
                f"{len(shown):,} of {len(self.all_items):,} items match “{text}”")
        self.model.set_items(shown)
        if shown:
            ids = [it.id for it in shown]
            self._select_row(ids.index(self.current_id) if self.current_id in ids else 0)
        else:
            self.details.clear()
        if not self.all_items:
            self.message.setText(
                "The catalogue is empty.\n\nClick Scan folder… and choose the folder where you "
                "keep your Amiga disk images.")
            self.stack.setCurrentWidget(self.message)
        elif not shown:
            self.message.setText(f"Nothing found for “{text}”.")
            self.stack.setCurrentWidget(self.message)
        else:
            self.stack.setCurrentWidget(self.table)

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
                                    border-bottom: 1px solid {c['line']}; padding: 10px 12px; }}
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
            QPushButton:disabled {{ color: {c['ink-muted']}; border-color: {c['line']}; }}
            QPushButton#primary {{ background: {c['accent']}; border: 1px solid {c['accent']}; color: {c['on-accent']};
                                   padding: 0 18px; min-height: 42px; }}
            QPushButton#primary:hover {{ background: {c['accent-ink']}; }}
            QPushButton#primary:disabled {{ background: {c['line']}; border-color: {c['line']};
                                            color: {c['ink-muted']}; }}
            QPushButton#small {{ min-height: 30px; padding: 0 12px; }}
            #scanBar {{ background: {c['accent-tint']}; border-radius: 8px; }}
            #scanBar QLabel {{ color: {c['accent-ink']}; }}
            QProgressBar {{ border: none; background: {c['surface']}; border-radius: 3px; max-height: 6px; }}
            QProgressBar::chunk {{ background: {c['accent']}; border-radius: 3px; }}
            QScrollBar:vertical {{ background: {c['surface']}; width: 12px; margin: 0; }}
            QScrollBar::handle:vertical {{ background: {c['line']}; border-radius: 4px; min-height: 30px;
                                           margin: 2px; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
            QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
        """)


def run(db_path):
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(VERSION)
    _pick_theme()
    app.setFont(ui_font(14))
    w = MainWindow(db_path)
    w.show()
    return app.exec()
