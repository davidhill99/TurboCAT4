"""Command-line front end for the TurboCAT 4 engine.

    python -m turbocat scan FOLDER...      scan images, archives and Amiga folders
    python -m turbocat search TEXT         find files, disks, WHDLoad games, disk text
    python -m turbocat show NUMBER         full details of one catalogued item
    python -m turbocat dups                duplicate images and files
    python -m turbocat sets                multi-disk sets: missing or mixed-up disks
    python -m turbocat problems            damaged images and suspicious bootblocks
    python -m turbocat stats               catalogue totals
    python -m turbocat export csv FILE     export every file to a spreadsheet (CSV)
    python -m turbocat export disks FILE   export the disk list (Gotek / Amiberry friendly)
    python -m turbocat window              open the desktop window (needs PySide6)
"""

import argparse
import csv
import json
import os
import sys

from . import APP_NAME, VERSION
from . import sets
from .bootblock import best_title
from .catalogue import Catalogue
from .scanner import scan

STATUS_WORD = {"ok": "OK", "warning": "Warning", "error": "Problem"}
DEFAULT_DB = os.path.join(os.path.expanduser("~"), "turbocat.db")


def _j(s, default):
    try:
        return json.loads(s) if s else default
    except ValueError:
        return default


def _media_line(cat, m):
    num = cat.top_number(m)
    label = cat.label(m)
    name = os.path.basename(label.split(" > ", 1)[0])
    if m["parent_id"]:
        name += " > " + label.split(" > ", 1)[1]
    bits = [f"#{num:04d}", m["kind"].upper(), name]
    if m["volume"]:
        bits.append(f'volume "{m["volume"]}"')
    if m["whd_name"]:
        bits.append(f'WHDLoad: {m["whd_name"]}')
    return "  ".join(bits)


def cmd_scan(cat, a):
    print(f"{APP_NAME} {VERSION} - scanning...")
    s = scan(a.paths, cat, rescan=a.rescan, folders_as_volumes=a.folders)
    print(f"\nScanned {s['scanned']}, unchanged {s['skipped']}, "
          f"not Amiga files {s['ignored']}.")
    if s.get("missing"):
        print(f"{len(s['missing'])} folder(s) not found - check the spelling: "
              + ", ".join(s["missing"]))
    cmd_stats(cat, a)


def cmd_stats(cat, a):
    st = cat.stats()
    print(f"Catalogue: {st['items']} items ({st['containers']} including archives/images "
          f"inside them), {st['files']} files. Problems: {st['errors']}, "
          f"warnings: {st['warnings']}.")


def cmd_search(cat, a):
    media, files = cat.search(a.text, a.limit)
    if not media and not files:
        print(f'Nothing found for "{a.text}".')
        return
    if media:
        print(f"Disks / archives matching \"{a.text}\":")
        for m in media:
            line = _media_line(cat, m)
            hits = [t for t in _j(m["text"], []) if a.text.lower() in t.lower()]
            if hits:
                line += f'  (disk text: "{hits[0][:60]}")'
            print("  " + line)
    if files:
        print(f"\nFiles matching \"{a.text}\":")
        for f in files:
            m = cat.media_by_id(f["media_id"])
            size = "dir" if f["is_dir"] else f"{f['size']:,} bytes"
            print(f"  {f['path']}  ({size})")
            print(f"      on {_media_line(cat, m)}")


