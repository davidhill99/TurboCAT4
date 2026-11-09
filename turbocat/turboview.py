"""The TurboView catalogue: what the Amiga companion reads.

TurboCAT writes it into a folder that an emulator mounts as an Amiga drive (TurboCAT:), so the
emulated Amiga always sees the latest catalogue. Plain text, ISO-8859-1 (the Amiga's character
set), one record per line with TAB-separated fields, so it is quick to read with a few hundred KB
of memory and easy to check by eye:

TurboCAT.cat     header lines, then one line per item
    TURBOVIEW 1
    MADE <date>  HOST <computer>  ITEMS <n>
    ROOT <tab> <PC folder> <tab> <Amiga volume it is mounted as>
    I <tab> number <tab> flags <tab> type <tab> title <tab> file <tab> PC path <tab> disk path
        flags: G game, M music, P problem, W warning, D duplicate, E empty, N non-DOS, H hard drive,
               B bootable (the disk starts by itself when the Amiga is switched on)
        disk path: what the emulator can put in a drive (ADF, ADZ, DMS or a ZIP of one disk), or -
TurboCAT.fil     F <tab> number <tab> path inside <tab> size     (every file, in item order)
TurboCAT.idx     number <tab> byte offset of its first line in TurboCAT.fil
TurboCAT.mus     T <tab> number <tab> title <tab> format <tab> seconds <tab> where
"""
import os
import platform
import re
import time

from . import pictures

FLAG_ORDER = "GMPWDENHB"
PROGRAM = os.path.join(os.path.dirname(__file__), "amiga", "TurboView")   # built from amiga/turboview.c
STARTUP = "; Written by TurboCAT: starts TurboView when the emulator boots from this folder\n" \
          "TurboCAT:TurboView TurboCAT:\n"


def default_folder():
    base = os.path.expanduser("~/Amiberry")
    return os.path.join(base, "HardDrives", "TurboCAT") if os.path.isdir(base) \
        else os.path.expanduser("~/TurboCAT-Amiga")


def install(folder):
    """Put TurboView and a boot script in the folder, so an emulator can boot straight into it.
    Returns True if the TurboView program is there."""
    import shutil
    os.makedirs(os.path.join(folder, "S"), exist_ok=True)
    with open(os.path.join(folder, "S", "Startup-Sequence"), "w", newline="\n") as f:
        f.write(STARTUP)
    if os.path.exists(PROGRAM):
        shutil.copyfile(PROGRAM, os.path.join(folder, "TurboView"))
    return os.path.exists(os.path.join(folder, "TurboView"))


def _txt(s):
    """One field: no tabs or newlines, in the Amiga's character set."""
    s = re.sub(r"[\t\r\n]+", " ", str(s or ""))
    return s.encode("latin-1", "replace").decode("latin-1")


def volume_name(path, used):
    """A short Amiga volume name for a PC folder, e.g. 'AMIGA_STUFF'."""
    base = re.sub(r"[^A-Za-z0-9]+", "_", os.path.basename(path.rstrip("/")) or "PC").strip("_")
    base = (base or "PC")[:24]
    name, n = base, 2
    while name.upper() in used or name.upper() in ("TURBOCAT", "DH0", "RAM", "SYS"):
        name = f"{base[:21]}_{n}"
        n += 1
    used.add(name.upper())
    return name


def roots_with_volumes(cat):
    used = set()
    return [(r, volume_name(r, used)) for r in cat.scan_roots()]


def export(cat, items, folder):
    """Write the catalogue files into `folder` (the window's items, already worked out)."""
    os.makedirs(folder, exist_ok=True)
    roots = roots_with_volumes(cat)
    tunes = pictures.music_by_key(cat)
    disk_kinds = ("adf", "adz", "dms")

    def disk_path(it):
        m = cat.media_by_id(it.id)
        if m is None or m["status"] == "empty":
            return "-"
        if m["kind"] in disk_kinds:
            return m["source"]
        if m["kind"] == "zip":
            kids = cat.db.execute("SELECT kind FROM media WHERE parent_id=?", (m["id"],)).fetchall()
            if len(kids) == 1 and kids[0]["kind"] in disk_kinds:
                return m["source"]
        return "-"

    def bootable(it):
        rows = [cat.media_by_id(it.id)] + cat.db.execute(
            "SELECT * FROM media WHERE parent_id=?", (it.id,)).fetchall()
        return any(r is not None and r["kind"] in disk_kinds and
                   (r["boot_kind"] or "").startswith(("standard", "custom")) for r in rows)

    def flags(it):
        f = {"G": bool(it.game), "M": it.music > 0, "P": it.status == "error",
             "W": it.status == "warning", "D": it.dup, "E": it.status == "empty",
             "N": it.non_dos, "H": it.hard_drive, "B": bootable(it)}
        return "".join(k for k in FLAG_ORDER if f[k]) or "-"

    tmp = {name: os.path.join(folder, name + ".part") for name in
           ("TurboCAT.cat", "TurboCAT.fil", "TurboCAT.idx", "TurboCAT.mus")}
    enc = dict(encoding="latin-1", errors="replace", newline="\n")
    with open(tmp["TurboCAT.cat"], "w", **enc) as cat_f:
        cat_f.write("TURBOVIEW 1\n")
        cat_f.write(f"MADE {time.strftime('%Y-%m-%d %H:%M')}\tHOST {_txt(platform.node())}\t"
                    f"ITEMS {len(items)}\n")
        for path, vol in roots:
            cat_f.write(f"ROOT\t{_txt(path)}\t{vol}\n")
        for it in items:
            cat_f.write("\t".join(["I", str(it.number), flags(it), _txt(it.type), _txt(it.title),
                                   _txt(it.file), _txt(it.path), _txt(disk_path(it))]) + "\n")
    # Every file, grouped by item, with an index so the Amiga can jump straight to a disk.
    top = cat.top_ids()
    number = {it.id: it.number for it in items}
    rows = {}
    for f in cat.db.execute("SELECT media_id, path, size, is_dir FROM files ORDER BY id"):
        n = number.get(top.get(f["media_id"]))
        if n is not None:
            rows.setdefault(n, []).append(f)
    with open(tmp["TurboCAT.fil"], "wb") as fil, open(tmp["TurboCAT.idx"], "w", **enc) as idx:
        for n in sorted(rows):
            idx.write(f"{n}\t{fil.tell()}\n")
            for f in rows[n]:
                line = f"F\t{n}\t{_txt(f['path'])}{'/' if f['is_dir'] else ''}\t{f['size'] or 0}\n"
                fil.write(line.encode("latin-1", "replace"))
    by_key = {}
    for it in items:
        by_key.setdefault(it.key, it)
    with open(tmp["TurboCAT.mus"], "w", **enc) as mus:
        for key, rs in tunes.items():
            it = by_key.get(key)
            if it is None:
                continue
            for r in rs:
                dur = r["duration"] if r["duration"] and r["duration"] > 0 else 0
                title = r["title"] or r["file"].rsplit("/", 1)[-1]
                mus.write("\t".join(["T", str(it.number), _txt(title), _txt(r["fmt"]),
                                     str(int(round(dur))), _txt(r["shown"])]) + "\n")
    for name, path in tmp.items():
        os.replace(path, os.path.join(folder, name))
    return {"items": len(items), "files": sum(len(v) for v in rows.values()), "folder": folder}
