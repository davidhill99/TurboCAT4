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
               B bootable (the disk starts by itself when the Amiga is switched on),
               F favourite (starred in TurboCAT), U utility or application
        disk path: what the emulator can put in a drive (ADF, ADZ, DMS or a ZIP of one disk), or -
TurboCAT.fil     F <tab> number <tab> path inside <tab> size     (every file, in item order)
TurboCAT.idx     number <tab> byte offset of its first line in TurboCAT.fil
TurboCAT.mus     T <tab> number <tab> title <tab> format <tab> seconds <tab> where <tab> F or -
"""
import os
import platform
import re
import time

from . import favourites, pictures

FLAG_ORDER = "GMPWDENHBFU"
PROGRAM = os.path.join(os.path.dirname(__file__), "amiga", "TurboView")   # built from amiga/turboview.c
# SCREEN=SUPER: TurboView opens its own 1280x512 screen (super-hires, interlaced), so on a big
# monitor it is a window in the middle of the screen rather than the whole Workbench blown up to
# fill it. The emulator is told to show super-hires detail (see emulator.turboview_command).
STARTUP = "; Written by TurboCAT: starts TurboView when the emulator boots from this folder\n" \
          "TurboCAT:TurboView TurboCAT: SCREEN={screen}\n"
# SCREEN=SUPER: 1280x512, sharp, for Amiberry. SCREEN=HIGH: 640x512, for FS-UAE, which shows only
# part of a super-hires screen.
SCREENS = ("SUPER", "HIGH")


def default_folder():
    if os.environ.get("TURBOCAT_TURBOVIEW_DIR"):     # the tests: never the user's own TurboView
        return os.environ["TURBOCAT_TURBOVIEW_DIR"]
    base = os.path.expanduser("~/Amiberry")
    return os.path.join(base, "HardDrives", "TurboCAT") if os.path.isdir(base) \
        else os.path.expanduser("~/TurboCAT-Amiga")


def install(folder, screen="SUPER"):
    """Put TurboView and a boot script in the folder, so an emulator can boot straight into it.
    screen: "SUPER" or "HIGH" (see SCREENS). Returns True if the TurboView program is there."""
    import shutil
    os.makedirs(os.path.join(folder, "S"), exist_ok=True)
    with open(os.path.join(folder, "S", "Startup-Sequence"), "w", newline="\n") as f:
        f.write(STARTUP.format(screen=screen if screen in SCREENS else "SUPER"))
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


MAX_DEPTH = 16          # no real disk in a large collection goes past 8 folders deep
MAX_PATH = 255          # nor past AmigaDOS's longest path


def junk_path(path):
    """A path no real disk has: from a damaged directory that loops back on itself, which a scan
    follows into nonsense hundreds of folders deep (one such disk added 1.2 MB of these)."""
    return len(path) > MAX_PATH or path.count("/") >= MAX_DEPTH


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
             "N": it.non_dos, "H": it.hard_drive, "B": bootable(it),
             "F": getattr(it, "favourite", False), "U": bool(getattr(it, "utility", ""))}
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
            junk = 0
            for f in rows[n]:
                if junk_path(f["path"]):
                    junk += 1
                    continue
                line = f"F\t{n}\t{_txt(f['path'])}{'/' if f['is_dir'] else ''}\t{f['size'] or 0}\n"
                fil.write(line.encode("latin-1", "replace"))
            if junk:
                fil.write(f"F\t{n}\t({junk} entries left out: this disk's damaged directory loops)\t0\n"
                          .encode("latin-1"))
    starred = favourites.load(cat)
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
                fav = "F" if favourites.tune_key(r) in starred else "-"
                mus.write("\t".join(["T", str(it.number), _txt(title), _txt(r["fmt"]),
                                     str(int(round(dur))), _txt(r["shown"]), fav]) + "\n")
    for name, path in tmp.items():
        os.replace(path, os.path.join(folder, name))
    return {"items": len(items), "files": sum(len(v) for v in rows.values()), "folder": folder}


# ---------------------------------------------------------------- for a real Amiga

FLOPPY_NAME = "TurboView.adf"
SEARCH_FLOPPY_NAME = "TurboView2.adf"
FLOPPY_STARTUP = ("; Written by TurboCAT: starts TurboView from this disk\n"
                  "TurboView SYS:\n")
FLOPPY_README = """TurboView - the Amiga side of TurboCAT
=======================================

