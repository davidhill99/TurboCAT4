"""Bootblock analysis for Amiga floppy images.

Classifies the first 1024 bytes of a disk and applies simple heuristics that
flag code which installs itself in memory - the behaviour of classic bootblock
viruses (and, to be fair, of some virus killers and copy protections).
"""

import re
import struct

DOS_TYPES = {
    0: "OFS", 1: "FFS", 2: "OFS-INTL", 3: "FFS-INTL",
    4: "OFS-DC", 5: "FFS-DC", 6: "OFS-LNFS", 7: "FFS-LNFS",
}

# (pattern, description) - byte patterns for 68k instructions touching
# exec's capture vectors / KickTag list, or calling SetFunction.
def _move_l_to(disp: bytes):
    """68k MOVE.L <register | #immediate | d16(PC)>, d16(An) with the given displacement."""
    return re.compile(rb"[\x21-\x2f](?:[\x40-\x4f]|\x7c.{4}|\x7a..)" + re.escape(disp), re.S)


_HOOK_PATTERNS = [
    (_move_l_to(b"\x00\x2e"), "writes ExecBase->CoolCapture (survives reset)"),
    (_move_l_to(b"\x00\x2a"), "writes ExecBase->ColdCapture (survives reset)"),
    (_move_l_to(b"\x00\x32"), "writes ExecBase->WarmCapture (survives reset)"),
    (_move_l_to(b"\x02\x26"), "writes ExecBase->KickTagPtr (survives reset)"),
    (_move_l_to(b"\x02\x22"), "writes ExecBase->KickMemPtr (survives reset)"),
    (re.compile(rb"\x4e\xae\xfe\x5c"), "calls SetFunction (patches system routines)"),
    (re.compile(rb"\x4e\xae\xfd\x9c"), "calls SumKickData (survives reset)"),
]

# Readable names that appear inside well-known bootblock viruses.
_VIRUS_TEXT = [
    "byte bandit", "sca!", "lamer exterminator", "saddam", "northstar",
    "byte warrior", "obelisk", "pentagon", "gadaffi", "revenge", "termigator",
    "joshua", "virus",
]


def checksum(bb: bytes) -> int:
    s = 0
    for i in range(0, 1024, 4):
        if i == 4:
            continue
        s += struct.unpack(">I", bb[i:i + 4])[0]
        if s > 0xFFFFFFFF:
            s = (s & 0xFFFFFFFF) + 1
    return (~s) & 0xFFFFFFFF


_WORD = re.compile(r"[A-Za-z]+")

# Most common letter pairs in English (covers ~97% of pairs in real text).
_BIGRAMS = set("""
ab ac ad ag ai ak al am an ap ar as at au av ay ba be bi bl bo br bs bu by ca cc
ce ch ci ck cl co cr ct cu da de di do dr du ea eb ec ed ee ef eg ei el em en eo
ep eq er es et ev ew ex fa fe ff fi fo fr ft fu fy ga ge gh gi gl gn go gr gs gu
ha he hi ho hr ht ia ib ic id ie if ig il im in io ip ir is it iv ix iz ja je ka
ke ki la ld le lg li ll lo ls lt lu ly ma mb me mi mm mo mp ms mu na nc nd ne nf
ng ni nn no ns nt nu ny ob oc od oe of og ol om on oo op or os ot ou ov ow pa pe
ph pi pl po pp pr ps pt pu py qu ra rc rd re rf rg ri rk rm rn ro rp rr rs rt ru
rv ry sa sc se sh si sl sm so sp ss st su sy ta te th ti to tr ts tt tu tw ty ua
ub uc ud ue ui ul um un up ur us ut va ve vi wa we wh wi wo wr yo yp yr ys yt
""".split())


def _english_score(words) -> float:
    pairs = [w[i:i + 2].lower() for w in words for i in range(len(w) - 1)]
    if not pairs:
        return 0.0
    return sum(p in _BIGRAMS for p in pairs) / len(pairs)
_VOWELS = set("aeiouyAEIOUY")


def _good_word(w: str) -> bool:
    if len(w) < 2 or not (set(w) & _VOWELS):
        return False
    # real words are lower case, UPPER CASE or Capitalised - not rAnDoM
    if not (w.islower() or w.isupper() or (w[0].isupper() and w[1:].islower())):
        return False
    # random data tends to produce long runs of consonants
    return not re.search(r"[^aeiouyAEIOUY]{5,}", w)


_GLUED = re.compile(r"[A-Za-z][`~|^\\{}\[\]<>@=][A-Za-z]")
_GLUED_DIGIT = re.compile(r"[A-Za-z]\d[A-Za-z]")


