"""Lists of a collection's files, found beside the files themselves, used to check them.

Two kinds are read:
  * Internet Archive file lists ("<item>_files.xml", with "<item>_meta.xml" giving the title):
    every file of the download with its SHA-1. TurboCAT checks each archive against it.
  * TOSEC DAT files ("*.dat", XML): every disk image of a TOSEC set with its SHA-1. TurboCAT
    checks the disk images (also those inside ZIPs) against it.

A match means the file is exactly the one the collection lists: complete and undamaged.
A file the list names but with different contents is probably damaged or a different version.
"""
import glob
import os
import xml.etree.ElementTree as ET

_cache = {}        # path -> (mtime, CollectionList or None)


class CollectionList:
    def __init__(self, title, path, kind):
        self.title, self.path, self.kind = title, path, kind
        self.by_sha1 = {}          # sha1 -> name in the list
        self.by_name = {}          # file name -> sha1

    @property
    def applications(self):
        """True for a list of applications / utilities rather than games or demos."""
        t = self.title.lower()
        return any(w in t for w in ("application", "utilit", "tools")) and "game" not in t


def _ia_title(files_xml):
    meta = files_xml[:-len("_files.xml")] + "_meta.xml"
    try:
        root = ET.parse(meta).getroot()
        return (root.findtext("title") or root.findtext("identifier") or "").strip()
    except (OSError, ET.ParseError):
        return os.path.basename(files_xml)[:-len("_files.xml")]


def _read(path):
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return None
    if root.tag == "files":                                 # Internet Archive
        lst = CollectionList(_ia_title(path) + " (Internet Archive)", path, "ia")
        for f in root.findall("file"):
            name, sha = f.get("name", ""), (f.findtext("sha1") or "").lower()
            if sha and f.get("source") == "original" and not name.endswith(("_files.xml", "_meta.xml",
                                                                               "_meta.sqlite", ".torrent")):
                lst.by_sha1[sha] = name
                lst.by_name[name] = sha
        return lst
    if root.tag == "datafile":                              # TOSEC (and other Logiqx) DAT
        title = (root.findtext("header/name") or os.path.basename(path)).strip()
        lst = CollectionList(title + " (TOSEC)", path, "dat")
        for game in root.findall("game") + root.findall("machine"):
            for rom in game.findall("rom"):
                sha = (rom.get("sha1") or "").lower()
                if sha:
                    lst.by_sha1[sha] = rom.get("name", game.get("name", ""))
                    lst.by_name[rom.get("name", "")] = sha
        return lst
    return None


_folders = {}       # folder -> (its modification time, the list files in it)


def lists_in(folders):
    """Every collection list found in these folders (not their subfolders)."""
    out = []
    for folder in sorted(set(folders)):
        try:
            stamp = os.stat(folder).st_mtime          # changes when a file is added or removed
        except OSError:
            continue
        seen = _folders.get(folder)
        if seen is None or seen[0] != stamp:
            seen = (stamp, glob.glob(os.path.join(glob.escape(folder), "*_files.xml")) +
                    glob.glob(os.path.join(glob.escape(folder), "*.dat")))
            _folders[folder] = seen
        for path in seen[1]:
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            hit = _cache.get(path)
            if hit is None or hit[0] != mtime:
                hit = (mtime, _read(path))
                _cache[path] = hit
            if hit[1] is not None and hit[1].by_sha1:
                out.append(hit[1])
    return out


def check(item_name, folder, shas, lists):
    """(verdict, list) for one item: "match" if any of its fingerprints is in a list from its
    own folder (or any list, for a TOSEC DAT); "differs" if its own folder's list names the file
    but with other contents; None if no list knows it."""
    differs = None
    for lst in lists:
        here = os.path.dirname(lst.path) == folder
        if (here or lst.kind == "dat") and any(s in lst.by_sha1 for s in shas):
            return "match", lst
        if here and item_name in lst.by_name and lst.by_name[item_name] not in shas:
            differs = lst
    return ("differs", differs) if differs else (None, None)
