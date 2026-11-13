"""Start a catalogued disk (or a set of disks) in Amiberry or FS-UAE.

TurboCAT picks a sensible Amiga for the disk (an A1200 for AGA titles, otherwise an A500), finds a
matching Kickstart ROM by its contents (Amiga Forever's encrypted ROMs work when rom.key is beside
them), puts a set's disks in DF0: to DF3: (an Amiga's four drives), and more than four in the
emulator's disk swapper too.
Disks the emulators can't open directly (one of several ADFs in an archive, an ADF inside an
LHA) are unpacked to ~/.cache/turbocat/play first.
"""
import glob
import hashlib
import os
import re
import shutil
import subprocess
import zipfile
import zlib

from . import gotek
from .pictures import CACHE, clean_title, normal

PLAY_DIR = os.path.join(CACHE, "play")
AMIBERRY_FLATPAK = "com.blitterstudio.amiberry"
ROM_DIRS = ["~/Amiberry/ROMs", "~/Amiberry/Kickstarts", "~/Amiberry/roms",
            "~/Documents/FS-UAE/Kickstarts", "~/.var/app/com.blitterstudio.amiberry/data/amiberry/roms",
            "~/FS-UAE/Kickstarts",
            # Windows: Amiga Forever keeps its ROMs (with rom.key) in the shared Amiga Files folder
            "%PUBLIC%/Documents/Amiga Files/Shared/rom", "~/Documents/Amiga Files/Shared/rom",
            # macOS: Amiberry's and Amiga Forever's usual places
            "~/Library/Application Support/Amiberry/roms", "~/Library/Application Support/Amiberry/Kickstarts",
            "~/Documents/Amiberry/Kickstarts"]
EXTRA_ROM_DIRS = []      # folders where scanning found Kickstart ROMs (filled in by the window)
MODELS = ("A500", "A600", "A1200")
# Kickstarts each model can use, best first: (major version, minor version or None)
WANTED = {"A500": [(34, None), (40, 63), (37, 175)],
          "A600": [(37, 350), (37, 300), (37, 299), (40, 63)],
          "A1200": [(40, 68), (39, 106)]}
A4000_CRC = {"43b6dd22", "3ac99edc", "5b47f34a", "2238b0b4"}      # 3.1 A4000 ROMs: not for an A1200


# ---------------------------------------------------------------- finding things

def find_emulators():
    """{'amiberry': [command...], 'fs-uae': [command...]} for those installed."""
    found = {}
    if shutil.which("amiberry"):
        found["amiberry"] = ["amiberry"]
    elif shutil.which("flatpak"):
        try:
            r = subprocess.run(["flatpak", "info", AMIBERRY_FLATPAK], capture_output=True, timeout=15)
            if r.returncode == 0:
                found["amiberry"] = ["flatpak", "run", AMIBERRY_FLATPAK]
        except Exception:
            pass
    if shutil.which("fs-uae"):
        found["fs-uae"] = ["fs-uae"]
    return found


ROM_SIZES = (262144, 524288)
AF_HEADER = b"AMIROMTYPE1"            # Amiga Forever's encrypted ROMs: this, then the ROM XORed with rom.key


def looks_like_rom(head, size):
    """Whether a file is probably a Kickstart ROM, from its size and first bytes."""
    if size in ROM_SIZES:
        return head[:2] in (b"\x11\x11", b"\x11\x14")
    return size in tuple(n + len(AF_HEADER) for n in ROM_SIZES) and head[:11] == AF_HEADER


