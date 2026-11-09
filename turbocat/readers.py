"""Readers for Amiga disk images and archives.

Every reader returns a ContainerResult: details about the container itself plus
a flat list of FileEntry objects describing what is inside it.
"""

import datetime
import gzip
import io
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from . import bootblock, lzx

DD_SIZE, HD_SIZE = 901120, 1802240
AMIGA_EPOCH = datetime.datetime(1978, 1, 1)


@dataclass
class FileEntry:
    path: str
    size: int = 0
    date: Optional[datetime.datetime] = None
    comment: str = ""
    protect: str = ""
    is_dir: bool = False
    read: Optional[Callable[[], bytes]] = None


@dataclass
class ContainerResult:
    kind: str                       # adf, adz, dms, hdf, lha, lzx, zip, folder
    volume: str = ""
    fs: str = ""
    boot: Optional[dict] = None
    files: List[FileEntry] = field(default_factory=list)
    problems: List[str] = field(default_factory=list)    # corruption / read errors
    warnings: List[str] = field(default_factory=list)    # suspicious, unsupported
    text: List[str] = field(default_factory=list)         # readable text (non-DOS)
    info: dict = field(default_factory=dict)              # extra details
    notes: List[str] = field(default_factory=list)        # harmless quirks worth knowing
    fs_issues: List[str] = field(default_factory=list)    # validator findings, judged later
    inner_image: Optional[bytes] = None                   # e.g. ADF unpacked from DMS


# ---------------------------------------------------------------- detection

def detect(name: str, head: bytes, size: int) -> Optional[str]:
    """Identify a file by its content (and size/extension as a fallback)."""
    ext = os.path.splitext(name)[1].lower()
    if head[:4] == b"DMS!":
        return "dms"
    if len(head) >= 7 and head[2:5] in (b"-lh", b"-lz") and head[6:7] == b"-":
        return "lha"
    if head[:3] == b"LZX":
        return "lzx"
    if head[:4] == b"PK\x03\x04":
        return "zip"
    if head[:8] in (b"UAE-1ADF", b"UAE--ADF"):
        return "extadf"
    if head[:2] == b"\x1f\x8b" and ext in (".adz", ".gz"):
        return "adz"
    if size in (DD_SIZE, HD_SIZE) or ext == ".adf":
        return "adf"
    if ext in (".hdf", ".hdz", ".hdd", ".rdb") or b"RDSK" in head[:512]:
        return "hdf"
    return None


# ---------------------------------------------------------------- AmigaDOS

def _walk_volume(vol) -> List[FileEntry]:
    out = []

    def walk(node, prefix):
        for e in node.get_entries_sorted_by_name():
            name = e.get_file_name().get_unicode_name()
            path = f"{prefix}{name}"
            mi = e.get_meta_info()
            try:
                date = AMIGA_EPOCH + datetime.timedelta(seconds=int(mi.get_mod_time()))
            except Exception:
                date = None
            try:
                comment = mi.get_comment_unicode_str() or ""
            except Exception:
                comment = ""
            prot = mi.get_protect_short_str() if hasattr(mi, "get_protect_short_str") else ""
            if e.is_dir():
                out.append(FileEntry(path, 0, date, comment, prot, True))
                walk(e, path + "/")
            else:
                out.append(FileEntry(path, e.get_size(), date, comment, prot, False,
                                     (lambda f=e: bytes(f.get_file_data()))))

    walk(vol.get_root_dir(), "")
    return out


def _validate(blkdev):
    """Run amitools' filesystem validator; return (errors, warnings) messages."""
    from amitools.fs.validate.Validator import Validator
    from amitools.fs.validate.Log import Log
    v = Validator(blkdev, min_level=Log.WARN)
    boot_dos, _ = v.scan_boot()
    if boot_dos and v.scan_root():
        v.scan_dir_tree()
        v.scan_files()
        v.scan_bitmap()
    errs = [str(e) for e in v.log.entries if e.level >= Log.ERROR]
    warns = [str(e) for e in v.log.entries if e.level == Log.WARN]
    return errs, warns


