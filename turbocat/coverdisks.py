"""Coverdisks: the disks given away with Amiga magazines.

TOSEC lists about 2,900 of them, from 80 magazines (Amiga Format, CU Amiga, Amiga Power, The One,
Amiga Shopper...), named like
    "Amiga Shopper #47 (1995)(Future Publishing)(GB)(Disk 2 of 3)[Mar 1995].adf"
    "Amiga Shopper #47 (1995)(Future Publishing)(GB)(Disk 3 of 3)[Mar 1995][Subscriber Disk].adf"
A disk whose checksum is in that list is a coverdisk for certain. One whose checksum isn't (a
different dump, a disk changed by use, or an empty file) can still be recognised by its file and
folder names: the magazine's name, the issue number and the disk number or label, e.g.
    ".../Amiga Shopper Coverdisks/Issue 47 March 1995/Amiga Shopper Issue 47 Disk 2.adf"
Files are never renamed here.
"""
import functools
import os
import re
from dataclasses import dataclass

from . import identify

LIST = "Coverdisks"
MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
_SEASON = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|christmas|xmas|spring|summer|autumn|winter)"
_DATE_TAG = re.compile(_SEASON + r"[a-z]*[ -]+(?:\d{1,2}[ -]+)?(?:19|20)\d\d$", re.I)
_DUMP_TAG = re.compile(r"^(!|a\d*|b\d*|f\d*|h\d*|m\d*|o\d*|p\d*|t\d*|u\d*|v\d*|cr\b.*|tr\b.*|[abfhmoptu] .*)$", re.I)
_NAME = re.compile(r"^(?P<mag>.+?)(?: #(?P<issue>[^ (]+))?(?: - (?P<sub>[^(]+?))? \((?P<year>[^)]*)\)"
                   r"\((?P<pub>[^)]*)\)(?P<rest>.*)$")


@dataclass
class Coverdisk:
    magazine: str
    issue: str = ""          # as TOSEC writes it: "47", "077", "87-04&05"
    date: str = ""           # "Mar 1995", "Christmas 1995"
    year: str = ""
    disk: str = ""           # "2"
    of: str = ""             # "3"
    label: str = ""          # "Subscriber Disk", "Shareware Collection Volume 01"
    tosec_name: str = ""     # the name in TOSEC's list ("" if only the magazine is known)
    how: str = ""            # "checksum", "name" (TOSEC knows the disk; this copy differs), "folder"
                             # (a coverdisk TOSEC doesn't list) or "made" (a disk made from one, e.g.
                             # by its installer, kept in a folder beside it)

    def title(self):
        """'Amiga Shopper #47 · Mar 1995 · Disk 2 of 3'."""
        bits = [self.magazine + (f" #{self.issue}" if self.issue else "")]
        if self.date:
            bits.append(self.date)
        if self.label:
            bits.append(self.label)
        if self.disk and self.of and self.of != "1":
            bits.append(f"Disk {self.disk} of {self.of}")
        return " · ".join(bits)

    def sort_key(self):
        n = re.match(r"\d+", self.issue or "")
        return (self.magazine.lower(), int(n.group()) if n else 0, self.issue, _num(self.disk))


def _num(text):
    m = re.match(r"\d+", text or "")
    return int(m.group()) if m else 0


def _display_magazine(mag):
    """TOSEC writes 'One, The': show 'The One'."""
    m = re.match(r"^(.*), (The|A|Der|Die|Das|Le|La)$", mag)
    return f"{m.group(2)} {m.group(1)}" if m else mag


def parse(name):
    """A TOSEC coverdisk name -> Coverdisk (how and tosec_name not set), or None."""
    stem = identify.stem(os.path.basename(name))
    m = _NAME.match(stem)
    if not m:
        return None
    rest = m.group("rest")
    cd = Coverdisk(magazine=_display_magazine(m.group("mag").strip()), issue=m.group("issue") or "",
                   year=m.group("year"))
    d = re.search(r"\(Disk (\w+) of (\w+)\)", rest)
    if d:
        cd.disk, cd.of = d.group(1), d.group(2)
    labels = []
    for tag in re.findall(r"\[([^\]]*)\]", rest):
        if _DATE_TAG.search(tag) and not cd.date:
            cd.date = tag
        elif not _DUMP_TAG.match(tag.strip()):
            labels.append(tag)
    sub = (m.group("sub") or "").strip()
    if sub and sub.lower() != "amiga":
        labels.insert(0, sub)
    cd.label = " · ".join(labels)
    return cd


def _words(text):
    """Lower-case words with numbers' leading zeros dropped and plurals made singular:
    'Subscribers Volume 01' -> ['subscriber', 'volume', '1']."""
    text = re.sub(r"([a-z])(\d)", r"\1 \2", text.lower())
    out = []
    for w in re.findall(r"[a-z]+|\d+", text):
        if w.isdigit():
            w = w.lstrip("0") or "0"
        elif len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.append(w)
    return out


GENERIC = {"disk", "disc", "dsk", "the", "of", "and", "amiga", "issue", "volume", "vol", "cover",
           "coverdisk", "magazine"}


