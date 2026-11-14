"""Collection stats: who cracked, trained, fixed and hacked your disks, who published them, and
when. Read from the disks' TOSEC names ("Lemmings (1991)(Psygnosis)[cr Skid Row][t +2 Fairlight]")
or, for disks not identified, their file names.
"""
import re
from collections import Counter, defaultdict

ROLES = {"cr": "cracked", "t": "trained", "f": "fixed", "h": "hacked", "tr": "translated"}
_TAG = re.compile(r"\[(cr|tr|t|f|h)\s+([^\]]+)\]", re.I)
_FIELDS = re.compile(r"\(([^()]*)\)")
_YEAR = re.compile(r"^(19[789]\d|20[0-4]\d)")
NOT_GROUPS = {"turbocat"}                 # TurboCAT's own repairs ([f TurboCAT])
# The short names TOSEC uses for the best-known groups
KNOWN = {"FLT": "Fairlight", "SR": "Skid Row", "QTX": "Quartex", "CSL": "Crystal", "RZR": "Razor 1911",
         "PDX": "Paradox", "ACU": "Australian Crackers United", "TRSI": "Tristar & Red Sector Inc.",
         "HLM": "Hoodlum"}


def full_name(group):
    """'SR' -> 'SR (Skid Row)'; anything else as it is."""
    return f"{group} ({KNOWN[group]})" if group in KNOWN else group


NOT_PUBLISHERS = {"-", "", "pd"}


def groups_in(name):
    """[(group, role)] from one name's tags: '[cr PDX - TRSI][t +2 Fairlight]' ->
    [('PDX', 'cracked'), ('TRSI', 'cracked'), ('Fairlight', 'trained')]."""
    out = []
    for code, who in _TAG.findall(name):
        who = re.sub(r"^\+\s*\d+\s*", "", who.strip())        # trainers: "+2 Fairlight"
        for g in re.split(r"\s+-\s+|\s*&\s*|,\s*", who):
            g = g.strip(" .")
            # all lower case ("startup-sequence") is what was changed, not who changed it
            if g and g.lower() not in NOT_GROUPS and not g.isdigit() and g != g.lower():
                out.append((g, ROLES[code.lower()]))
    return out


def fields(name):
    """(year, publisher) from a TOSEC name, '' where it doesn't say."""
    f = [x.strip() for x in _FIELDS.findall(name)]
    year = next((x[:4] for x in f[:1] if _YEAR.match(x)), "")
    pub = f[1] if len(f) > 1 and year else ""
    if pub.lower() in NOT_PUBLISHERS or _YEAR.match(pub):
        pub = ""
    return year, pub


def collect(names):
    """Stats over a collection's disk names (one per disk).
    Returns dict(groups={group: Counter(role -> disks)}, publishers=Counter, years=Counter, disks=n)."""
    groups = defaultdict(Counter)
    publishers, years = Counter(), Counter()
    seen = set()
    for name in names:
        if not name or name in seen:
            continue
        seen.add(name)
        for g, role in set(groups_in(name)):
            groups[_canon(groups, g)][role] += 1
        year, pub = fields(name)
        if year:
            years[year] += 1
        if pub:
            for p in re.split(r"\s+-\s+", pub):
                publishers[p.strip()] += 1
    return {"groups": dict(groups), "publishers": publishers, "years": years, "disks": len(seen)}


def _canon(groups, g):
    """The same group written differently ('Skid Row', 'SKID ROW') counts once, under the first
    spelling seen."""
    low = g.lower()
    for k in groups:
        if k.lower() == low:
            return k
    return g


def league(groups):
    """Groups ranked by disks, most first: [(group, total, Counter(role -> disks))]."""
    rows = [(g, sum(c.values()), c) for g, c in groups.items()]
    return sorted(rows, key=lambda r: (-r[1], r[0].lower()))