This is disk 1 of 2 ("TurboView"). It lists your Amiga collection, as catalogued by
TurboCAT on {host} on {made}. Boot from it and TurboView starts by itself: search for a
game, tool or disk by name to see which disk (or Gotek image) holds it.

{files}
Disk 2 ("TurboView2") is the search disk: boot from it to search every file name
quickly. With both disks in two drives, TurboView uses each for what it does best.

To put TurboView on your hard drive: start your Amiga from the hard drive, put this disk
in a drive, and in a Shell type (with your own drive and drawer):
    TurboView:TurboView INSTALL DH0:TurboCAT
It copies everything, asks for disk 2 when it needs it, and unpacks the list of files.
Then double-click TurboView in its drawer, or start it from a Shell with:
    DH0:TurboCAT/TurboView DH0:TurboCAT
The hard drive install is NEW AND EXPERIMENTAL: it hasn't been tried on a real Amiga yet.
It's meant for an A1200 or any Amiga with Kickstart 2.04 or later; on a Kickstart 1.3
A500 TurboView only runs from the Shell. Please tell us how it went: in TurboCAT,
Help > How TurboView went on your Amiga.

Make new TurboView disks in TurboCAT after you scan new disks, so it knows about them.
"""
SEARCH_README = """TurboView - the search disk
===========================

This is disk 2 of 2 ("TurboView2"), made by TurboCAT on {host} on {made}. Boot from it
to search every file name on every disk quickly: it holds an index of the names and
which disks they are on.

