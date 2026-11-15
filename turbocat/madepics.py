"""Pictures TurboCAT draws itself, for disks with no picture of their own and none online.

  * A disk with Workbench icons: its window as Workbench showed it, with the disk's own icons
    where the disk put them (each .info file says where its icon sits, and Disk.info how big
    the window is), in the colours of the Workbench the icons were drawn for (1.3 or 2.0+).
  * A disk with no icons (a Shell-only utility disk): an AmigaDOS Shell window listing it, the
    way "dir" did.

They are stored apart from real pictures (thumbs.made), so a title screen found later, on the
disk or online, always takes their place. Games with no picture get a generic picture instead,
drawn by the window when it shows them (no file needed).

Drawing uses Qt, so this runs inside the TurboCAT window's picture search only.
"""
import os
import struct
import time

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPen

from . import amigaimg, pictures

MADE_RULES = 1        # bump when the drawings change, so every disk is drawn again
DISK_KINDS = ("adf", "adz", "dms", "folder")
ARCHIVES = ("zip", "lha", "lzx")
NO_POSITION = -2147483648      # NO_ICON_POSITION (0x80000000) as a signed number

WB13 = {"back": QColor(0, 85, 170), "text": QColor(255, 255, 255), "dark": QColor(0, 0, 0),
        "accent": QColor(255, 136, 0), "title": QColor(255, 255, 255)}
WB20 = {"back": QColor(149, 149, 149), "text": QColor(0, 0, 0), "dark": QColor(0, 0, 0),
        "accent": QColor(59, 103, 162), "title": QColor(255, 255, 255)}
SCALE_Y = 2            # Workbench ran in hires: pixels twice as tall as they are wide


# ---------------------------------------------------------------- storing

def ensure_columns(cat):
    pictures.ensure_schema(cat)          # adds thumbs.made, made_from, made_v


def _store(cat, key, png, made_from):
    name = pictures._save_png(png) if png else None
    cat.db.execute(
        "INSERT INTO thumbs (key, made, made_from, made_v, made_at) VALUES (?,?,?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET made=excluded.made, made_from=excluded.made_from, "
        "made_v=excluded.made_v, made_at=excluded.made_at", (key, name, made_from, MADE_RULES, time.time()))


def make(cat, skip=(), progress=None, stop=lambda: False):
    """Draw a picture for every item that has none: not empty, not a game (skip: ids), not a
    tune or ROM on its own. Each is drawn once (again when MADE_RULES changes)."""
    ensure_columns(cat)
    thumbs = pictures.thumbs_by_key(cat)
    todo = []
    for m in cat.db.execute("SELECT * FROM media WHERE parent_id IS NULL ORDER BY number"):
        t = thumbs.get(pictures.item_key(m))
        if m["id"] in skip or m["status"] == "empty" or m["kind"] in ("hdf", "module", "kickstart"):
            continue
        if t is not None and (t["pic"] or (t["made_v"] or 0) == MADE_RULES):
            continue
        todo.append(m)
    drawn = 0
    for i, m in enumerate(todo):
        if stop():
            return {"looked": i, "drawn": drawn, "stopped": True}
        if progress:
            progress(i, len(todo), m)
        try:
            png, what = draw_item(cat, m)
        except Exception:
            png, what = None, ""
        _store(cat, pictures.item_key(m), png, what)
        drawn += bool(png)
        if i % 20 == 19:
            cat.db.commit()
    cat.db.commit()
    return {"looked": len(todo), "drawn": drawn, "stopped": False}


# ---------------------------------------------------------------- reading the disk

def _disk_of(cat, m):
    """The chain (top first) to the disk to draw: the item itself, or the one disk image inside
    an archive. None if there's nothing sensible to draw (an archive of many disks)."""
    if m["kind"] in DISK_KINDS:
        return [m]
    kids = cat.db.execute("SELECT * FROM media WHERE parent_id=? ORDER BY id", (m["id"],)).fetchall()
    disks = [k for k in kids if k["kind"] in DISK_KINDS]
    if m["kind"] in ARCHIVES and len(disks) == 1:
        return [m, disks[0]]
    if m["kind"] in ARCHIVES and not kids:
        return [m]                      # an archive of loose files: list those
    return None