def looks_like_text(s: str) -> bool:
    if _GLUED.search(s):          # odd symbols inside "words": random data
        return False
    if " " not in s and _GLUED_DIGIT.search(s):
        return False
    words = [w for w in _WORD.findall(s) if len(w) > 1 or w in "aAI"]
    letters = sum(len(w) for w in words)
    if letters < 4:
        return False
    good = [w for w in words if _good_word(w)]
    good_letters = sum(len(w) for w in good)
    if good_letters / letters < 0.7 or not any(len(w) >= 4 for w in good):
        return False
    if letters / len(s) < 0.5 or _english_score(good) < 0.8:
        return False
    if len(words) == 1 and (len(words[0]) < 6 or _english_score(good) < 0.95):
        return False    # lone "words" are usually random data
    # mostly letters, spaces and ordinary punctuation
    plain = sum(c.isalnum() or c in " .,:;!?'-/()&*" for c in s)
    return plain / len(s) >= 0.8


def readable_strings(data: bytes, min_len: int = 6, limit: int = 40):
    """Return distinct human-readable strings (titles, credits, messages)."""
    out, seen = [], set()
    for m in re.finditer(rb"[\x20-\x7e]{%d,}" % min_len, data):
        s = m.group().decode("latin-1").strip()
        if len(s) < min_len or not looks_like_text(s):
            continue
        s = re.sub(r"\s{2,}", " ", s)
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    # keep the most text-like strings (phrases first), in disk order
    ranked = sorted(range(len(out)), key=lambda i: -_quality(out[i]))[:limit]
    return [out[i] for i in sorted(ranked)]


_best = {}


def best_title(strings):
    """Pick the string most likely to be a title or credit (for non-DOS disks). Remembered: the
    same disks' texts come up on every reload."""
    key = tuple(strings)
    if key not in _best:
        _best[key] = _best_title(key)
    return _best[key]


def _best_title(strings):
    best, score = "", 0.0
    for s in strings:
        if s.lower().endswith((".library", ".device")) or s.lstrip().startswith(";") \
                or "(a" in s.lower() or (("," in s or "_" in s) and " " not in s):
            continue
        words = [w for w in _WORD.findall(s) if _good_word(w) and len(w) >= 3]
        if len(words) < 2:
            continue
        q = min(_quality(s), 25)      # long messages shouldn't beat short titles
        if q > score:
            best, score = s, q
    return best.strip(" -:()*")


def _quality(s: str) -> float:
    words = [w for w in _WORD.findall(s) if _good_word(w)]
    return sum(len(w) for w in words) * (1.5 if len(words) > 1 else 1.0)


def analyse(bb: bytes) -> dict:
    """Analyse a 1024-byte bootblock."""
    r = {"dos": False, "fs": None, "bootable": False, "kind": "", "flags": [],
         "notes": [], "text": []}
    if len(bb) < 1024:
        r["kind"] = "too short"
        return r
    if bb.count(0) == 1024:
        r["kind"] = "empty bootblock"
        return r
    if bb[:3] == b"DOS" and bb[3] <= 7:
        r["dos"] = True
        r["fs"] = DOS_TYPES.get(bb[3])
    elif bb[:3] in (b"PFS", b"SFS"):
        r["fs"] = bb[:3].decode()
    code = bb[12:]
    stored = struct.unpack(">I", bb[4:8])[0]
    r["bootable"] = r["dos"] and stored == checksum(bb) and code.strip(b"\x00") != b""
    r["text"] = readable_strings(bb, 5, 20)

    if not r["dos"]:
        r["kind"] = "no DOS bootblock (data disk or custom format)"
        return r
    if not r["bootable"]:
        r["kind"] = "DOS, not bootable"
        return r

    hooks = sorted({desc for pat, desc in _HOOK_PATTERNS if pat.search(code)})
    lower = bb.decode("latin-1").lower()
    vtext = [v for v in _VIRUS_TEXT if v in lower]
    used = len(code.rstrip(b"\x00"))
    standardish = (b"dos.library" in code and used <= 100 and not hooks)

    if standardish:
        r["kind"] = "standard AmigaDOS boot code"
    elif hooks:
        r["kind"] = "custom boot code - SUSPICIOUS"
        r["flags"] = hooks + [f'contains text "{v}"' for v in vtext]
    else:
        r["kind"] = "custom boot code (loader, intro or protection)"
        if vtext:
            # Text alone proves nothing: crack intros and virus killers often say "virus free".
            r["notes"] = [f'mentions "{v}" but its code shows no virus behaviour' for v in vtext]
    return r