def rom_data(data, key=None):
    """(ROM bytes, encrypted) for a Kickstart file; the ROM is None if it is encrypted and there
    is no key, or if it isn't a Kickstart ROM."""
    encrypted = data[:11] == AF_HEADER
    if encrypted:
        body = data[11:]
        if not key:
            return None, True
        # XOR with the repeated key, all at once (a byte at a time took about a second per ROM).
        pad = (key * (len(body) // len(key) + 1))[:len(body)]
        data = (int.from_bytes(body, "big") ^ int.from_bytes(pad, "big")).to_bytes(len(body), "big")
    if len(data) not in ROM_SIZES or data[:2] not in (b"\x11\x11", b"\x11\x14"):
        return None, encrypted                  # Kickstart ROMs start with 1111 / 1114
    return data, encrypted


def rom_version(rom):
    """(major, minor, crc) of decrypted ROM bytes."""
    return (int.from_bytes(rom[12:14], "big"), int.from_bytes(rom[14:16], "big"),
            f"{zlib.crc32(rom) & 0xFFFFFFFF:08x}")


def read_key(folder):
    try:
        with open(os.path.join(folder, "rom.key"), "rb") as f:
            return f.read()
    except OSError:
        return None


def _rom_info(path):
    """(major, minor, crc) of a Kickstart ROM, decrypting Amiga Forever ROMs with rom.key."""
    try:
        size = os.path.getsize(path)
        if size not in ROM_SIZES and size not in tuple(n + len(AF_HEADER) for n in ROM_SIZES):
            return None
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    rom, _ = rom_data(data, read_key(os.path.dirname(path)) if data[:11] == AF_HEADER else None)
    return rom_version(rom) if rom else None


# Kickstart release names by exec's major version (and minor, where a major covers several).
RELEASES = {30: "1.0", 31: "1.1", 32: "1.1", 33: "1.2", 34: "1.3", 35: "1.3", 36: "2.0",
            37: "2.04", 38: "2.1", 39: "3.0", 40: "3.1", 45: "3.1.4", 46: "3.2", 47: "3.2"}
MINOR_RELEASES = {(37, 299): "2.05", (37, 300): "2.05", (37, 350): "2.05",
                  (47, 96): "3.2.1", (47, 111): "3.2.2"}
# Well-known ROMs by CRC32: (name, machine it was made for). Machine-specific ROMs (A3000,
# A4000, CD32) are not offered for the A500/A600/A1200 that Play in emulator sets up.
KNOWN_ROMS = {
    "428a9a4b": ("Kickstart 0.7 (beta)", ""), "299790ff": ("Kickstart 1.0", "A1000"),
    "d060572a": ("Kickstart 1.1 (NTSC)", "A1000"), "ec86dae2": ("Kickstart 1.1 (PAL)", "A1000"),
    "a6ce1636": ("Kickstart 1.2", "A500/A2000"), "c4f0f55f": ("Kickstart 1.3", "A500/A2000"),
    "e0f37258": ("Kickstart 1.3", "A500/A2000"), "bc0ec13f": ("Kickstart 2.0 beta", "A3000"),
    "c3bdb240": ("Kickstart 2.04", "A500+"), "43b0df7b": ("Kickstart 2.05", "A600HD"),
    "9e6ac152": ("Kickstart 3.0", "A1200"), "1483a091": ("Kickstart 3.1", "A1200"),
    "fc24ae0d": ("Kickstart 3.1", "A500/A600/A2000"), "efb239cc": ("Kickstart 3.1", "A3000"),
    "1e62d4a5": ("Kickstart 3.1", "CD32"), "261339f8": ("Kickstart 3.1 (Walker beta)", "Walker"),
    "42baa124": ("CDTV extended ROM", "CDTV"), "87746be2": ("CD32 extended ROM", "CD32"),
}
for _crc in A4000_CRC:
    KNOWN_ROMS.setdefault(_crc, ("Kickstart 3.1" if _crc != "3ac99edc" else "Kickstart 3.1.4", "A4000"))
NOT_FOR_PLAY = ("A3000", "A4000", "CD32", "CDTV", "Walker")
_EXEC_ID = re.compile(rb"exec(?:\.library)?(?: amiga-m68k)? (\d+)\.(\d+)")


def _exec_id(rom):
    """exec.library's ID string, found through its ROM tag, or b""."""
    base = 0x1000000 - len(rom)
    for m in re.finditer(rb"\x4a\xfc", rom):
        o = m.start()
        if int.from_bytes(rom[o + 2:o + 6], "big") != base + o:      # a ROM tag points at itself
            continue
        def text(addr):
            a = addr - base
            return rom[a:rom.find(b"\0", a)] if 0 <= a < len(rom) else b""
        if text(int.from_bytes(rom[o + 14:o + 18], "big")) == b"exec.library":
            return text(int.from_bytes(rom[o + 18:o + 22], "big")).strip()
    return b""


def describe_rom(rom):
    """What a (decrypted) ROM is: {name, version, crc, machine, kickstart, aros}."""
    major, minor, crc = rom_version(rom)
    exec_id = _exec_id(rom)
    aros = b"AROS" in rom
    out = {"crc": crc, "version": "", "machine": "", "kickstart": bool(exec_id) and not aros,
           "aros": aros, "major": major, "minor": minor}
    if aros:
        out["name"] = "AROS ROM (free replacement)" if exec_id else "AROS extended ROM"
        return out
    if crc in KNOWN_ROMS:
        out["name"], out["machine"] = KNOWN_ROMS[crc]
    if not exec_id:
        out.setdefault("name", "Extended ROM" if major != 0xFFFF and major < 60 else "Other Amiga ROM")
        return out
    m = _EXEC_ID.search(exec_id)
    if major == 0xFFFF and m and crc not in KNOWN_ROMS:   # the oldest keep it only in exec's tag
        major, minor = int(m.group(1)), int(m.group(2))
    if major != 0xFFFF:
        out["version"] = f"{major}.{minor}"
        out["major"], out["minor"] = major, minor
    if "name" not in out:
        rel = MINOR_RELEASES.get((major, minor)) or RELEASES.get(major)
        out["name"] = f"Kickstart {rel}" if rel else f"Kickstart (version {major}.{minor})"
    return out


def kickstart_name(major, minor, crc=""):
    """'Kickstart 1.3', 'Kickstart 3.1 (A4000)'..., or 'Kickstart (version 50.1)' if unknown."""
    if crc in KNOWN_ROMS:
        name, machine = KNOWN_ROMS[crc]
        return f"{name} ({machine})" if machine in NOT_FOR_PLAY and machine not in name else name
    rel = MINOR_RELEASES.get((major, minor)) or RELEASES.get(major)
    return f"Kickstart {rel}" if rel else f"Kickstart (version {major}.{minor})"


def models_for(major, minor, crc=""):
    """The models Play in emulator would start with this ROM (when it's the best one found)."""
    if KNOWN_ROMS.get(crc, ("", ""))[1] in NOT_FOR_PLAY:
        return []
    return [model for model, wants in WANTED.items()
            if any(major == ma and (mi is None or minor == mi) for ma, mi in wants)
            and not (model == "A1200" and crc in A4000_CRC)]


def catalogued_rom_dirs(cat):
    """Folders holding the Kickstart ROMs found by scanning, for Play and TurboView to use."""
    try:
        rows = cat.db.execute("SELECT source FROM media WHERE kind='kickstart' AND parent_id IS NULL")
        return sorted({os.path.dirname(r["source"]) for r in rows})
    except Exception:
        return []


def _all_roms(extra_dirs=()):
    """[(path, major, minor, crc)] for every Kickstart ROM in the usual folders."""
    roms = []
    for d in dict.fromkeys(list(extra_dirs) + EXTRA_ROM_DIRS + ROM_DIRS):
        d = os.path.expandvars(os.path.expanduser(d))
        if "%PUBLIC%" in d:
            continue                    # Windows' public folder, on a computer that hasn't one
        for p in sorted(glob.glob(os.path.join(glob.escape(d), "*"))):
            info = _rom_info(p)
            if info:
                roms.append((p, *info))
    return roms


def kickstart_list(extra_dirs=()):
    """Every Kickstart ROM found, for Check setup: [(path, name, models it starts)]."""
    out, seen = [], set()
    for p, ma, mi, crc in _all_roms(extra_dirs):
        if crc in seen:
            continue
        seen.add(crc)
        try:
            with open(p, "rb") as f:
                aros = b"AROS" in f.read(1 << 20)
        except OSError:
            aros = False
        if aros:      # the free replacement: starts many disks, but isn't a real Kickstart
            out.append((p, "AROS (free replacement, not a real Kickstart)", []))
        else:
            out.append((p, kickstart_name(ma, mi, crc), models_for(ma, mi, crc)))
    return out


def find_kickstarts(extra_dirs=()):
    """{model: path} for the Kickstart ROMs found."""
    roms = _all_roms(extra_dirs)
    found = {}
    for model, wants in WANTED.items():
        for major, minor in wants:
            match = [p for p, ma, mi, crc in roms
                     if model in models_for(ma, mi, crc) and ma == major
                     and (minor is None or mi == minor)]
            if match:
                found[model] = match[0]
                break
    return found


# ---------------------------------------------------------------- choosing disks

def guess_model(names):
    """An A1200 for AGA titles (TOSEC "(AGA)"; "OCS-AGA" runs on both), an A600 for "(ECS)"."""
    text = " ".join(names)
    if re.search(r"\(AGA\)|\(A1200\)|\(CD32\)", text, re.I):
        return "A1200"
    if re.search(r"\(ECS\)|\[KS2\.0\]|\(A600\)|\(A500\+\)", text, re.I):
        return "A600"
    return "A500"


def _disk_no(name):
    m = re.search(r"\bdisk\s*([0-9]+|[a-d])\b", name, re.I)
    if not m:
        return 99
    v = m.group(1)
    return int(v) if v.isdigit() else "abcd".index(v.lower()) + 1


def set_members(cat, top):
    """The other disks of the same set as `top` (same folder and title), in disk order."""
    folder, title = os.path.dirname(top["source"]), normal(clean_title(top["source"]))
    rows = [r for r in cat.db.execute("SELECT * FROM media WHERE parent_id IS NULL AND source LIKE ?",
                                      (folder.replace("%", "\\%") + "/%",))
            if os.path.dirname(r["source"]) == folder and normal(clean_title(r["source"])) == title
            and r["status"] != "empty"]
    if len(rows) < 2:
        return [top]
    # One disk per number: prefer the one chosen, then ones without problems.
    best = {}
    for r in sorted(rows, key=lambda r: (r["id"] != top["id"], r["status"] == "error", r["number"] or 0)):
        best.setdefault(_disk_no(os.path.basename(r["source"])), r)
    return [best[k] for k in sorted(best)]


def _cached(name, data):
    os.makedirs(PLAY_DIR, exist_ok=True)
    stem, ext = os.path.splitext(gotek.safe_name(name))
    path = os.path.join(PLAY_DIR, f"{stem} [{hashlib.sha1(data).hexdigest()[:8]}]{ext}")
    if not os.path.exists(path):
        with open(path + ".part", "wb") as f:
            f.write(data)
        os.replace(path + ".part", path)
    return path


def disk_files(cat, top_ids, whole_sets=True):
    """Files to hand to the emulator, in drive order, plus anything left out and why.
    Returns (files, whdload_lha or None, skipped [(name, why)], names for guessing the model)."""
    files, skipped, names = [], [], []
    tops = [cat.media_by_id(i) for i in top_ids]
    tops = [t for t in tops if t is not None]
    if whole_sets and len(tops) == 1:
        tops = set_members(cat, tops[0])
    for top in tops:
        names.append(os.path.basename(top["source"]))
        kids = cat.db.execute("SELECT * FROM media WHERE parent_id=? ORDER BY id", (top["id"],)).fetchall()
        if top["whd_name"] or any(k["whd_name"] for k in kids):
            if top["kind"] == "lha":
                return [], top["source"], skipped, names
            skipped.append((names[-1], "WHDLoad game in a format TurboCAT can't start yet"))
            continue
        # Copy-protected originals (IPF) inside a ZIP: both emulators read IPF.
        ipfs = [f["path"] for f in cat.db.execute(
            "SELECT path FROM files WHERE media_id=? AND lower(path) LIKE '%.ipf' ORDER BY path", (top["id"],))]
        if ipfs and top["kind"] == "zip":
            with zipfile.ZipFile(top["source"]) as z:
                for p in ipfs:
                    files.append(_cached(os.path.basename(p), z.read(p)))
            continue
        if top["source"].lower().endswith(".ipf"):
            files.append(top["source"])
            continue
        p = gotek.plan(cat, [top["id"]])
        skipped += [(name, why) for _, name, why in p.skipped]
        for d in p.disks:
            m = cat.media_by_id(d.media_id)
            if m["parent_id"] is None and m["kind"] in ("adf", "adz", "dms"):
                # A copy: a game that saves to its disk (high scores, settings) changes the copy,
                # never the original. The copy is kept, so saves are there the next time.
                with open(m["source"], "rb") as f:
                    files.append(_cached(os.path.basename(m["source"]), f.read()))
            elif m["parent_id"] == top["id"] and top["kind"] == "zip" and len(p.disks) == 1:
                files.append(top["source"])        # a ZIP holding one disk: also read directly
            else:
                files.append(_cached(d.name, gotek.adf_bytes(cat, d.media_id)))
    return files, None, skipped, names


# ---------------------------------------------------------------- Workbench first

# Some disks don't start by themselves (no boot block: "DOS, not bootable"): they were opened from
# Workbench. Play can start a Workbench disk from the collection in DF0: with them in DF1:.
WB_MODEL = {1: "A500", 2: "A600", 3: "A1200"}      # the smallest Amiga each Workbench runs on


def _boots(m):
    return m is not None and (m["boot_kind"] or "").startswith(("standard", "custom"))


def first_disk_boots(cat, top_ids):
    """True if the disk Play puts in DF0: starts by itself (None if it can't tell)."""
    tops = [cat.media_by_id(i) for i in top_ids]
    tops = [t for t in tops if t is not None]
    if not tops:
        return None
    if len(tops) == 1:
        tops = set_members(cat, tops[0])
    p = gotek.plan(cat, [tops[0]["id"]])
    if not p.disks:
        return None
    m = cat.media_by_id(p.disks[0].media_id)
    if m is None or m["kind"] not in ("adf", "adz", "dms"):
        return None
    return _boots(m)


def wb_version(volume):
    """'Workbench3.1' -> (3, '3.1'); 'Workbench 1.3' -> (1, '1.3'); else (None, '')."""
    v = re.search(r"(\d)\.(\d+)", volume or "")
    return (int(v.group(1)), f"{v.group(1)}.{v.group(2)}") if v else (None, "")


def find_workbenches(cat):
    """Catalogued Workbench disks that boot: [(media id, label, major version)], newest first,
    plain files before ones inside archives."""
    out = []
    for m in cat.db.execute(
            "SELECT * FROM media WHERE kind IN ('adf','adz','dms') AND status='ok' "
            "AND lower(volume) LIKE 'workbench%' ORDER BY parent_id IS NOT NULL, id"):
        if not _boots(m):
            continue
        if not cat.db.execute("SELECT 1 FROM files WHERE media_id=? AND lower(path)='c/loadwb'",
                              (m["id"],)).fetchone():
            continue
        major, ver = wb_version(m["volume"])
        if major is None:
            continue                     # Commodore's disks are "Workbench1.3", "Workbench3.1"...
        name = os.path.basename(m["inner_path"] or m["source"])
        out.append((m["id"], f"Workbench {ver}".strip() + f"  ·  {name}", major or 0))
    out.sort(key=lambda w: -w[2])
    return out


def workbench_file(cat, media_id):
    """A file the emulator can read for this Workbench disk."""
    m = cat.media_by_id(media_id)
    if m["parent_id"] is None:
        return m["source"]
    return _cached(os.path.basename(m["inner_path"]), gotek.adf_bytes(cat, media_id))


def model_for_workbench(major, model):
    """The Amiga to use: `model`, or a newer one if this Workbench needs a later Kickstart."""
    need = WB_MODEL.get(major or 1, "A500")
    return need if MODELS.index(need) > MODELS.index(model) else model


# ---------------------------------------------------------------- starting

# How big the emulator shows the Amiga. The picture keeps the Amiga's shape (no stretching to
# widescreen) and is centred.
DISPLAYS = {"window": "In a window", "1080p": "1080p window (1920 × 1080)",
            "fullscreen": "Full screen"}


def display_args(emulator, display):
    if emulator == "amiberry":
        shape = ["-s", "gfx_keep_aspect=true", "-s", "gfx_center_horizontal=smart",
                 "-s", "gfx_center_vertical=smart"]
        if display == "1080p":
            return ["-s", "gfx_width_windowed=1920", "-s", "gfx_height_windowed=1080"] + shape
        if display == "fullscreen":
            return ["-s", "gfx_fullscreen_amiga=fullwindow"] + shape     # borderless, at the screen's size
        return []
    if display == "1080p":
        return ["--window_width=1920", "--window_height=1080", "--keep_aspect=1"]
    if display == "fullscreen":
        return ["--fullscreen=1", "--fullscreen_mode=fullscreen-window", "--keep_aspect=1"]
    return []

DRIVES = 4          # DF0: to DF3:, as many as an Amiga can have
# FS-UAE keeps its own files (save states, disk overlays, logs) here, not in ~/Documents/FS-UAE
FSUAE_DIR = os.path.expanduser("~/.local/share/turbocat/fs-uae")
# A plain A1200 has 2 MB of Chip RAM and no Fast RAM; most owners added a trapdoor expansion, and
# some AGA games crash on 2 MB alone (Worms - The Director's Cut: "Software Failure"). So TurboCAT's
# A1200 has 8 MB of Fast RAM, the most a 68020 A1200 trapdoor card gave.
A1200_FAST_MB = 8


def command(emulator, base, model, rom, files, whdload=None, mounts=(), display="window",
            fast_floppy=False):
    """The command line that starts `emulator` with these disks. mounts: [(volume, folder)].
    fast_floppy: drives faster than a real Amiga's (Workbench started from a floppy takes over a
    minute at real speed; game loaders can mind, so only when asked)."""
    if emulator == "amiberry":
        cmd = list(base) + ["--model", model, "-G"]
        if rom:
            cmd += ["-r", rom]
        cmd += display_args(emulator, display)
        if model == "A1200":
            cmd += ["-s", f"fastmem_size={A1200_FAST_MB}"]
        if whdload:
            return cmd + ["--autoload", whdload]
        # An Amiga takes up to four floppy drives: a set of 2-4 disks goes in DF0:-DF3:, so a game
        # asking for disk 3 finds it in a drive; more than four are in the disk swapper as well.
        for i, f in enumerate(files[:DRIVES]):
            cmd += [f"-{i}", f]
        for i in range(1, min(len(files), DRIVES)):
            cmd += ["-s", f"floppy{i}type=0"]              # a 3.5" DD drive for each disk
        if len(files) > 1:
            cmd.append("-diskswapper=" + ",".join(f'"{f}"' if "," in f else f for f in files))
        for vol, folder in mounts:
            cmd += ["-s", f"filesystem2=rw,{vol}:{vol}:{folder},-128"]
        if fast_floppy:
            cmd += ["-s", "floppy_speed=800"]
        return cmd
    os.makedirs(FSUAE_DIR, exist_ok=True)
    cmd = list(base) + [f"--base_dir={FSUAE_DIR}", f"--amiga_model={model}"] + display_args(emulator, display)
    if rom:
        cmd.append(f"--kickstart_file={rom}")
    if model == "A1200":
        cmd.append(f"--fast_memory={A1200_FAST_MB * 1024}")
    if len(files) > 1:
        cmd.append(f"--floppy_drive_count={min(len(files), DRIVES)}")
    for i, f in enumerate(files[:DRIVES]):
        cmd.append(f"--floppy_drive_{i}={f}")
    for i, f in enumerate(files):
        cmd.append(f"--floppy_image_{i}={f}")
    for i, (vol, folder) in enumerate(mounts):
        cmd += [f"--hard_drive_{i}={folder}", f"--hard_drive_{i}_label={vol}",
                f"--hard_drive_{i}_priority=-128"]
    if fast_floppy:
        cmd.append("--floppy_drive_speed=0")              # 0: as fast as possible
    return cmd


def turboview_command(emulator, base, rom, folder, roots, display="window"):
    """An A1200 that boots from the TurboView folder (TurboCAT:), with the collection folders
    mounted read-only under their volume names so TurboView can show Amiga paths."""
    roots = [(p, v) for p, v in roots if os.path.isdir(p) and "," not in p]
    if emulator == "amiberry":
        cmd = list(base) + ["--model", "A1200", "-G"]
        if rom:
            cmd += ["-r", rom]
        cmd += display_args(emulator, display)
        cmd += ["-s", "gfx_resolution=superhires"]     # TurboView's own 1280x512 screen, in full detail
        cmd += ["-s", "floppy1type=0"]                 # a second drive, DF1:
        # A browsing tool needn't run at original speed: fast RAM and the CPU flat out.
        cmd += ["-s", "fastmem_size=8", "-s", "cpu_speed=max", "-s", "cpu_cycle_exact=false"]
        cmd += ["-s", f"filesystem2=rw,DH0:TurboCAT:{folder},0"]
        for i, (path, vol) in enumerate(roots, 1):
            cmd += ["-s", f"filesystem2=ro,DH{i}:{vol}:{path},-128"]
        return cmd
    os.makedirs(FSUAE_DIR, exist_ok=True)
    cmd = list(base) + [f"--base_dir={FSUAE_DIR}", "--amiga_model=A1200", "--floppy_drive_count=2", "--fast_memory=8192",
                        "--uae_cpu_speed=max", "--uae_gfx_resolution=superhires",
                        f"--hard_drive_0={folder}", "--hard_drive_0_label=TurboCAT"] + display_args(emulator, display)
    if rom:
        cmd.append(f"--kickstart_file={rom}")
    for i, (path, vol) in enumerate(roots, 1):
        cmd += [f"--hard_drive_{i}={path}", f"--hard_drive_{i}_label={vol}",
                f"--hard_drive_{i}_read_only=1", f"--hard_drive_{i}_priority=-128"]
    return cmd


def launch(cmd):
    """Start the emulator on its own (closing TurboCAT doesn't close it)."""
    return subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)