@functools.lru_cache(maxsize=None)
def _key(text):
    return " ".join(_words(text))


class Catalogue:
    """TOSEC's coverdisks, looked up by magazine and issue."""

    def __init__(self, names):
        self.by_issue = {}       # (magazine key, issue) -> [Coverdisk]
        self.magazines = {}      # magazine key -> display name
        for name in names:
            cd = parse(name)
            if cd is None:
                continue
            cd.tosec_name = identify.stem(name)
            key = _key(cd.magazine)
            self.magazines.setdefault(key, cd.magazine)
            self.by_issue.setdefault((key, (cd.issue or "").lstrip("0") or "0"), []).append(cd)
        # longest first, so "CU Amiga Magazine" wins over "CU Amiga", "Amiga Format" over "Amiga"
        self._mags = sorted(self.magazines, key=len, reverse=True)

    def magazine_in(self, text):
        memo = self.__dict__.setdefault("_memo", {})        # the same names come up every reload
        if text in memo:
            return memo[text]
        memo[text] = found = self._magazine_in(text)
        return found

    def _magazine_in(self, text):
        k = " " + _key(text) + " "
        for mag in self._mags:
            if f" {mag} " in k:
                return mag
        return ""

    def guess(self, path):
        """Recognise a coverdisk by its file and folder names: a Coverdisk with how='name' (TOSEC
        knows the disk), how='folder' (a coverdisk, not in TOSEC's list) or None."""
        # "/" or "\\": a path inside a ZIP uses "/" even on Windows
        parts = [p for p in re.split(r"[\\/]", path)[-4:] if p]
        text = " ".join(parts)
        mag = self.magazine_in(text)
        # A file whose own name says nothing of the magazine or issue, in a folder inside the
        # issue's folder ("Issue 60/Created Disks/Created Disk 1.adf"), was made from the coverdisk.
        own = os.path.splitext(parts[-1])[0]
        near = " ".join(parts[-2:])
        made = bool(mag) and not self.magazine_in(near) and not re.search(r"(?:issue|#)\s*\d+", near, re.I)
        in_cover_folder = bool(re.search(r"cover\s*-?\s*dis[ck]", text, re.I))
        if not mag:
            if in_cover_folder:
                return Coverdisk(magazine="", how="folder", label=os.path.splitext(parts[-1])[0])
            return None
        issue = re.search(r"(?:issue|#|\bno\.?|\bnr\.?)\s*0*(\d+)", text, re.I)
        if not issue:
            return Coverdisk(magazine=self.magazines[mag], how="folder") if in_cover_folder else None
        found = self.by_issue.get((mag, issue.group(1)), [])
        if made:
            date = next((cd.date for cd in found if cd.date), "")
            return Coverdisk(magazine=self.magazines[mag], issue=issue.group(1), date=date, label=own,
                             how="made")
        if not found:
            return Coverdisk(magazine=self.magazines[mag], issue=issue.group(1), how="folder")
        scores = [self._score(cd, parts[-1]) for cd in found]
        top = [cd for cd, sc in zip(found, scores) if sc == max(scores)]
        # several dumps of one disk ([o], [m]...) are the same disk: name the plainest
        best = min(top, key=lambda cd: (len(cd.tosec_name), cd.tosec_name))
        out = Coverdisk(**{**best.__dict__, "how": "name"})
        if len({(cd.disk, cd.label) for cd in top}) > 1:
            out.disk, out.of, out.label, out.tosec_name = "", "", "", ""   # which disk is unclear
        return out

    @staticmethod
    def _score(cd, file_name):
        """How well a file name fits one of an issue's disks."""
        words = _words(os.path.splitext(file_name)[0])
        score = 0
        disk = re.search(r"(?:disk|disc|dsk)\s*0*(\d+)", file_name, re.I)
        if disk and cd.disk:
            score += 3 if disk.group(1) == cd.disk.lstrip("0") else -3
        label = _words(cd.label)
        score += sum(1 for w in label if w in words and not w.isdigit() and w not in GENERIC)
        nums = [w for w in label if w.isdigit()]
        if nums and all(n in words for n in nums):
            score += 2
        if ("subscriber" in words) != ("subscriber" in label):
            score -= 2
        return score


_catalogue = None


def catalogue():
    """The coverdisk catalogue from TOSEC's lists (empty until they're downloaded)."""
    global _catalogue
    if _catalogue is None or getattr(_catalogue, "_source", None) is not identify.tosec_index():
        _catalogue = Catalogue(identify.names_in(LIST))
        _catalogue._source = identify.tosec_index()
    return _catalogue


def recognise(path, known=None):
    """A Coverdisk for an item, or None. known: (TOSEC name, source, list) if its checksum matched."""
    if known and len(known) > 2 and str(known[2]).startswith(LIST):
        cd = parse(known[0])
        if cd:
            cd.tosec_name, cd.how = identify.stem(known[0]), "checksum"
            return cd
    if known:
        return None                   # identified as something else (a game, a demo...)
    return catalogue().guess(path)