A disk's full list of files is on disk 1 ("TurboView"): boot from disk 1, or put it in
a second drive (DF1:) and TurboView here will use it.
"""
FILES_NOTE_IN = "The list of every file on every disk is on it too: TurboView can show a disk's contents.\n"
FILES_NOTE_PACKED = ("The list of every file on every disk is on it too, packed to fit (sizes left out):\n"
                     "TurboView can show a disk's contents. Searching every file name from this disk\n"
                     "takes a while on an A500; disk 2 does it much faster.\n")
FILES_NOTE_OUT = ("The list of every file on every disk was too big for a floppy, so TurboView shows\n"
                  "each disk's name, type and problems, but not its contents. Disk 2 still finds\n"
                  "which disks a file is on; the hard drive install has everything.\n")
CATALOGUE_FILES = ("TurboCAT.cat", "TurboCAT.idx", "TurboCAT.mus", "TurboCAT.fil")


FZ_NAME = "TurboCAT.fz"
FZ_BLOCK = 32 * 1024        # unpacked bytes per block: one disk's contents unpacks on its own
FZ_MAGIC = b"TVFZ"
FZ_DISK_MAX = 64 * 1024     # one disk's list is cut here: TurboView needs a buffer as big as a block


def pack_file_list(fil):
    """TurboCAT.fil (bytes) packed to fit a floppy, as TurboCAT.fz. TurboView unpacks it with puff
    (amiga/puff.c, standard deflate).

    Header, big-endian longs: "TVFZ", version 1, blocks, biggest unpacked block, biggest packed
    block; then for each block: first disk, last disk, offset in the file, packed size, unpacked
    size. Each block is raw deflate of whole disks' lines: byte 1 then the disk's number starts a
    disk (byte 1 can't be mistaken for the next kind of line), and every other
    line is one byte (32 + how many characters it shares with the line before, at most 95) and
    then the rest of its path (folders end in "/"). Sizes are left out."""
    import struct
    import zlib
    disks, order = {}, []
    for line in fil.split(b"\n"):
        f = line.split(b"\t")
        if len(f) < 4 or f[0] != b"F":
            continue
        n = int(f[1])
        if n not in disks:
            disks[n] = []
            order.append(n)
        disks[n].append(f[2])
    texts = []
    for n in order:
        out, prev, size = [b"\x01%d\n" % n], b"", 0
        for i, path in enumerate(disks[n]):
            k = 0
            while k < min(len(path), len(prev), 95) and path[k] == prev[k]:
                k += 1
            line = bytes([32 + k]) + path[k:] + b"\n"
            if size + len(line) > FZ_DISK_MAX:
                out.append(b" (%d more left out: too many for TurboView's floppy)\n" % (len(disks[n]) - i))
                break
            out.append(line)
            size += len(line)
            prev = path
        texts.append((n, b"".join(out)))
    blocks, cur = [], []
    for n, t in texts:
        if cur and sum(len(x) for _, x in cur) + len(t) > FZ_BLOCK:
            blocks.append(cur)
            cur = []
        cur.append((n, t))
    if cur:
        blocks.append(cur)
    packed = []
    for b in blocks:
        raw = b"".join(t for _, t in b)
        c = zlib.compressobj(9, zlib.DEFLATED, -15)
        packed.append((b[0][0], b[-1][0], c.compress(raw) + c.flush(), len(raw)))
    head = 20 + 20 * len(packed)
    table, offset = [], head
    for first, last, data, ulen in packed:
        table.append(struct.pack(">5I", first, last, offset, len(data), ulen))
        offset += len(data)
    return (FZ_MAGIC + struct.pack(">4I", 1, len(packed), max((p[3] for p in packed), default=0),
                                   max((len(p[2]) for p in packed), default=0))
            + b"".join(table) + b"".join(p[2] for p in packed))


def unpack_file_list(fz):
    """{disk: [paths]} from TurboCAT.fz: what TurboView reads, for checking."""
    import struct
    import zlib
    if fz[:4] != FZ_MAGIC:
        raise ValueError("not a TurboCAT.fz")
    _v, n, _mu, _mc = struct.unpack(">4I", fz[4:20])
    out = {}
    for i in range(n):
        first, last, off, clen, ulen = struct.unpack(">5I", fz[20 + 20 * i:40 + 20 * i])
        raw = zlib.decompress(fz[off:off + clen], -15)
        assert len(raw) == ulen
        disk, prev = None, b""
        for line in raw.split(b"\n"):
            if not line:
                continue
            if line[:1] == b"\x01":
                disk, prev = int(line[1:]), b""
                out[disk] = []
                continue
            path = prev[:line[0] - 32] + line[1:]
            out[disk].append(path.decode("latin-1"))
            prev = path
    return out


NX_NAME = "TurboCAT.nix"
NX_MAGIC = b"TVNX"
NX_BLOCK = 32 * 1024        # unpacked names per block
# TurboView's lower-casing (amiga/turboview.c lower()): ASCII and Latin-1 capitals
_LOWER = bytes((c + 32) if (65 <= c <= 90 or (0xC0 <= c <= 0xDE and c != 0xD7)) else c for c in range(256))


def _varint(x):
    out = bytearray()
    while x >= 128:
        out.append(x & 127 | 128)
        x >>= 7
    out.append(x)
    return bytes(out)


def build_name_index(fil):
    """TurboCAT.nix, the search disk's name index, from TurboCAT.fil (bytes): every file and folder
    name once, with the disks it is on, so a search unpacks ~400 KB of names instead of every path.

    Header, big-endian longs: "TVNX", version 1, blocks, biggest names block unpacked/packed,
    biggest disks block unpacked/packed; then per block: entries, and the offset, packed and unpacked
    size of its names, then of its disks. Names: sorted without case, one per line, as one byte
    (32 + characters shared with the name before, at most 95) and the rest; folders end in "/".
    Disks (raw deflate too): per name, a varint count, then the disk numbers as varint gaps."""
    import struct
    import zlib
    by_low, shown = {}, {}
    for line in fil.split(b"\n"):
        f = line.split(b"\t")
        if len(f) < 4 or f[0] != b"F":
            continue
        n, path = int(f[1]), f[2]
        folder = path.endswith(b"/")
        name = path.rstrip(b"/").rsplit(b"/", 1)[-1] + (b"/" if folder else b"")
        if not name.strip(b"/"):
            continue
        low = name.translate(_LOWER)
        by_low.setdefault(low, set()).add(n)
        counts = shown.setdefault(low, {})
        counts[name] = counts.get(name, 0) + 1
    entries = [(max(shown[low].items(), key=lambda kv: (kv[1], kv[0]))[0], sorted(by_low[low]))
               for low in sorted(by_low)]

    def pack(raw):
        c = zlib.compressobj(9, zlib.DEFLATED, -15)
        return c.compress(raw) + c.flush()

    blocks, names, disks, prev, size = [], [], [], b"", 0
    for name, ds in entries:
        k = 0
        while k < min(len(name), len(prev), 95) and name[k] == prev[k]:
            k += 1
        line = bytes([32 + k]) + name[k:] + b"\n"
        if names and size + len(line) > NX_BLOCK:
            blocks.append((names, disks))
            names, disks, size, k = [], [], 0, 0
            line = bytes([32]) + name + b"\n"
        names.append(line)
        last, refs = 0, [_varint(len(ds))]
        for d in ds:
            refs.append(_varint(d - last))
            last = d
        disks.append(b"".join(refs))
        size += len(line)
        prev = name
    if names:
        blocks.append((names, disks))
    packed = [(len(nm), b"".join(nm), pack(b"".join(nm)), b"".join(dk), pack(b"".join(dk))) for nm, dk in blocks]
    head = 28 + 28 * len(packed)
    table, data, offset = [], [], head
    for count, nraw, npk, draw, dpk in packed:
        table.append(struct.pack(">7I", count, offset, len(npk), len(nraw), offset + len(npk), len(dpk), len(draw)))
        data += [npk, dpk]
        offset += len(npk) + len(dpk)
    mx = lambda i: max((p[i] if isinstance(p[i], int) else len(p[i]) for p in packed), default=0)
    return (NX_MAGIC + struct.pack(">6I", 1, len(packed), mx(1), mx(2), mx(3), mx(4))
            + b"".join(table) + b"".join(data))


def read_name_index(nx):
    """{name: [disks]} from TurboCAT.nix: what TurboView reads, for checking."""
    import struct
    import zlib
    if nx[:4] != NX_MAGIC:
        raise ValueError("not a TurboCAT.nix")
    _v, n = struct.unpack(">2I", nx[4:12])
    out = {}
    for i in range(n):
        count, noff, nclen, nulen, doff, dclen, dulen = struct.unpack(">7I", nx[28 + 28 * i:56 + 28 * i])
        names = zlib.decompress(nx[noff:noff + nclen], -15)
        disks = zlib.decompress(nx[doff:doff + dclen], -15)
        assert len(names) == nulen and len(disks) == dulen
        pos, prev = 0, b""

        def varint():
            nonlocal pos
            x, shift = 0, 0
            while True:
                b = disks[pos]
                pos += 1
                x |= (b & 127) << shift
                if b < 128:
                    return x
                shift += 7
        lines = [l for l in names.split(b"\n") if l]
        assert len(lines) == count
        for line in lines:
            name = prev[:line[0] - 32] + line[1:]
            prev = name
            c, last, ds = varint(), 0, []
            for _ in range(c):
                last += varint()
                ds.append(last)
            out[name.decode("latin-1")] = ds
    return out


def floppy_catalogue(data):
    """TurboCAT.cat for a floppy: the computer's own paths (each item's PC path and disk path, and
    the ROOT lines that map them to emulator drives) mean nothing on a real Amiga, so they become
    "-". About two thirds smaller. Every line keeps all its fields, as TurboView expects."""
    out = []
    for line in data.split(b"\n"):
        if line.startswith(b"ROOT\t"):
            continue
        if line.startswith(b"I\t"):
            f = line.split(b"\t")
            if len(f) >= 8:
                f[6] = f[7] = b"-"
                line = b"\t".join(f)
        out.append(line)
    return b"\n".join(out)


def _program(folder):
    program = PROGRAM if os.path.exists(PROGRAM) else os.path.join(folder, "TurboView")
    if not os.path.exists(program):
        raise ValueError("the TurboView program isn't there (see Check setup)")
    if not os.path.exists(os.path.join(folder, "TurboCAT.cat")):
        raise ValueError("TurboView's catalogue hasn't been written yet: start TurboView once, or scan")
    return program


def _made(folder):
    with open(os.path.join(folder, "TurboCAT.cat"), encoding="latin-1") as f:
        f.readline()
        m = re.match(r"MADE (.+?)\tHOST (.*?)\t", f.readline())
    return (m.group(1), m.group(2)) if m else ("?", "your computer")


def _floppy_image(volume, files, startup, readme):
    """A bootable OFS floppy image: files is [(name, bytes)]. Raises if they don't fit."""
    import io
    from amitools.fs.ADFSVolume import ADFSVolume
    from amitools.fs.FSString import FSString
    from amitools.fs.blkdev.ADFBlockDevice import ADFBlockDevice
    from . import repair
    fobj = io.BytesIO()
    dev = ADFBlockDevice(None, fobj=fobj)
    dev.create()
    vol = ADFSVolume(dev)
    vol.create(FSString(volume), boot_code=repair.STANDARD_BOOT)
    from . import wbicon
    root = vol.get_root_dir()
    for name, data in files:
        root.create_file(FSString(name), data)
    s_dir = root.create_dir(FSString("S"))
    s_dir.create_file(FSString("Startup-Sequence"), startup.encode("latin-1"))
    # for INSTALL to put on the hard drive (in S, so it doesn't show on this disk's Workbench window)
    s_dir.create_file(FSString("Drawer.icon"), wbicon.drawer_icon())
    root.create_file(FSString("ReadMe"), readme.encode("latin-1", "replace"))
    # Workbench icons: the disk, TurboView itself (no CATALOGUE tooltype: it reads this disk), the ReadMe
    root.create_file(FSString("Disk.info"), wbicon.disk_icon())
    root.create_file(FSString("TurboView.info"), wbicon.tool_icon())
    root.create_file(FSString("ReadMe.info"), wbicon.readme_icon())
    vol.close()
    dev.flush()
    return fobj.getvalue()