def cmd_show(cat, a):
    rows = [m for m in cat.all_media() if cat.top_number(m) == a.number]
    if not rows:
        print(f"No item #{a.number}.")
        return
    for m in rows:
        print("=" * 70)
        print(cat.label(m))
        print(f"  Type: {m['kind'].upper()}   Status: {STATUS_WORD.get(m['status'], m['status'])}   "
              f"Size: {m['size'] or 0:,} bytes   SHA1: {(m['sha1'] or '')[:16]}")
        if m["volume"]:
            print(f"  Volume: {m['volume']}   Filesystem: {m['fs'] or '-'}")
        if m["boot_kind"]:
            print(f"  Bootblock: {m['boot_kind']}")
        for k, v in _j(m["info"], {}).items():
            if not k.startswith("whd_") and k != "notes":
                print(f"  {k}: {v}")
        for n in _j(m["info"], {}).get("notes", []):
            print(f"  Note: {n}")
        if m["whd_name"]:
            print(f"  WHDLoad game: {m['whd_name']}  {m['whd_copy']}")
        for p in _j(m["problems"], []):
            print(f"  PROBLEM: {p}")
        for w in _j(m["warnings"], []):
            print(f"  Warning: {w}")
        text = _j(m["text"], [])
        if text:
            print("  Readable text on disk:")
            for t in text[:a.text_lines]:
                print(f"     {t[:76]}")
        files = cat.db.execute("SELECT * FROM files WHERE media_id=? ORDER BY path",
                               (m["id"],)).fetchall()
        if files:
            print(f"  Contents ({sum(1 for f in files if not f['is_dir'])} files):")
            for f in files[:a.max_files]:
                if f["is_dir"]:
                    print(f"     {f['path']}/")
                else:
                    print(f"     {f['path']:50} {f['size']:>9,}  {(f['date'] or '')[:10]}")
            if len(files) > a.max_files:
                print(f"     ... and {len(files) - a.max_files} more")


def cmd_dups(cat, a):
    di = cat.duplicate_images()
    print(f"Identical disk images / archives: {len(di)} set(s)")
    for d in di:
        print("  Same content:")
        for m in cat.media_with_sha1(d["sha1"]):
            print("     " + _media_line(cat, m))
    groups = cat.duplicate_files(a.min_size, limit=5000)
    shown, same_set, system = [], 0, []
    for d in groups:
        places = {}
        for f in cat.files_with_sha1(d["sha1"]):
            m = cat.media_by_id(f["media_id"])
            top = m
            while top["parent_id"]:
                top = cat.media_by_id(top["parent_id"])
            places[m["id"]] = (m, sets.set_key_for(top["source"]) or f"#{top['id']}", f["path"])
        keys = {k for _, k, _ in places.values()}
        if len(keys) == 1:
            same_set += 1          # a game repeating its own file across its own disks
            continue
        if all(sets.is_system_file(p) for _, _, p in places.values()):
            system.append((d, places))
            continue
        shown.append((d, places))
    print(f"\nFiles stored on unrelated disks (>= {a.min_size:,} bytes): {len(shown)}")
    for d, places in shown[:a.limit]:
        print(f"  {d['name']} ({d['size']:,} bytes) on {len(places)} disks:")
        for line in sorted(_media_line(cat, m) for m, _, _ in places.values()):
            print("     " + line)
    if len(shown) > a.limit:
        print(f"  ... and {len(shown) - a.limit} more (use --limit)")
    if system:
        def short(places):
            path = min((p for _, _, p in places.values()), key=len)
            return "/".join(path.split("/")[-2:]) if path.split("/")[-1][:1].isdigit() else path.split("/")[-1]
        names = sorted({short(pl) for _, pl in system})
        print(f"\nCommon system files found on several disks: {len(system)} "
              f"({', '.join(names[:8])}{' ...' if len(names) > 8 else ''})")
    if same_set:
        print(f"Not shown: {same_set} file(s) that games repeat across their own disks.")


def cmd_sets(cat, a):
    tops = cat.db.execute("SELECT number, source FROM media WHERE parent_id IS NULL").fetchall()
    reports = sets.analyse((r["number"], r["source"]) for r in tops)
    if not reports:
        print("No multi-disk sets recognised (names need '(Disk 1 of 3)' style numbering).")
        return
    bad = [r for r in reports if r["issues"]]
    print(f"Multi-disk sets: {len(reports)}, complete: {len(reports) - len(bad)}, "
          f"need attention: {len(bad)}")
    for r in reports:
        if not r["issues"] and not a.all:
            continue
        flag = "Check" if r["issues"] else "OK   "
        print(f"\n{flag}  {r['set']}  (have disk {', '.join(map(str, r['have']))} "
              f"of {r['expected']})")
        for i in r["issues"]:
            print(f"       - {i}")
        if a.all or r["issues"]:
            for n, total, number, name in r["disks"]:
                print(f"       #{number:04d}  disk {n} of {total}  {name}")
    if not a.all and len(reports) > len(bad):
        print(f"\n{len(reports) - len(bad)} complete set(s) not listed (use --all).")


