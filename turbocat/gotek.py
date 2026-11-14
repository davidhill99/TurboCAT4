"""Copy catalogued floppy disks to a Gotek USB stick (or any folder) as plain ADF files.

A Gotek drive with FlashFloppy firmware reads .adf files from a FAT-formatted stick and shows
their long names. Stock Gotek firmware and HxC-style "indexed" mode want numbered names
instead (DSKA0000.ADF, DSKA0001.ADF, ...), so both are offered.
"""
import gzip
import hashlib
import io
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field

from . import paths, tools
from .readers import DD_SIZE, HD_SIZE

FLOPPY_KINDS = ("adf", "adz", "dms")
ARCHIVE_KINDS = ("lha", "lzx", "zip")
STICK_FS = ("vfat", "exfat", "msdos", "fat", "fat32", "fat16", "fat12")


@dataclass
class Disk:
    """One floppy that can go on the stick."""
    media_id: int
    number: int            # the item's catalogue number
    name: str              # file name it will get on the stick (FlashFloppy naming)
    size: int              # ADF size once unpacked
    sha1: str
    status: str
    problems: list = field(default_factory=list)


@dataclass
class Plan:
    disks: list = field(default_factory=list)      # Disk
    skipped: list = field(default_factory=list)    # (number, file name, reason)

    @property
    def total(self):
        return sum(d.size for d in self.disks)


def _j(s, default):
    import json
    try:
        return json.loads(s) if s else default
    except ValueError:
        return default


def safe_name(name, limit=120):
    """A file name FAT and FlashFloppy accept: no reserved characters, sensible length."""
    name = re.sub(r'[\x00-\x1f<>:"/\\|?*]', "_", name).strip(" .")
    stem, ext = os.path.splitext(name)
    if len(name) > limit:
        name = stem[:limit - len(ext)].rstrip(" .") + ext
    return name or "disk.adf"


def _adf_name(path):
    base = os.path.basename(path.rstrip("/"))
    stem, ext = os.path.splitext(base)
    if ext.lower() in (".adf", ".adz", ".dms", ".zip", ".lha", ".lzh", ".lzx", ".gz"):
        base = stem
    if base.lower().endswith(".adf"):        # "Disk.adf.gz", "Disk.adf.zip"
        base = base[:-4]
    return safe_name(base + ".adf")


def _unpacked_size(m):
    info = _j(m["info"], {})
    return HD_SIZE if info.get("density") == "HD" else DD_SIZE


def plan(cat, top_ids):
    """Work out which floppies the chosen items hold, and why any are left out."""
    p = Plan()
    used = set()
    for tid in top_ids:
        top = cat.media_by_id(tid)
        if top is None:
            continue
        label = os.path.basename(top["source"].rstrip("/"))
        # The item itself and everything found inside it, in catalogue order.
        rows, todo = [], [top]
        while todo:
            r = todo.pop(0)
            rows.append(r)
            todo += cat.db.execute("SELECT * FROM media WHERE parent_id=? ORDER BY id",
                                   (r["id"],)).fetchall()
        floppies = [r for r in rows if r["kind"] in FLOPPY_KINDS
                    # a DMS/ADZ inside an archive is the floppy; skip ADFs it was unpacked to
                    and not (r["parent_id"] and cat.media_by_id(r["parent_id"])["kind"] in ("dms", "adz"))]
        if not floppies:
            if top["whd_name"]:
                why = "WHDLoad game: it runs from a hard drive, not a floppy"
            elif top["kind"] in ("hdf", "folder"):
                why = "hard drive, not a floppy"
            elif cat.db.execute("SELECT 1 FROM files WHERE media_id IN (%s) AND lower(path) LIKE '%%.ipf' "
                                "LIMIT 1" % ",".join(str(r["id"]) for r in rows)).fetchone():
                why = ("IPF images (copy-protected originals): FlashFloppy can't read IPF; "
                       "convert them to HFE first")
            elif top["kind"] in ARCHIVE_KINDS:
                why = "archive with no floppy images in it"
            elif top["kind"] == "module":
                why = "a music module, not a floppy image"
            else:
                why = "not a floppy image"
            p.skipped.append((top["number"], label, why))
            continue
        for r in floppies:
            src = r["inner_path"] or r["source"]
            if r["status"] == "empty":
                p.skipped.append((top["number"], os.path.basename(src),
                                  "empty: a 0-byte file" if not r["size"] else "blank disk, nothing on it"))
                continue
            if r["kind"] == "dms" and not tools.which("xdms"):
                p.skipped.append((top["number"], os.path.basename(src),
                                  "DMS, and the 'xdms' tool is not installed to unpack it"))
                continue
            name = _adf_name(src if r["parent_id"] else top["source"])
            if name.lower() in used:
                stem, ext = os.path.splitext(name)
                name = safe_name(f"{stem} (#{top['number']:04d}){ext}")
                n = 2
                while name.lower() in used:
                    name = safe_name(f"{stem} (#{top['number']:04d}-{n}){ext}")
                    n += 1
            used.add(name.lower())
            p.disks.append(Disk(r["id"], top["number"], name, _unpacked_size(r), r["sha1"] or "",
                                r["status"] or "ok", _j(r["problems"], [])))
    return p


