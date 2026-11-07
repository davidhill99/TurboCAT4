"""TurboCAT 4 desktop window (step 1: the catalogue list with search).

Follows the "TurboCAT 4 Window" design: wordmark header, a search box, the
numbered disk list with type icons and status pills, and a status line.
Run with:  python -m turbocat window   (add --db FILE for another catalogue)
"""

import json
import os
import sys
import time
from dataclasses import dataclass, field

from PySide6.QtCore import (QAbstractTableModel, QModelIndex, QRectF, QSize, Qt, QTimer)
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QGuiApplication, QIcon, QKeySequence,
                           QPainter, QPen, QPixmap, QShortcut)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFrame, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMainWindow, QStackedWidget, QStyle,
                               QStyledItemDelegate, QTableView, QVBoxLayout, QWidget)

from . import APP_NAME, VERSION
from .bootblock import best_title
from .catalogue import Catalogue

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

IMAGE_KINDS = ("adf", "dms", "adz", "hdf", "lha", "lzx")
KIND_ICON = {"adf": "disk", "dms": "disk", "adz": "disk", "hdf": "harddrive",
             "lha": "archive", "lzx": "archive", "folder": "folder"}
STATUS = {"ok": ("OK", "ok", "ok-tint", None),
          "warning": ("Warning", "warn", "warn-tint", "warning"),
          "error": ("Problem", "problem", "problem-tint", "problem")}


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
    dup: bool = False
    found: str = ""
    search_blob: str = field(default="", repr=False)


def load_items(cat):
    rows = cat.db.execute("SELECT * FROM media WHERE parent_id IS NULL ORDER BY number").fetchall()
    dup_sha = {r["sha1"] for r in cat.duplicate_images()}
    child_files = dict(cat.db.execute(
        "SELECT parent_id, SUM(file_count) FROM media WHERE parent_id IS NOT NULL GROUP BY parent_id"))
    items = []
    for m in rows:
        try:
            info = json.loads(m["info"] or "{}")
            texts = json.loads(m["text"] or "[]")
        except ValueError:
            info, texts = {}, []
        kind = m["kind"] or ""
        non_dos = "non-DOS" in str(info.get("format", ""))
        if m["whd_name"]:
            typ, ico = "WHDLoad", "game"
        else:
            typ, ico = ("Folder" if kind == "folder" else kind.upper()), KIND_ICON.get(kind, "disk")
        title, from_text = m["whd_name"] or m["volume"] or "", False
        if not title:
            title = best_title(texts)[:60]
            from_text = bool(title)
            if not title:
                title = "Non-DOS data disk" if non_dos or not m["fs"] else "No volume name"
        n = (m["file_count"] or 0) + (child_files.get(m["id"]) or 0)
        files = f"{n:,}" if n or (m["volume"] and not non_dos) else "—"
        items.append(Item(
            id=m["id"], number=m["number"] or 0, file=os.path.basename(m["source"].rstrip("/")),
            path=m["source"], type=typ, icon=ico, title=title, from_text=from_text, files=files,
            status=m["status"] or "ok", dup=m["sha1"] in dup_sha and kind in IMAGE_KINDS))
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
        lw = QWidget()
        ll = QVBoxLayout(lw)
        ll.setContentsMargins(24, 4, 24, 24)
        ll.addWidget(panel)
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

        self._fill_counts()
        self.run_search()
        self.search.edit.setFocus()

    def focus_search(self):
        self.search.edit.setFocus()
        self.search.edit.selectAll()

    def _fill_counts(self):
        st = self.cat.stats()
        self.counts.setText(f"{st['items']:,} items · {st['files']:,} files")
        last = self.cat.db.execute("SELECT MAX(scanned_at) FROM media").fetchone()[0]
        bits = []
        if last:
            bits.append("Catalogue of " + time.strftime("%-d %b %Y, %H:%M", time.localtime(last)))
        bits.append(f"{st['errors']} with problems, {st['warnings']} with warnings")
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
        if not self.all_items:
            self.message.setText(
                "The catalogue is empty.\n\nScan a folder from the terminal first, for example:\n"
                "python -m turbocat scan ~/Amiga")
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
