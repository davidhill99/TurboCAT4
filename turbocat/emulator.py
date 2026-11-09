"""Start a catalogued disk (or a set of disks) in Amiberry or FS-UAE.

TurboCAT picks a sensible Amiga for the disk (an A1200 for AGA titles, otherwise an A500), finds a
matching Kickstart ROM by its contents (Amiga Forever's encrypted ROMs work when rom.key is beside
them), puts the first disks in DF0:/DF1: and the rest in the emulator's disk swapper.
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
            "~/FS-UAE/Kickstarts"]
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


def _rom_info(path):
    """(major, minor, crc) of a Kickstart ROM, decrypting Amiga Forever ROMs with rom.key."""
    try:
        size = os.path.getsize(path)
        if size not in (262144, 524288, 262155, 524299):
            return None
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    if data[:11] == b"AMIROMTYPE1":
        key_path = os.path.join(os.path.dirname(path), "rom.key")
        try:
            with open(key_path, "rb") as f:
                key = f.read()
        except OSError:
            return None
        body = data[11:]
        if not key:
            return None
        # XOR with the repeated key, all at once (a byte at a time took about a second per ROM).
        pad = (key * (len(body) // len(key) + 1))[:len(body)]
        data = (int.from_bytes(body, "big") ^ int.from_bytes(pad, "big")).to_bytes(len(body), "big")
    if data[:2] not in (b"\x11\x11", b"\x11\x14"):         # Kickstart ROMs start with 1111 / 1114
        return None
    major = int.from_bytes(data[12:14], "big")
    minor = int.from_bytes(data[14:16], "big")
    return major, minor, f"{zlib.crc32(data) & 0xFFFFFFFF:08x}"


def find_kickstarts(extra_dirs=()):
    """{model: path} for the Kickstart ROMs found."""
    roms = []
    for d in list(extra_dirs) + ROM_DIRS:
        for p in sorted(glob.glob(os.path.join(os.path.expanduser(d), "*"))):
            info = _rom_info(p)
            if info:
                roms.append((p, *info))
    found = {}
    for model, wants in WANTED.items():
        for major, minor in wants:
            match = [p for p, ma, mi, crc in roms
                     if ma == major and (minor is None or mi == minor)
                     and not (model == "A1200" and crc in A4000_CRC)]
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
                files.append(m["source"])          # the emulators read these as they are
            elif m["parent_id"] == top["id"] and top["kind"] == "zip" and len(p.disks) == 1:
                files.append(top["source"])        # a ZIP holding one disk: also read directly
            else:
                files.append(_cached(d.name, gotek.adf_bytes(cat, d.media_id)))
    return files, None, skipped, names


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

def command(emulator, base, model, rom, files, whdload=None, mounts=(), display="window"):
    """The command line that starts `emulator` with these disks. mounts: [(volume, folder)]."""
    if emulator == "amiberry":
        cmd = list(base) + ["--model", model, "-G"]
        if rom:
            cmd += ["-r", rom]
        cmd += display_args(emulator, display)
        if whdload:
            return cmd + ["--autoload", whdload]
        for i, f in enumerate(files[:2]):
            cmd += [f"-{i}", f]
        if len(files) > 1:
            cmd.append("-diskswapper=" + ",".join(f'"{f}"' if "," in f else f for f in files))
        for vol, folder in mounts:
            cmd += ["-s", f"filesystem2=rw,{vol}:{vol}:{folder},-128"]
        return cmd
    cmd = list(base) + [f"--amiga_model={model}"] + display_args(emulator, display)
    if rom:
        cmd.append(f"--kickstart_file={rom}")
    for i, f in enumerate(files[:2]):
        cmd.append(f"--floppy_drive_{i}={f}")
    for i, f in enumerate(files):
        cmd.append(f"--floppy_image_{i}={f}")
    for i, (vol, folder) in enumerate(mounts):
        cmd += [f"--hard_drive_{i}={folder}", f"--hard_drive_{i}_label={vol}",
                f"--hard_drive_{i}_priority=-128"]
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
    cmd = list(base) + ["--amiga_model=A1200", "--floppy_drive_count=2", "--fast_memory=8192",
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
