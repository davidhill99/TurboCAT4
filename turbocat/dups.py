"""Duplicates: the same disk catalogued more than once.

Two items are duplicates when they hold exactly the same disk: the same bytes, or the same disk
inside different wrappers (an ADF, the same ADF in a ZIP, a DMS of it). TurboCAT never deletes
anything. For each set of copies it shows one, the copy it keeps, and hides the others as spares;
the files stay where they are. The user can choose which copy is kept, and the choice is
remembered by file path, so it survives rescans.

Items that merely share a file (two different PD disks with the same archive on them) are not
duplicates: both are kept, and the details panel just says what they share.
"""
import re

from .catalogue import BLANK_SHA1

STATUS_RANK = {"ok": 0, "warning": 1, "error": 2}
CHOICES = "dup_keep"           # meta: {content sha1: path of the copy the user chose to keep}


def _flags(path):
    """Collector flags in a name, e.g. [b], [o], [a2], [m bamcopy]: fewer means a cleaner copy."""
    return len(re.findall(r"\[[^\]]*\]", path.rsplit("/", 1)[-1]))


def keeper_order(item):
    """Best copy first: no problems, then the cleanest name, then the first catalogued."""
    return (STATUS_RANK.get(item.status, 1), _flags(item.path), item.number)


def choices(cat):
    return cat.get_meta(CHOICES, {}) or {}


def choose(cat, content_key, path):
    """Remember that this copy is the one to keep."""
    c = choices(cat)
    c[content_key] = path
    cat.set_meta(CHOICES, c)


def mark(items, cat):
    """Fill in each item's duplicate fields: copies, spare_of, spares.
    Items need .dup_key (the content fingerprint, or "" if it has none)."""
    groups = {}
    for it in items:
        if it.dup_key and it.dup_key not in BLANK_SHA1 and it.status != "empty":
            groups.setdefault(it.dup_key, []).append(it)
    chosen = choices(cat)
    for key, group in groups.items():
        if len(group) < 2:
            continue
        group.sort(key=keeper_order)
        want = chosen.get(key)
        keep = next((it for it in group if it.path == want), group[0])
        for it in group:
            it.copies = len(group)
            it.dup = True
            it.spare_of = 0 if it is keep else keep.id
            it.spares = tuple(o.id for o in group if o is not keep) if it is keep else ()
    return groups
