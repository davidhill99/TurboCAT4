"""Recognise multi-disk sets from collector (TOSEC-style) file names.

    "Syndicate (1993)(Electronic Arts)(M3)(Disk 2 of 4).adf"
        -> set "Syndicate (1993)(Electronic Arts)(M3)", disk 2 of 4
"""

import os
import re
from collections import defaultdict

_DISK = re.compile(r"\(\s*Dis[ck]\s*(\d+)\s*of\s*(\d+)\s*\)", re.I)
_TAGS = re.compile(r"\[[^\]]*\]")
_SYSTEM_DIRS = ("libs/", "devs/", "fonts/", "l/", "c/", "s/")
_SYSTEM_EXT = (".library", ".device", ".font", ".datatype", ".resource")


def parse(name: str):
    """Return (set_key, disk_no, disk_total) or None for names without "(Disk n of m)"."""
    base = os.path.basename(name)
    m = _DISK.search(base)
    if not m:
        return None
    key = base[:m.start()]
    key = _TAGS.sub("", key).strip()
    return key, int(m.group(1)), int(m.group(2))


def is_system_file(path: str) -> bool:
    p = path.lower()
    return p.endswith(_SYSTEM_EXT) or any(p.startswith(d) or f"/{d}" in p for d in _SYSTEM_DIRS)


def analyse(sources):
    """sources: iterable of (number, path). Returns a list of set reports, worst first."""
    groups = defaultdict(list)
    for number, path in sources:
        info = parse(path)
        if info:
            key, n, total = info
            groups[key].append((n, total, number, os.path.basename(path)))
    reports = []
    for key, disks in groups.items():
        totals = sorted({t for _, t, _, _ in disks})
        expected = max(totals)
        have = sorted({n for n, _, _, _ in disks})
        missing = [n for n in range(1, expected + 1) if n not in have]
        extra = sorted({n for n, _, _, _ in disks if [x for x in disks if x[0] == n].__len__() > 1})
        issues = []
        if missing:
            issues.append("missing disk " + ", ".join(map(str, missing)) + f" of {expected}")
        if len(totals) > 1:
            issues.append("disk counts disagree (" + " / ".join(f"of {t}" for t in totals)
                          + "): may be two different releases mixed together")
        if extra:
            issues.append("more than one copy of disk " + ", ".join(map(str, extra)))
        reports.append({"set": key, "expected": expected, "have": have, "issues": issues,
                        "disks": sorted(disks)})
    reports.sort(key=lambda r: (not r["issues"], r["set"].lower()))
    return reports


def set_key_for(path: str):
    info = parse(path)
    return info[0] if info else None