def _open_inner(data, kind, inner_path):
    """Pull one file out of an archive held in memory."""
    if kind == "zip":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for info in z.infolist():
                if info.filename.replace("\\", "/").rstrip("/") == inner_path:
                    return z.read(info)
    elif kind == "lha":
        import lhafile
        arc = lhafile.LhaFile(io.BytesIO(data))
        for info in arc.infolist():
            if info.filename.replace("\\", "/").rstrip("/") == inner_path:
                return arc.read(info.filename)
    elif kind == "adf" or kind in ("adz", "dms"):
        raise ValueError("files inside a disk image can't be unpacked yet")
    raise ValueError(f"{inner_path} not found in the {kind.upper()} archive")


def _unpack_floppy(kind, data):
    if kind == "adf":
        return data
    if kind == "adz":
        return gzip.decompress(data)
    exe = tools.which("xdms")
    with tempfile.TemporaryDirectory() as td:
        src, dst = os.path.join(td, "in.dms"), os.path.join(td, "out.adf")
        with open(src, "wb") as f:
            f.write(data)
        subprocess.run([exe, "-q", "u", src, "+" + dst], capture_output=True, **paths.no_window())
        if not os.path.exists(dst):
            raise ValueError("the DMS file could not be unpacked")
        with open(dst, "rb") as f:
            return f.read()


def adf_bytes(cat, media_id):
    """The plain ADF for a catalogued floppy, unpacked from whatever holds it."""
    chain = []
    m = cat.media_by_id(media_id)
    while m is not None:
        chain.append(m)
        m = cat.media_by_id(m["parent_id"]) if m["parent_id"] else None
    chain.reverse()                      # top-level file first
    with open(chain[0]["source"], "rb") as f:
        data = f.read()
    for outer, inner in zip(chain, chain[1:]):
        data = _open_inner(data, outer["kind"], inner["inner_path"])
    disk = chain[-1]
    adf = _unpack_floppy(disk["kind"], data)
    want = disk["sha1"]
    if want and hashlib.sha1(adf).hexdigest() != want:
        raise ValueError("the file has changed since it was catalogued; rescan it first")
    if len(adf) < DD_SIZE:               # truncated dump: pad so the Gotek accepts it
        adf += bytes(DD_SIZE - len(adf))
    return adf


def _sticks_from(volumes, system):
    """The likely Gotek sticks among Qt's mounted volumes (each with root, name, file system,
    ready, read-only, free bytes): FAT, writable, and not the system's own disk."""
    found = []
    for v in volumes:
        root, name, fs, ready, read_only, free = v
        if not ready or read_only or fs.lower() not in STICK_FS:
            continue
        if system == "windows":
            if root.rstrip("\\/").upper() == os.environ.get("SystemDrive", "C:").upper():
                continue                     # never the Windows drive itself
        elif system == "mac":
            if not root.startswith("/Volumes/"):
                continue                     # sticks appear in /Volumes
        found.append((root, name or os.path.basename(root.rstrip("\\/")) or root, free))
    return found


