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
# Standard AmigaDOS / Workbench commands (C: on Workbench 1.3-3.x). Games and demos often copy
# these into their own root or a drawer rather than C/, so they are matched by name anywhere.
_SYSTEM_COMMANDS = frozenset(n.lower() for n in """
    AddBuffers AddDataTypes Alias Ask Assign Avail BindDrivers Break CD ChangeTaskPri ConClip
    Copy CPU Date Delete Dir DiskChange DiskDoctor Echo Ed Edit Else EndCLI EndIf EndShell EndSkip
    Eval Execute FailAt Fault FF FileNote Format Get GetEnv IconX If Info Install Join Lab List
    LoadResource LoadWB Lock MakeDir MakeLink More Mount NewCLI NewShell Path Prompt Protect Quit
    Relabel RemRAD Rename RequestChoice RequestFile Resident Run Search Set SetClock SetDate
    SetEnv SetFont SetKeyboard SetPatch Skip Sort Stack Status Type UnAlias UnSet UnSetEnv
    Version Wait Which Why
""".split())


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
    return (p.endswith(_SYSTEM_EXT) or p.rsplit("/", 1)[-1] in _SYSTEM_COMMANDS
            or any(p.startswith(d) or f"/{d}" in p for d in _SYSTEM_DIRS))


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


# ---------------------------------------------------------------- sets for the window

_CRACK = re.compile(r"\[(cr|t|f|h)\s[^\]]*\]", re.I)     # cracker / trainer / fix / hack tags


class DiskSet:
    """One multi-disk set as the window shows it.

    disks: [(disk number, the copy used, [other versions of that disk])], in disk order;
    missing: disk numbers not found; flags: short descriptions of anything odd."""

    def __init__(self, key, expected, disks, missing, flags, problem_disks):
        self.key, self.expected, self.disks = key, expected, disks
        self.missing, self.flags, self.problem_disks = missing, flags, problem_disks

    @property
    def complete(self):
        return not self.missing and not self.problem_disks

    def badge(self):
        """(text, tone) for the list: tone is ok, warn or problem."""
        if self.missing:
            if len(self.missing) == 1:
                return f"Disk {self.missing[0]} missing", "problem"
            return f"{len(self.missing)} disks missing", "problem"
        if self.problem_disks:
            n = self.problem_disks
            return (f"Disk {n[0]} has problems" if len(n) == 1 else
                    f"{len(n)} disks have problems"), "problem"
        if self.flags:
            return f"Complete · {self.flags[0].split(':')[0]}", "warn"
        return f"Complete · {self.expected} of {self.expected}", "ok"


def group(items, order):
    """Gather items named "(Disk N of M)" into sets.

    items: things with .file, .path and .status (spare copies already left out);
    order: sort key putting the best copy first (used when a disk is there more than once).
    Returns [DiskSet], and only sets of two or more disks."""
    found = defaultdict(list)
    for it in items:
        info = parse(getattr(it, "tosec_name", "") or it.file)
        if info and info[2] >= 2:
            key, n, total = info
            found[key].append((n, total, it))
    out = []
    for key, entries in found.items():
        totals = sorted({t for _, t, _ in entries})
        expected = max(totals)
        by_no = defaultdict(list)
        for n, _, it in entries:
            by_no[n].append(it)
        disks = []
        for n in sorted(by_no):
            copies = sorted(by_no[n], key=order)
            disks.append((n, copies[0], copies[1:]))
        missing = [n for n in range(1, expected + 1) if n not in by_no]
        flags = []
        if len(totals) > 1:
            flags.append("mixed releases: disk counts disagree (" +
                         " / ".join(f"of {t}" for t in totals) + ")")
        cracks = sorted({m.group(0) for _, it, _ in disks
                         for m in _CRACK.finditer(getattr(it, "tosec_name", "") or it.file)})
        if len(cracks) > 1:
            flags.append("mixed releases: " + ", ".join(cracks) +
                         " (disks from different releases don't always work together)")
        problems = [n for n, it, _ in disks if it.status == "error"]
        out.append(DiskSet(key, expected, disks, missing, flags, problems))
    out.sort(key=lambda s: s.key.lower())
    return out
