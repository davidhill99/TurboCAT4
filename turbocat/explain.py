"""Problems in plain English: what is wrong with a disk, how much of it is affected, and whether
anything in the collection can fix it. The scanner's own messages stay as the technical detail
(shown on hover)."""
import os

from . import versions as vers

UNREADABLE = "file unreadable: "

# The start of a technical message, and what it means
PLAIN = [
    ("truncated image", "The disk image is cut short: part of the disk is missing"),
    ("not a usable ADF", "Not a usable disk image"),
    ("unexpected ADF size", "The disk image is the wrong size"),
    ("filesystem unreadable", "The disk's directory is damaged, so its files can't be listed"),
    ("filesystem:", "Part of the disk's directory is damaged"),
    ("LHA archive unreadable", "An LHA archive on it can't be opened"),
    ("ZIP archive unreadable", "The ZIP archive can't be opened"),
    ("LZX archive unreadable", "An LZX archive on it can't be opened"),
    ("DMS", "The DMS image can't be unpacked properly"),
    ("ADZ", "The ADZ image can't be unpacked"),
    ("RDB", "The hard disk's partition table can't be read"),
    ("partition", "A hard disk partition can't be read"),
    ("could not read", "The file can't be read"),
]


def damaged_paths(messages):
    """The files named in 'file unreadable' messages, in order, once each. The path ends where
    the reason in brackets starts, so look for the last ' (' that opens a bracket closed at the end."""
    out = []
    for msg in messages:
        if UNREADABLE not in msg:
            continue
        text = msg[msg.index(UNREADABLE):]          # after "inner.adf: " when inside an archive
        rest = text[len(UNREADABLE):]
        depth, cut = 0, len(rest)
        for i in range(len(rest) - 1, -1, -1):       # walk back to the bracket matching the last ')'
            if rest[i] == ")":
                depth += 1
            elif rest[i] == "(":
                depth -= 1
                if depth == 0:
                    cut = i
                    break
        path = rest[:cut].rstrip()
        if path and path not in out:
            out.append(path)
    return out


def summary(messages, total_files):
    """One plain sentence for the heading: '1 of 220 files damaged — the other 219 read fine'."""
    bad = len(damaged_paths(messages))
    if bad and total_files:
        good = max(total_files - bad, 0)
        head = f"{bad:,} of {total_files:,} file{'s' if total_files != 1 else ''} damaged"
        return head + (f" — the other {good:,} read fine" if good > 1 else
                       " — the other one reads fine" if good == 1 else "")
    if bad:
        return f"{bad:,} file{'s' if bad != 1 else ''} damaged"
    for start, plain in PLAIN:
        if any(msg.startswith(start) or f": {start}" in msg for msg in messages):
            return plain
    return "Something on this disk can't be read"


def why_not_fixable(item, all_items):
    """Why the collection holds no good copy: one short line per other version."""
    out = []
    for o in all_items:
        if o is item or not item.version_key or o.version_key != item.version_key or o.spare_of:
            continue
        t = vers.tags(vers.name_of(o))
        if o.status == "empty":
            why = "it is an empty file"
        elif any(x.startswith("b") for x in t):
            why = "TOSEC marks it as a bad dump [b]" + (", and TurboCAT can't read its files either"
                                                        if o.files in ("—", "0") else "")
        elif o.status == "error":
            why = "it is damaged too"
        else:
            continue
        out.append(f"#{o.number:04d} is another version of this disk, but {why}.")
    return out


def found_elsewhere(cat, paths, own_ids):
    """Damaged files found intact (same name and size, read without error) on other disks:
    {path: [disk numbers]}."""
    found = {}
    if not paths or not own_ids:
        return found
    marks = ",".join("?" * len(own_ids))
    for p in paths:
        row = cat.db.execute(
            f"SELECT size FROM files WHERE media_id IN ({marks}) AND path=? LIMIT 1",
            (*own_ids, p)).fetchone()
        if row is None or not row["size"]:
            continue
        name = os.path.basename(p)
        nums = set()
        for r in cat.db.execute(
                f"SELECT m.id FROM files f JOIN media m ON m.id=f.media_id "
                f"WHERE f.name=? COLLATE NOCASE AND f.size=? AND f.sha1 IS NOT NULL AND NOT f.is_dir "
                f"AND m.id NOT IN ({marks})", (name, row["size"], *own_ids)):
            top = r["id"]
            while True:
                up = cat.db.execute("SELECT parent_id, number FROM media WHERE id=?", (top,)).fetchone()
                if up is None or not up["parent_id"]:
                    break
                top = up["parent_id"]
            if up is not None and up["number"]:
                nums.add(up["number"])
        if nums:
            found[p] = sorted(nums)
    return found
