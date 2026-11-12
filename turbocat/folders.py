"""Which folders TurboCAT scans, as tick boxes on a folder tree (File > Scan folders…).

Stored as two lists: roots (folders scanned with everything inside them) and skips (folders
inside a root that are left out). A root may sit inside a skip: "leave out Temp, but do scan
Temp/Keep". Ticking or unticking a folder rewrites the two lists so that folder, and everything
inside it, ends up scanned or not, and the rest stays as it was.
"""
import os


def norm(p):
    return os.path.normpath(os.path.abspath(os.path.expanduser(p)))


def within(path, root):
    """True if path is root or inside it."""
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def inside(path, root):
    """True if path is inside root (not root itself)."""
    return path != root and within(path, root)


def tidy(roots, skips):
    """Drop roots already covered by another root (unless a skip between them leaves them out),
    and skips no root covers."""
    kept = []
    for p in sorted({norm(r) for r in roots}, key=len):
        if not any(within(p, r) and not any(within(p, s) and inside(s, r) for s in skips)
                   for r in kept):
            kept.append(p)
    skips = sorted({norm(s) for s in skips if any(inside(norm(s), r) for r in kept)})
    return sorted(kept), skips


class Selection:
    """The roots and skips, with what a tick box shows and does."""

    def __init__(self, roots=(), skips=()):
        self.roots, self.skips = tidy(roots, skips)

    def included(self, path):
        """Would a scan look at this file or folder?"""
        p = norm(path)
        return any(within(p, r) and not any(within(p, s) and inside(s, r) for s in self.skips)
                   for r in self.roots)

    def state(self, folder):
        """'on' (scanned, all of it), 'part' (some of it) or 'off'."""
        f = norm(folder)
        if self.included(f):
            return "part" if any(inside(s, f) for s in self.skips) else "on"
        return "part" if any(inside(r, f) and self.included(r) for r in self.roots) else "off"

    def tick(self, folder):
        """Scan this folder and everything in it."""
        f = norm(folder)
        roots = [r for r in self.roots if not inside(r, f)]
        skips = [s for s in self.skips if not within(s, f)]
        self.roots, self.skips = roots, skips
        if not self.included(f):
            roots.append(f)
        self.roots, self.skips = tidy(roots, skips)

    def untick(self, folder):
        """Leave this folder, and everything in it, out."""
        f = norm(folder)
        roots = [r for r in self.roots if not within(r, f)]
        skips = [s for s in self.skips if not inside(s, f)]
        self.roots, self.skips = roots, skips
        if self.included(f):
            skips.append(f)
        self.roots, self.skips = tidy(roots, skips)

    def gains(self, old):
        """True if this selection scans anything the old one didn't (so a Rescan is needed)."""
        return any(not old.included(r) for r in self.roots) or any(self.included(s) for s in old.skips)