def icon_position(data):
    """Where a .info file puts its icon in its window, or None if it leaves it to Workbench."""
    if len(data) < 66:
        return None
    x, y = struct.unpack(">ii", data[58:66])
    if x == NO_POSITION or y == NO_POSITION or not (-50 < x < 2000 and -50 < y < 2000):
        return None
    return x, y


def drawer_box(data):
    """The window size Disk.info gives its drawer: (width, height), or None."""
    if len(data) < 78 + 8 or not struct.unpack(">I", data[66:70])[0]:
        return None
    _, _, w, h = struct.unpack(">hhhh", data[78:86])
    return (w, h) if 80 <= w <= 1024 and 40 <= h <= 1024 else None


def draw_item(cat, m):
    """(PNG bytes, what it shows) for one item, or (None, "")."""
    chain = _disk_of(cat, m)
    if chain is None:
        return None, ""
    disk = chain[-1]
    data = pictures._container_data(cat, chain)
    files = pictures._files_in(disk["kind"], data, disk["source"])
    root = [fe for fe in files if "/" not in fe.path.strip("/")]
    if not root:
        return None, ""
    volume = disk["volume"] or os.path.splitext(os.path.basename(disk["inner_path"] or disk["source"]))[0]
    icons, box, wb2 = [], None, False
    for fe in root:
        low = fe.path.lower()
        if not low.endswith(".info") or not fe.read or not fe.size:
            continue
        try:
            raw = fe.read()
            img = amigaimg.decode_icon(raw)
        except Exception:
            continue
        if img is None:
            continue
        if low == "disk.info":
            box = drawer_box(raw)
            continue
        stem = fe.path[:-5]          # (an icon for something not there still showed on Workbench)
        icons.append((stem, img, icon_position(raw)))
        wb2 = wb2 or (not isinstance(img, bytes) and img.note != "Workbench 1.3")
    if icons:
        return workbench_window(volume, icons, box, wb2), f"Workbench window of {volume}"
    entries = [(fe.path.strip("/"), fe.is_dir) for fe in root if not fe.path.lower().endswith(".info")]
    if not entries:
        return None, ""
    return shell_window(volume, entries), f"Shell listing of {volume}"


# ---------------------------------------------------------------- drawing

def _font(px, bold=False):
    f = QFont()
    f.setFamilies(["DejaVu Sans Mono", "Menlo", "Consolas", "Courier New", "monospace"])
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setPixelSize(px)
    f.setBold(bold)
    return f


def _png(img):
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


def _qimage(icon):
    if isinstance(icon, bytes):
        q = QImage.fromData(icon)
        return None if q.isNull() else q
    q = QImage(icon.rgba, icon.width, icon.height, icon.width * 4, QImage.Format.Format_RGBA8888)
    return q.copy()


def _window_frame(p, w, h, title, pal):
    """A Workbench window: title bar with close and depth gadgets, border, background."""
    p.fillRect(0, 0, w, h, pal["back"])
    bar = 22
    p.fillRect(0, 0, w, bar, pal["title"] if pal is WB20 else pal["text"])
    p.setPen(QPen(pal["dark"], 2))
    p.drawRect(1, 1, w - 2, h - 2)
    p.drawLine(0, bar, w, bar)
    # close gadget on the left, depth gadgets on the right
    p.fillRect(6, 5, 14, 12, pal["back"])
    p.drawRect(6, 5, 14, 12)
    for x in (w - 46, w - 24):
        p.drawRect(x, 5, 16, 12)
    p.fillRect(w - 44, 7, 8, 6, pal["accent"])
    p.setFont(_font(14, bold=True))
    p.setPen(pal["dark"] if pal is WB20 else pal["back"])
    p.drawText(QRect(28, 0, w - 90, bar), Qt.AlignmentFlag.AlignVCenter, title)
    return bar