def _write(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _read(folder, name):
    path = os.path.join(folder, name)
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return f.read()


def make_floppy(folder, out_path):
    """Disk 1, "TurboView": a bootable floppy image with TurboView and the catalogue files from
    `folder` (written by export()), for a Gotek or a real floppy. The list of every file goes on as
    it is if it fits (files="full"), else packed as TurboCAT.fz (files="packed"), else not at all
    (files="none"). Returns dict(path, files, with_files) or raises ValueError if even the rest
    won't fit."""
    with open(_program(folder), "rb") as f:
        program = f.read()
    made, host = _made(folder)
    base = [("TurboView", program), ("TurboCAT.cat", floppy_catalogue(_read(folder, "TurboCAT.cat")))]
    if _read(folder, "TurboCAT.mus") is not None:
        base.append(("TurboCAT.mus", _read(folder, "TurboCAT.mus")))
    fil = _read(folder, "TurboCAT.fil")
    for mode in ("full", "packed", "none"):
        if mode != "none" and fil is None:
            continue
        files = list(base)
        if mode == "full":          # the index points into TurboCAT.fil, so it goes only with it
            files += [("TurboCAT.fil", fil)] + ([("TurboCAT.idx", _read(folder, "TurboCAT.idx"))]
                                                if _read(folder, "TurboCAT.idx") is not None else [])
        elif mode == "packed":
            files.append((FZ_NAME, pack_file_list(fil)))
        readme = FLOPPY_README.format(host=host, made=made, files={"full": FILES_NOTE_IN,
                                      "packed": FILES_NOTE_PACKED}.get(mode, FILES_NOTE_OUT))
        try:
            data = _floppy_image("TurboView", files, FLOPPY_STARTUP, readme)
        except Exception:
            continue                      # too big: try the next, smaller way
        _write(out_path, data)
        return {"path": out_path, "files": mode, "with_files": mode != "none"}
    raise ValueError("your catalogue is too big for a floppy, even without the list of files: use "
                     "\u201cFiles for your hard drive\u201d instead")


def make_search_floppy(folder, out_path):
    """Disk 2, "TurboView2": TurboView, the main list and the name index (build_name_index), so
    searching every file name unpacks a third as much and reads a third as much from the floppy.
    Returns dict(path) or raises ValueError if it won't fit."""
    with open(_program(folder), "rb") as f:
        program = f.read()
    fil = _read(folder, "TurboCAT.fil")
    if fil is None:
        raise ValueError("there is no list of files to index yet: scan first")
    made, host = _made(folder)
    files = [("TurboView", program), ("TurboCAT.cat", floppy_catalogue(_read(folder, "TurboCAT.cat"))),
             (NX_NAME, build_name_index(fil))]
    if _read(folder, "TurboCAT.mus") is not None:
        files.append(("TurboCAT.mus", _read(folder, "TurboCAT.mus")))
    try:
        data = _floppy_image("TurboView2", files, FLOPPY_STARTUP, SEARCH_README.format(host=host, made=made))
    except Exception:
        raise ValueError("the search index is too big for a floppy: use the hard drive install instead")
    _write(out_path, data)
    return {"path": out_path}


def volume_of(adf_path):
    """The volume name of an ADF (from its root block), or "" if it isn't a readable DOS disk.
    Only the root block is read."""
    try:
        with open(adf_path, "rb") as f:
            f.seek(880 * 512)
            root = f.read(512)
    except OSError:
        return ""
    if len(root) < 512 or root[:4] != b"\0\0\0\x02" or root[508:512] != b"\0\0\0\x01":
        return ""
    return root[433:433 + min(root[432], 30)].decode("latin-1", "replace")


def gotek_slots(stick, count=2):
    """File names for the TurboView disks on a Gotek stick using numbered images (DSKAnnnn.ADF):
    the slots earlier TurboView disks are in (found by their volume names), so an update replaces
    them instead of piling up new ones; otherwise the first free numbers."""
    names = sorted(n for n in os.listdir(stick) if re.fullmatch(r"DSKA\d{4}\.ADF", n, re.I))
    by_volume = {}
    for n in names:
        v = volume_of(os.path.join(stick, n))
        if v in ("TurboView", "TurboView2") and v not in by_volume:
            by_volume[v] = n
    taken = {int(n[4:8]) for n in names}
    out = []
    for vol in ("TurboView", "TurboView2")[:count]:
        if vol in by_volume:
            out.append(by_volume[vol])
            continue
        i = 0
        while i in taken:
            i += 1
        taken.add(i)
        out.append(f"DSKA{i:04d}.ADF")
    return out


def copy_files(folder, dest):
    """The full TurboView (program and every catalogue file) into dest/TurboCAT, for an Amiga's
    hard drive. Returns the drawer written."""
    import shutil
    out = os.path.join(dest, "TurboCAT")
    os.makedirs(out, exist_ok=True)
    program = PROGRAM if os.path.exists(PROGRAM) else os.path.join(folder, "TurboView")
    shutil.copyfile(program, os.path.join(out, "TurboView"))
    for name in CATALOGUE_FILES:
        src = os.path.join(folder, name)
        if os.path.exists(src):
            shutil.copyfile(src, os.path.join(out, name))
    fil = _read(folder, "TurboCAT.fil")
    if fil is not None:                 # the name index makes file searches quick there too
        with open(os.path.join(out, NX_NAME), "wb") as f:
            f.write(build_name_index(fil))
    return out