def cmd_problems(cat, a):
    rows = cat.db.execute("SELECT * FROM media WHERE status!='ok' ORDER BY id").fetchall()
    if not rows:
        print("No problems found.")
        return
    for m in rows:
        print(("PROBLEM  " if m["status"] == "error" else "Warning  ") + _media_line(cat, m))
        for p in _j(m["problems"], [])[:5]:
            print(f"     - {p}")
        for w in _j(m["warnings"], [])[:5]:
            print(f"     - {w}")


def cmd_export(cat, a):
    with open(a.file, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if a.what == "csv":
            w.writerow(["Number", "Image or archive", "Volume", "Path", "Size", "Date",
                        "Comment", "SHA1"])
            for f in cat.db.execute("SELECT * FROM files WHERE is_dir=0 ORDER BY media_id, path"):
                m = cat.media_by_id(f["media_id"])
                w.writerow([cat.top_number(m), cat.label(m), m["volume"], f["path"], f["size"],
                            f["date"], f["comment"], f["sha1"]])
        else:
            w.writerow(["Number", "Image file", "Type", "Volume / title", "Status",
                        "Bootblock", "Files", "Folder"])
            for m in cat.db.execute("SELECT * FROM media WHERE parent_id IS NULL ORDER BY number"):
                title = m["whd_name"] or m["volume"] or best_title(_j(m["text"], []))[:60]
                if not title and m["kind"] in ("lha", "lzx"):
                    first = cat.db.execute("SELECT path FROM files WHERE media_id=? ORDER BY id "
                                           "LIMIT 1", (m["id"],)).fetchone()
                    title = first["path"].split("/")[0] if first else ""
                w.writerow([m["number"], os.path.basename(m["source"]), m["kind"].upper(), title,
                            m["status"], m["boot_kind"], m["file_count"],
                            os.path.dirname(m["source"])])
    print(f"Exported to {a.file}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="turbocat", description=f"{APP_NAME} {VERSION}")
    ap.add_argument("--db", default=DEFAULT_DB, help="catalogue file (default: %(default)s)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("scan"); p.add_argument("paths", nargs="+")
    p.add_argument("--rescan", action="store_true", help="rescan unchanged files too")
    p.add_argument("--folders", action="store_true", help="treat given folders as Amiga volumes")
    p = sub.add_parser("search"); p.add_argument("text"); p.add_argument("--limit", type=int, default=100)
    p = sub.add_parser("show"); p.add_argument("number", type=int)
    p.add_argument("--max-files", type=int, default=60); p.add_argument("--text-lines", type=int, default=12)
    p = sub.add_parser("dups"); p.add_argument("--min-size", type=int, default=1024)
    p.add_argument("--limit", type=int, default=30)
    sub.add_parser("problems")
    p = sub.add_parser("sets"); p.add_argument("--all", action="store_true", help="list complete sets too")
    sub.add_parser("stats")
    p = sub.add_parser("export"); p.add_argument("what", choices=["csv", "disks"]); p.add_argument("file")
    sub.add_parser("window", help="open the desktop window")
    a = ap.parse_args(argv)
    if a.cmd == "window":
        try:
            from .gui import run
        except ImportError as e:
            print(f"The window needs PySide6 ({e}). Install it with:\n"
                  "  ~/turbocat-env/bin/pip install PySide6-Essentials")
            return 1
        return run(a.db)
    cat = Catalogue(a.db)
    {"scan": cmd_scan, "search": cmd_search, "show": cmd_show, "dups": cmd_dups,
     "problems": cmd_problems, "stats": cmd_stats, "export": cmd_export,
     "sets": cmd_sets}[a.cmd](cat, a)


if __name__ == "__main__":
    sys.exit(main())