def _qt_volumes():
    from PySide6.QtCore import QStorageInfo
    return [(v.rootPath(), v.displayName(), bytes(v.fileSystemType()).decode("ascii", "replace"),
             v.isReady(), v.isReadOnly(), v.bytesAvailable()) for v in QStorageInfo.mountedVolumes()]


def find_sticks():
    """Mounted removable FAT drives, as (mount point, label, free bytes). Linux reads
    /proc/mounts; Windows (drive letters) and macOS (/Volumes) ask Qt for the drive list."""
    from . import paths
    if paths.system() != "linux":
        try:
            return _sticks_from(_qt_volumes(), paths.system())
        except Exception:
            return []
    found = []
    try:
        with open("/proc/mounts") as f:
            lines = f.read().splitlines()
    except OSError:
        return found
    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        mnt = parts[1].replace("\\040", " ")
        if parts[2] not in STICK_FS:
            continue
        if not (mnt.startswith("/media/") or mnt.startswith("/run/media/")):
            continue
        if not os.access(mnt, os.W_OK):
            continue
        try:
            free = shutil.disk_usage(mnt).free
        except OSError:
            continue
        found.append((mnt, os.path.basename(mnt), free))
    return found


def is_removable(path):
    path = os.path.normcase(os.path.realpath(path))
    for m, _, _ in find_sticks():
        m = os.path.normcase(os.path.realpath(m)).rstrip("\\/")
        if path == m or path.startswith(m + os.sep):
            return True
    return False


def next_index(dest):
    """First free DSKA number in a folder, for numbered (indexed) naming."""
    taken = set()
    try:
        for n in os.listdir(dest):
            mt = re.fullmatch(r"DSKA(\d{4})\.ADF", n, re.IGNORECASE)
            if mt:
                taken.add(int(mt.group(1)))
    except OSError:
        pass
    i = 0
    while i in taken:
        i += 1
    return i


def copy_disks(cat, disks, dest, numbered=False, progress=None, stop=lambda: False, written=None):
    """Write each Disk to dest. Returns (copied [(disk, file name)], failed [(disk, reason)],
    already there [(disk, file name)]). written(disk, file name, adf bytes) is called after each
    disk is written (the copier screen shows it)."""
    copied, failed, same = [], [], []
    index = next_index(dest) if numbered else 0
    for i, d in enumerate(disks):
        if stop():
            break
        if progress:
            progress(i, len(disks), d)
        try:
            adf = adf_bytes(cat, d.media_id)
        except Exception as ex:
            failed.append((d, str(ex)))
            continue
        if numbered:
            while os.path.exists(os.path.join(dest, f"DSKA{index:04d}.ADF")):
                index += 1
            name = f"DSKA{index:04d}.ADF"
            index += 1
        else:
            name = d.name
            target = os.path.join(dest, name)
            if os.path.exists(target):
                with open(target, "rb") as f:
                    if f.read() == adf:
                        same.append((d, name))
                        continue
                stem, ext = os.path.splitext(name)
                n = 2
                while os.path.exists(os.path.join(dest, f"{stem} ({n}){ext}")):
                    n += 1
                name = f"{stem} ({n}){ext}"
        target = os.path.join(dest, name)
        try:
            with open(target + ".part", "wb") as f:
                f.write(adf)
                f.flush()
                os.fsync(f.fileno())
            os.replace(target + ".part", target)
            if written:
                written(d, name, adf)
        except OSError as ex:
            try:
                os.remove(target + ".part")
            except OSError:
                pass
            failed.append((d, ex.strerror or str(ex)))
            if ex.errno == 28:          # disk full: no point trying the rest
                for rest in disks[i + 1:]:
                    failed.append((rest, "the stick is full"))
                break
            continue
        copied.append((d, name))
    if progress:
        progress(len(disks), len(disks), None)
    return copied, failed, same
