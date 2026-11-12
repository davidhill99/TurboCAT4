"""Scan folders of Amiga disk images, archives and Amiga folders into the catalogue."""

import hashlib
import os
import time

from . import emulator, music, readers, whdload
from .catalogue import BLANK_SHA1
from .readers import detect, ContainerResult

MAX_DEPTH = 3                # containers inside containers (e.g. ADF in LHA in HDF)
MAX_INNER_SIZE = 64 << 20    # don't unpack inner images larger than this
KEEP_INNER = 256 << 20       # inner files kept in memory until their turn; beyond this, read again
BIG_ARCHIVE = 200 << 20      # archives this big are listed first so the user can choose to skip them
ARCHIVE_KINDS = ("zip", "lha", "lzx", "dms", "adz")
DEFAULT_RATE = 2.5 * (1 << 20)   # bytes a second, for an archive of zipped disks (measured: 790 MB in 5 min)
RATE_KEY = "archive_read_rate"   # the speed measured on this computer, kept in the catalogue
LOAD_SHARE = 0.03                # of a big file's progress: loading it from disk
LIST_SHARE = 0.05                # listing what is in it (opening what is inside is the rest)
SHOW_INSIDE = 50 << 20           # files this big report their loading, so the window never looks stuck


def read_rate(catalogue):
    """How fast this computer reads big archives, in bytes a second."""
    try:
        return float(catalogue.get_meta(RATE_KEY) or DEFAULT_RATE)
    except (TypeError, ValueError):
        return DEFAULT_RATE
FOLDER_WEIGHT = 1 << 20      # Amiga folders: size unknown until read; count as 1 MB for progress