def read_dos_blkdev(blkdev, res: ContainerResult, validate=True):
    from amitools.fs.ADFSVolume import ADFSVolume
    vol = ADFSVolume(blkdev)
    vol.open()
    res.volume = vol.get_volume_name().get_unicode()
    res.files = _walk_volume(vol)
    if validate:
        try:
            errs, warns = _validate(blkdev)
        except Exception as ex:          # validator itself failed
            res.notes.append(f"filesystem check could not run: {ex}")
            return vol
        bitmap = [m for m in errs + warns if "bitmap" in m.lower()]
        if bitmap:
            # Games often leave the free-space map stale or blank on purpose; files still read.
            res.notes.append("free-space map (bitmap) does not match the files; common on game "
                             "disks and harmless while every file reads")
        res.fs_issues += [" ".join(m.split()) for m in errs + warns if m not in bitmap][:20]
    return vol


# ---------------------------------------------------------------- ADF

def read_adf(data: bytes, kind="adf", validate=True) -> ContainerResult:
    from amitools.fs.blkdev.ADFBlockDevice import ADFBlockDevice
    res = ContainerResult(kind)
    if len(data) < 1024:
        res.problems.append(f"not a usable ADF: only {len(data)} bytes")
        return res
    if len(data) not in (DD_SIZE, HD_SIZE):
        track = 11 * 512
        if len(data) < DD_SIZE:
            short = DD_SIZE - len(data)
            tracks = short / track
            what = (f"{int(tracks)} track{'s' if tracks != 1 else ''}" if short % track == 0
                    else f"{short:,} bytes")
            res.problems.append(f"truncated image: {what} short of a full disk "
                                f"({len(data):,} of {DD_SIZE:,} bytes); the end of the disk is missing")
            data = data + bytes(short)       # pad so whatever survives can still be listed
        else:
            # Overdumps (TOSEC "[o]"): the whole disk plus extra tracks past the end, usually
            # 81-84 cylinders. The disk itself is complete, so read it at its normal size.
            base = HD_SIZE if len(data) > HD_SIZE else DD_SIZE
            btrack = track * (2 if base == HD_SIZE else 1)
            extra = len(data) - base
            if extra % btrack == 0 and extra // btrack <= 10:
                n = extra // btrack
                tail = data[base:]
                res.notes.append(
                    f"overdump: {n} extra track{'s' if n != 1 else ''} past the end of the disk "
                    + ("(they hold data - some copy-protected disks use them)"
                       if tail.count(0) != len(tail) else "(blank)")
                    + "; the disk itself is complete")
                data = data[:base]
            else:
                res.problems.append(f"unexpected ADF size {len(data):,} bytes "
                                    f"(expected {DD_SIZE:,} or {HD_SIZE:,})")
                data = data[:HD_SIZE] if len(data) > HD_SIZE else data + bytes(HD_SIZE - len(data))
    hd = len(data) == HD_SIZE
    res.info["density"] = "HD" if hd else "DD"
    res.boot = bootblock.analyse(data[:1024])
    if res.boot["kind"].endswith("SUSPICIOUS"):
        res.warnings.append("bootblock: " + "; ".join(res.boot["flags"]))
    res.notes += [f"bootblock: {n}" for n in res.boot.get("notes", [])]
    res.fs = res.boot["fs"] or ""

    if res.boot["dos"] and len(data) in (DD_SIZE, HD_SIZE):
        try:
            blk = ADFBlockDevice(None, read_only=True, fobj=io.BytesIO(data), hd=hd)
            blk.open()
            read_dos_blkdev(blk, res, validate)
            return res
        except Exception as ex:
            if res.boot["bootable"]:
                # DOS boot code but no readable filesystem: custom loader disk
                res.info["format"] = "non-DOS (custom loader)"
            else:
                res.info["format"] = "custom-format data disk (AmigaDOS header only)"
                res.warnings.append("AmigaDOS header but no readable filesystem: usually a game "
                                    f"data disk in its own format, occasionally damage ({ex})")
    else:
        res.info["format"] = "non-DOS"

    # Non-DOS disk: record readable text and track usage for identification
    res.text = bootblock.readable_strings(data, 8, 60)
    track = 11 * 512 * (2 if hd else 1)
    blank = sum(1 for t in range(len(data) // track)
                if data[t * track:(t + 1) * track].count(0) == track)
    res.info["blank_tracks"] = blank
    return res


# ---------------------------------------------------------------- DMS / ADZ

def read_dms(data: bytes) -> ContainerResult:
    exe = shutil.which("xdms")
    if not exe:
        r = ContainerResult("dms")
        r.warnings.append("DMS not unpacked: the 'xdms' tool is not installed")
        return r
    with tempfile.TemporaryDirectory() as td:
        src, dst = os.path.join(td, "in.dms"), os.path.join(td, "out.adf")
        with open(src, "wb") as f:
            f.write(data)
        p = subprocess.run([exe, "-q", "u", src, "+" + dst], capture_output=True, text=True)
        if not os.path.exists(dst):
            r = ContainerResult("dms")
            r.problems.append("DMS could not be unpacked: "
                              + (p.stderr or p.stdout).strip()[:200])
            return r
        adf = open(dst, "rb").read()
    res = read_adf(adf, "dms")
    res.inner_image = adf
    if p.returncode != 0:
        res.problems.append("DMS unpacked with errors (CRC or packing problem)")
    return res


def read_adz(data: bytes) -> ContainerResult:
    try:
        adf = gzip.decompress(data)
    except Exception as ex:
        r = ContainerResult("adz")
        r.problems.append(f"ADZ could not be decompressed: {ex}")
        return r
    res = read_adf(adf, "adz")
    res.inner_image = adf
    return res


# ---------------------------------------------------------------- HDF

def read_hdf(path_or_data) -> ContainerResult:
    """Read a hard-disk image: RDB with partitions, or a single bare partition."""
    from amitools.fs.blkdev.RawBlockDevice import RawBlockDevice
    from amitools.fs.rdb.RDisk import RDisk
    res = ContainerResult("hdf")
    fobj = io.BytesIO(path_or_data) if isinstance(path_or_data, (bytes, bytearray)) else None
    fname = None if fobj else path_or_data
    raw = RawBlockDevice(fname, read_only=True, fobj=fobj)
    raw.open()
    try:
        rdisk = RDisk(raw)
        if rdisk.open():
            res.info["layout"] = "RDB"
            parts = []
            for i in range(rdisk.get_num_partitions()):
                p = rdisk.get_partition(i)
                dn = p.get_drive_name()
                pname = dn.get_unicode() if hasattr(dn, "get_unicode") else str(dn)
                pres = ContainerResult("partition")
                pname_desc = pname
                try:
                    blk = p.create_blkdev()
                    blk.open()
                    first = blk.read_block(0)
                    pres.boot = bootblock.analyse((first + blk.read_block(1))[:1024]) if blk.block_bytes == 512 else None
                    if first[:3] == b"DOS":
                        pres.fs = bootblock.DOS_TYPES.get(first[3], "")
                        read_dos_blkdev(blk, pres)
                        pname_desc = f"{pname} ({pres.volume}, {pres.fs})"
                    else:
                        tag = first[:4].rstrip(b"\x00")
                        pres.warnings.append(
                            f"partition {pname}: filesystem {tag.decode('latin-1', 'replace')!r} "
                            "is not supported yet (only OFS/FFS)")
                except Exception as ex:
                    pres.problems.append(f"partition {pname}: {ex}")
                parts.append(pname_desc)
                if pres.fs and not res.fs:
                    res.fs = pres.fs
                res.files += [FileEntry(f"{pname}:{fe.path}", fe.size, fe.date, fe.comment,
                                        fe.protect, fe.is_dir, fe.read) for fe in pres.files]
                res.problems += [f"{pname}: {m}" for m in pres.problems]
                res.warnings += [m if m.startswith("partition") else f"{pname}: {m}"
                                 for m in pres.warnings]
                if not res.volume and pres.volume:
                    res.volume = pres.volume
            res.info["partitions"] = parts
            return res
    except Exception as ex:
        res.problems.append(f"RDB could not be read: {ex}")
        return res

    # No RDB: try a bare partition image (common for emulator HDFs)
    res.info["layout"] = "single partition"
    first = raw.read_block(0)
    if first[:3] != b"DOS":
        res.warnings.append("not an AmigaDOS hard disk image (no RDB, no DOS partition)")
        return res
    from amitools.fs.blkdev.BlkDevFactory import BlkDevFactory
    res.fs = bootblock.DOS_TYPES.get(first[3], "")
    try:
        if fname:
            blk = BlkDevFactory().open(fname, read_only=True)
        else:
            tmp = tempfile.NamedTemporaryFile(suffix=".hdf", delete=False)
            tmp.write(path_or_data)
            tmp.close()
            blk = BlkDevFactory().open(tmp.name, read_only=True)
        read_dos_blkdev(blk, res)
    except Exception as ex:
        res.problems.append(f"filesystem unreadable: {ex}")
    finally:
        if not fname:
            os.unlink(tmp.name)
    return res


# ---------------------------------------------------------------- archives

def read_lha(data: bytes) -> ContainerResult:
    import lhafile
    res = ContainerResult("lha")
    try:
        arc = lhafile.LhaFile(io.BytesIO(data))
    except Exception as ex:
        res.problems.append(f"LHA archive unreadable: {ex}")
        return res
    for info in arc.infolist():
        name = info.filename.replace("\\", "/")
        is_dir = info.compress_type == b"-lhd-" or name.endswith("/")
        comment = info.comment.decode("latin-1") if isinstance(info.comment, bytes) else (info.comment or "")

        def reader(n=info.filename, a=arc):
            return a.read(n)

        res.files.append(FileEntry(name.rstrip("/"), info.file_size, info.date_time,
                                   comment, "", is_dir, None if is_dir else reader))
    return res


def read_zip(data: bytes) -> ContainerResult:
    """ZIP archives, as used by TOSEC and most download sites (usually one image each)."""
    import zipfile
    res = ContainerResult("zip")
    try:
        arc = zipfile.ZipFile(io.BytesIO(data))
    except Exception as ex:
        res.problems.append(f"ZIP archive unreadable: {ex}")
        return res
    for info in arc.infolist():
        name = info.filename.replace("\\", "/")
        is_dir = info.is_dir()
        try:
            date = datetime.datetime(*info.date_time)
        except ValueError:
            date = None

        def reader(i=info, a=arc):
            return a.read(i)

        res.files.append(FileEntry(name.rstrip("/"), info.file_size, date,
                                   info.comment.decode("latin-1", "replace"), "", is_dir,
                                   None if is_dir else reader))
    return res


def read_lzx(data: bytes) -> ContainerResult:
    res = ContainerResult("lzx")
    try:
        for e in lzx.list_lzx(data):
            res.files.append(FileEntry(e["name"], e["size"], e["date"], e["comment"]))
        res.info["note"] = "LZX: contents listed, files not unpacked"
    except Exception as ex:
        res.problems.append(f"LZX archive unreadable: {ex}")
    return res


# ---------------------------------------------------------------- folders

AMIGA_FOLDER_MARKERS = ("s/startup-sequence", "c/loadwb", "libs/exec.library",
                        "_uaefsdb.___", "devs/system-configuration")


def looks_like_amiga_folder(path: str) -> bool:
    for m in AMIGA_FOLDER_MARKERS:
        parts = m.split("/")
        cur = path
        ok = True
        for p in parts:
            try:
                match = next((x for x in os.listdir(cur) if x.lower() == p), None)
            except (NotADirectoryError, PermissionError, FileNotFoundError):
                match = None
            if match is None:
                ok = False
                break
            cur = os.path.join(cur, match)
        if ok:
            return True
    return False


def read_folder(path: str) -> ContainerResult:
    res = ContainerResult("folder", volume=os.path.basename(os.path.normpath(path)))
    for root, dirs, files in os.walk(path):
        dirs.sort()
        rel_root = os.path.relpath(root, path)
        rel_root = "" if rel_root == "." else rel_root.replace(os.sep, "/") + "/"
        for d in dirs:
            st = os.stat(os.path.join(root, d))
            res.files.append(FileEntry(rel_root + d, 0,
                                       datetime.datetime.fromtimestamp(st.st_mtime), is_dir=True))
        for f in sorted(files):
            if f.lower() in ("_uaefsdb.___",) or f.lower().endswith(".uaem"):
                continue
            full = os.path.join(root, f)
            st = os.stat(full)
            res.files.append(FileEntry(rel_root + f, st.st_size,
                                       datetime.datetime.fromtimestamp(st.st_mtime),
                                       read=(lambda p=full: open(p, "rb").read())))
    return res


def read_module(data: bytes, name: str = "module") -> ContainerResult:
    """A music module on its own (a .mod, .xm, .s3m... in a PC folder): one item holding one tune."""
    from . import music
    res = ContainerResult("module")
    found = music.identify(name, data)
    if found:
        res.info["format"] = f"{found[0]} music module"
        if found[1]:
            res.volume = found[1]
    res.files.append(FileEntry(os.path.basename(name), len(data), None, "", "", False,
                               (lambda d=data: d)))
    return res


READERS = {"adf": read_adf, "dms": read_dms, "adz": read_adz,
           "lha": read_lha, "lzx": read_lzx, "zip": read_zip,
           "module": read_module}