def workbench_window(volume, icons, box=None, wb2=False):
    """The disk's Workbench window: its icons where the disk put them, labelled below."""
    pal = WB20 if wb2 else WB13
    qicons = [(name, _qimage(img), pos) for name, img, pos in icons]
    qicons = [(n, q, pos) for n, q, pos in qicons if q is not None]
    label = _font(13)
    fm = QFontMetrics(label)
    # Lay out icons that have no position of their own in rows, as Workbench's Clean Up did.
    placed, x, y, row_h = [], 10, 6, 0
    free = [ic for ic in qicons if ic[2] is None]
    for name, q, pos in qicons:
        if pos is not None:
            placed.append((name, q, pos[0], pos[1]))
    for name, q, _ in free:
        cell = max(q.width(), min(fm.horizontalAdvance(name), 120)) + 20
        if x + cell > 620:
            x, y = 10, y + row_h + 24
            row_h = 0
        placed.append((name, q, x, y))
        x += cell
        row_h = max(row_h, q.height())
    if not placed:
        return None
    # The window: Disk.info's size if it covers the icons, else just big enough for them.
    min_x = min(px for _, _, px, _ in placed)
    min_y = min(py for _, _, _, py in placed)
    right = max(px - min_x + max(q.width(), fm.horizontalAdvance(n)) for n, q, px, _ in placed)
    bottom = max(py - min_y + q.height() for _, q, _, py in placed)
    w, h = (box if box else (0, 0))
    w = min(640, max(w, right + 40, 240))
    h = min(256, max(h, bottom + 30, 90))
    bar = 22
    img = QImage(w, bar + h * SCALE_Y, QImage.Format.Format_RGB32)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    _window_frame(p, w, img.height(), volume, pal)
    p.setFont(label)
    for name, q, px, py in placed:
        ix = 14 + (px - min_x)
        iy = bar + 8 + (py - min_y) * SCALE_Y
        p.drawImage(QRect(ix, iy, q.width(), q.height() * SCALE_Y), q)
        text = fm.elidedText(name, Qt.TextElideMode.ElideRight, 150)
        tw = fm.horizontalAdvance(text)
        tx = max(4, min(w - 4 - tw, ix + q.width() // 2 - tw // 2))     # kept inside the window
        p.setPen(pal["text"])
        p.drawText(tx, iy + q.height() * SCALE_Y + fm.ascent() + 2, text)
    p.end()
    return _png(img)


def shell_window(volume, entries):
    """An AmigaDOS Shell window listing the disk, the way "dir" did: drawers first, then files
    in two columns."""
    pal = WB13
    font = _font(15)
    fm = QFontMetrics(font)
    line = fm.height() + 2
    dirs = sorted((n for n, d in entries if d), key=str.lower)
    files = sorted((n for n, d in entries if not d), key=str.lower)
    col = 32
    lines = [f"1> dir {volume}:"]
    lines += [f"     {n} (dir)" for n in dirs]
    for i in range(0, len(files), 2):
        pair = files[i:i + 2]
        lines.append("  " + pair[0][:col - 4].ljust(col) + ("  " + pair[1][:col - 4] if len(pair) > 1 else ""))
    lines.append("1> ")
    rows = 22
    if len(lines) > rows:
        more = len(lines) - rows + 1
        lines = lines[:rows - 2] + [f"  … and {more} more", "1> "]
    w = 640
    bar = 22
    h = bar + 14 + line * max(len(lines), 6)
    img = QImage(w, h, QImage.Format.Format_RGB32)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    _window_frame(p, w, h, "AmigaShell", pal)
    p.setFont(font)
    p.setPen(pal["text"])
    y = bar + 8 + fm.ascent()
    for text in lines:
        p.drawText(10, y, text)
        y += line
    p.fillRect(10 + fm.horizontalAdvance("1> "), y - line - fm.ascent() + 2, fm.horizontalAdvance("M"),
               fm.height() - 2, pal["accent"])           # the cursor
    p.end()
    return _png(img)