def _sha1(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()


def _status(res: ContainerResult) -> str:
    if res.problems:
        return "error"
    if res.warnings:
        return "warning"
    return "ok"


def analyse_container(kind, data, name, source, depth, catalogue, parent_id, number=None,
                      path_on_disk=None, tick=None):
    """Read one container, store it, then recurse into containers found inside.
    tick(inner path, fraction or None), if given, is called as files inside are read, so a big
    archive (an archive of a thousand archives) shows progress and can be stopped part way."""
    try:
        if kind == "hdf":
            res = readers.read_hdf(path_on_disk if path_on_disk else data)
        elif kind == "folder":
            res = readers.read_folder(path_on_disk)
        elif kind == "module":
            res = readers.read_module(data, name)
        elif kind == "kickstart":
            res = readers.read_kickstart(data, path_on_disk or "")
        elif kind == "extadf":
            res = ContainerResult("extadf")
            res.warnings.append("extended ADF (MFM/copy-protected) not supported yet")
        else:
            res = readers.READERS[kind](data)
    except Exception as ex:
        res = ContainerResult(kind)
        res.problems.append(f"could not read: {ex}")

    files, inner = [], []
    unreadable = 0
    kept = 0
    total_size = sum(fe.size or 0 for fe in res.files if not fe.is_dir) or 1
    read_size = 0
    for fe in res.files:
        sha = None
        content = None
        if not fe.is_dir and fe.read:
            try:
                content = fe.read()
                sha = _sha1(content)
            except Exception as ex:
                unreadable += 1
                res.problems.append(f"file unreadable: {fe.path} ({ex})")
            read_size += fe.size or 0
            if tick:
                if depth == 0:
                    # listing is quick; opening what is inside takes the time
                    tick(fe.path, LOAD_SHARE + LIST_SHARE * read_size / total_size, len(files) + 1,
                         len(res.files), "inside-read")
                else:
                    tick(fe.path, None)
        files.append({"path": fe.path, "size": fe.size,
                      "date": fe.date.isoformat(sep=" ") if fe.date else None,
                      "comment": fe.comment, "protect": fe.protect,
                      "sha1": sha, "is_dir": fe.is_dir})
        if content is None:
            continue
        lname = fe.path.lower()
        if lname.endswith(".slave"):
            slave = whdload.parse_slave(content)
            if slave and "whd_name" not in res.info:
                res.info["whd_name"] = slave["name"]
                res.info["whd_copy"] = slave["copyright"]
                res.info["whd_info"] = slave["info"]
                res.info["whd_slave"] = fe.path
        if depth < MAX_DEPTH and 0 < len(content) <= MAX_INNER_SIZE:
            k = detect(fe.path, content[:1024], len(content))
            if k:
                if kept + len(content) <= KEEP_INNER:
                    kept += len(content)
                    inner.append((k, content, fe.path, None, len(content)))
                else:                    # read it again when its turn comes
                    inner.append((k, None, fe.path, fe.read, len(content)))

    # Judge filesystem findings by their effect: if every file reads, they are quirks.
    if res.fs_issues:
        if unreadable:
            res.problems += [f"filesystem: {m}" for m in res.fs_issues]
        else:
            res.warnings += [f"filesystem inconsistency, but every file reads: {m}"
                             for m in res.fs_issues]
    if res.notes:
        res.info["notes"] = res.notes

    whole = data if data is not None else None
    rec = {
        "source": source, "inner_path": name if parent_id else "",
        "kind": res.kind, "size": len(whole) if whole is not None else None,
        "sha1": _sha1(res.inner_image) if res.inner_image else (_sha1(whole) if whole is not None else None),
        "volume": res.volume, "fs": res.fs,
        "boot_kind": (res.boot or {}).get("kind", ""),
        "boot_flags": (res.boot or {}).get("flags", []),
        "status": _status(res), "problems": res.problems, "warnings": res.warnings,
        "text": res.text, "info": res.info, "files": files,
        "whd_name": res.info.get("whd_name", ""), "whd_copy": res.info.get("whd_copy", ""),
        "whd_info": res.info.get("whd_info", ""),
    }
    if path_on_disk and parent_id is None:
        st = os.stat(path_on_disk)
        rec["mtime"] = st.st_mtime
        if rec["size"] is None:
            rec["size"] = st.st_size
        if kind == "folder":
            rec["size"] = sum(f["size"] for f in files)
        if rec["sha1"] is None and os.path.isfile(path_on_disk):
            h = hashlib.sha1()
            with open(path_on_disk, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            rec["sha1"] = h.hexdigest()
    if rec["sha1"] in BLANK_SHA1:
        rec["status"] = "empty"
    mid = catalogue.add_media(rec, parent_id, number)
    inner_total = sum(sz for _k, _c, _p, _a, sz in inner) or 1
    opened = 0
    for n, (k, content, p, again, size) in enumerate(inner):
        if tick:
            if depth == 0:
                tick(p, LOAD_SHARE + LIST_SHARE + (1 - LOAD_SHARE - LIST_SHARE) * opened / inner_total,
                     n + 1, len(inner),
                     "inside-open")
            else:
                tick(p, None)
        if content is None:
            try:
                content = again()
            except Exception:
                continue
        inner[n] = None                  # let it go once read
        opened += size
        sub = (lambda q, f, *_, p=p: tick(f"{p} › {q}", None)) if tick else None
        analyse_container(k, content, p, source, depth + 1, catalogue, mid, tick=sub)
    return mid, res


def rescan_all(catalogue, progress=print, step=None, confirm_big=None):
    """Rescan every folder the catalogue was built from: new and changed files are read,
    unchanged ones skipped, and items whose files have been deleted are removed."""
    roots = catalogue.scan_roots()
    summary = scan(roots, catalogue, progress=progress, step=step, confirm_big=confirm_big)
    summary["removed"] = catalogue.remove_missing(roots)
    summary["roots"] = roots
    return summary


def recheck(files, catalogue, progress=print, step=None, confirm_big=None):
    """Look again at chosen items only, instead of every folder (Disk > Recheck): their own
    files are read again whatever their dates say, and the folders they are in (not the folders
    inside those) are checked for new, changed and deleted files, so a disk of a set that was
    replaced, added or removed is picked up. Folders scanned before stay as they were."""
    files = [os.path.abspath(f) for f in files]
    folders = sorted({os.path.dirname(f) for f in files})
    summary = scan(folders, catalogue, progress=progress, step=step, confirm_big=confirm_big,
                   shallow=True, add_roots=False, force=set(files))
    summary["removed"] = catalogue.remove_missing(folders)
    summary["roots"] = folders
    return summary


def scan(paths, catalogue, rescan=False, progress=print, folders_as_volumes=False, step=None,
         confirm_big=None, shallow=False, add_roots=True, force=()):
    """Scan files and folders. Returns a summary dict.

    progress(text) gets a line per item read. step(phase, done, total, done_bytes,
    total_bytes, path), if given, is called often enough to drive a progress bar: phase
    "checking" while working out what is new or changed, then "reading" once per file. While
    one file is read, "inside-load" (a big file loading from disk: done and total in MB),
    "inside-read" (its list of files: done and total count them) and then
    "inside-open" (the disks and archives inside it) report how far into it the scan is, with
    done_bytes and total_bytes counting through that file only, and path "file › inner path".

    confirm_big(big, rate), if given, is asked about archives of BIG_ARCHIVE or more before
    any are read: big is [(path, kind, size)], rate the reading speed in bytes a second; it
    returns the paths to read. The others are left for another time (summary "held_back").

    shallow: only the files directly in each folder (and Amiga folders there), not the folders
    inside it. add_roots: remember these folders for Rescan. force: files read again even if
    their size and date haven't changed.
    """
    summary = {"scanned": 0, "skipped": 0, "ignored": 0}
    found = [os.path.abspath(os.path.expanduser(p)) for p in paths]
    if add_roots:
        catalogue.add_scan_roots([p for p in found if os.path.exists(p)])
    todo = []
    for p in paths:
        p = os.path.abspath(os.path.expanduser(p))
        if not os.path.exists(p):
            summary.setdefault("missing", []).append(p)
            if progress:
                progress(f"Not found, skipped: {p}")
            continue
        if os.path.isdir(p):
            if folders_as_volumes or readers.looks_like_amiga_folder(p):
                todo.append(("folder", p))
                continue
            for root, dirs, fnames in os.walk(p):
                dirs.sort()
                keep = []
                for d in dirs:
                    full = os.path.join(root, d)
                    if readers.looks_like_amiga_folder(full):
                        todo.append(("folder", full))
                    else:
                        keep.append(d)
                dirs[:] = [] if shallow else keep
                for f in sorted(fnames):
                    todo.append((None, os.path.join(root, f)))
        else:
            todo.append((None, p))

    # Items that couldn't be read fully for want of a helper program (lha, xdms) that has been
    # installed since: read them again once, even though their files haven't changed.
    tools_now = readers.helper_tools()
    new_tools = set(tools_now) - set(catalogue.get_meta("helper_tools", []))
    retry = catalogue.sources_with_message(sorted({readers.HELPER_TOOLS[t] for t in new_tools}))

    # Pass 1 - decide what needs reading. Cheap: a size and date check for files already
    # catalogued, and the first 1 KB of anything new to recognise it.
    work = []
    for i, (kind, path) in enumerate(todo):
        if step and i % 25 == 0:
            step("checking", i, len(todo), 0, 0, path)
        try:
            st = os.stat(path)
        except OSError:
            summary["ignored"] += 1
            continue
        if kind == "folder":
            work.append(("folder", path, FOLDER_WEIGHT))
            continue
        size, mtime = st.st_size, st.st_mtime
        if (not rescan and path not in force and path not in retry
                and catalogue.known_unchanged(path, size, mtime)):
            summary["skipped"] += 1
            continue
        try:
            with open(path, "rb") as fh:
                head = fh.read(2048)
        except OSError:
            summary["ignored"] += 1
            continue
        kind = detect(path, head[:1024], size)
        if kind is None and emulator.looks_like_rom(head, size):
            kind = "kickstart"       # a Kickstart ROM: Play in emulator and TurboView use these
        if kind is None and music.identify(os.path.basename(path), head):
            kind = "module"          # a tune on its own, straight from a PC folder
        if kind is None:
            summary["ignored"] += 1
            continue
        work.append((kind, path, size))

    # Big archives take minutes each (an archive of a thousand zipped disks): ask first.
    big = [(path, kind, size) for kind, path, size in work
           if kind in ARCHIVE_KINDS and size >= BIG_ARCHIVE]
    if big and confirm_big:
        wanted = set(confirm_big(big, read_rate(catalogue)))
        held = [path for path, _k, _s in big if path not in wanted]
        if held:
            summary["held_back"] = held
            work = [w for w in work if w[1] not in set(held)]

    # Pass 2 - read them, reporting progress by bytes so big images count for more.
    total_bytes = sum(w[2] for w in work)
    done_bytes = 0
    if step:
        step("reading", 0, len(work), 0, total_bytes, "")
    for i, (kind, path, size) in enumerate(work):
        if step:
            step("reading", i, len(work), done_bytes, total_bytes, path)
        number = catalogue.remove_source(path) or catalogue.next_number()
        data = None
        if kind not in ("hdf", "folder"):
            with open(path, "rb") as fh:
                if step and size >= SHOW_INSIDE:
                    # a big file takes a while to load from disk: count it in
                    parts, got = [], 0
                    step("inside-load", 0, size >> 20, 0, size, path)
                    for chunk in iter(lambda: fh.read(16 << 20), b""):
                        parts.append(chunk)
                        got += len(chunk)
                        step("inside-load", got >> 20, size >> 20, int(size * LOAD_SHARE * got / size),
                             size, path)
                    data = b"".join(parts)
                    del parts
                else:
                    data = fh.read()
        tick = None
        started = time.monotonic()
        if step:
            # when it last reported, how far into the file, which count, of how many, which stage
            last = [started, 0.0, 0, 0, "inside-read"]

            def tick(inner, frac, n=None, of=None, stage=None, path=path, size=size, last=last):
                if frac is not None:
                    last[1] = frac
                if n is not None:
                    last[2:5] = [n, of, stage]
                now = time.monotonic()
                if now - last[0] >= 0.25:
                    last[0] = now
                    step(last[4], last[2], last[3], int(size * last[1]), size, f"{path} › {inner}")
        try:
            mid, res = analyse_container(kind, data, os.path.basename(path), path, 0, catalogue,
                                         None, number, path_on_disk=path, tick=tick)
        except BaseException:
            # stopped part way through: leave this file as it was, so the next scan reads it again
            catalogue.db.rollback()
            raise
        data = None
        catalogue.commit()
        took = time.monotonic() - started
        if kind in ARCHIVE_KINDS and size >= 32 << 20 and took > 1:
            # remember how fast this computer reads big archives, for the next estimate
            catalogue.set_meta(RATE_KEY, round(0.5 * read_rate(catalogue) + 0.5 * size / took))
        summary["scanned"] += 1
        done_bytes += size
        if progress:
            status = catalogue.media_by_id(mid)["status"]
            flag = {"ok": "", "warning": "  [warning]", "error": "  [PROBLEM]",
                    "empty": "  [empty]"}[status]
            progress(f"#{number:04d} {kind.upper():6} {os.path.basename(path)}{flag}")
    if step:
        step("reading", len(work), len(work), total_bytes, total_bytes, "")
    if retry <= {p for _, p in todo}:
        catalogue.set_meta("helper_tools", tools_now)   # all read again with the tools there are now
    return summary
