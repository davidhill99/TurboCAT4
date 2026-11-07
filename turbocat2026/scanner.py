"""Scan folders of Amiga disk images, archives and Amiga folders into the catalogue."""

import hashlib
import os

from . import readers, whdload
from .readers import detect, ContainerResult

MAX_DEPTH = 3                # containers inside containers (e.g. ADF in LHA in HDF)
MAX_INNER_SIZE = 64 << 20    # don't unpack inner images larger than this


def _sha1(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()


def _status(res: ContainerResult) -> str:
    if res.problems:
        return "error"
    if res.warnings:
        return "warning"
    return "ok"


def analyse_container(kind, data, name, source, depth, catalogue, parent_id, number=None,
                      path_on_disk=None):
    """Read one container, store it, then recurse into containers found inside."""
    try:
        if kind == "hdf":
            res = readers.read_hdf(path_on_disk if path_on_disk else data)
        elif kind == "folder":
            res = readers.read_folder(path_on_disk)
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
                inner.append((k, content, fe.path))

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
    mid = catalogue.add_media(rec, parent_id, number)
    for k, content, p in inner:
        analyse_container(k, content, p, source, depth + 1, catalogue, mid)
    return mid, res


def scan(paths, catalogue, rescan=False, progress=print, folders_as_volumes=False):
    """Scan files and folders. Returns a summary dict."""
    summary = {"scanned": 0, "skipped": 0, "ignored": 0}
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
                dirs[:] = keep
                for f in sorted(fnames):
                    todo.append((None, os.path.join(root, f)))
        else:
            todo.append((None, p))

    for kind, path in todo:
        if kind == "folder":
            st = os.stat(path)
            size, mtime = 0, st.st_mtime
        else:
            st = os.stat(path)
            size, mtime = st.st_size, st.st_mtime
            with open(path, "rb") as fh:
                head = fh.read(1024)
            kind = detect(path, head, size)
            if kind is None:
                summary["ignored"] += 1
                continue
        if not rescan and kind != "folder" and catalogue.known_unchanged(path, size, mtime):
            summary["skipped"] += 1
            continue
        number = catalogue.remove_source(path) or catalogue.next_number()
        data = None
        if kind not in ("hdf", "folder"):
            with open(path, "rb") as fh:
                data = fh.read()
        _, res = analyse_container(kind, data, os.path.basename(path), path, 0, catalogue,
                                   None, number, path_on_disk=path)
        catalogue.commit()
        summary["scanned"] += 1
        if progress:
            flag = {"ok": "", "warning": "  [warning]", "error": "  [PROBLEM]"}[_status(res)]
            progress(f"#{number:04d} {kind.upper():6} {os.path.basename(path)}{flag}")
    return summary
