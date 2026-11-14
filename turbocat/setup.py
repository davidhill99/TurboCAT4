"""Check setup: what TurboCAT needs, what it found, and how to get what is missing.

Each check says what a part is for, whether it was found, which features go without it, and how
to get it on this computer (a command to copy and/or a web page), worded for Linux (apt, dnf or
pacman), macOS (Homebrew) or Windows.
"""
import importlib
import os
import platform
import shutil
import sys
from dataclasses import dataclass, field

from . import tools as helpers

OK, PARTIAL, MISSING = "ok", "partial", "missing"


@dataclass
class Check:
    name: str
    purpose: str
    status: str
    detail: str = ""
    without: str = ""            # what doesn't work while it is missing
    command: str = ""            # a command to copy, for this computer
    url: str = ""                # a web page with downloads or instructions
    advice: str = ""             # words, when a command isn't enough
    important: bool = True       # missing it is worth telling the user about on start
    tags: list = field(default_factory=list)


def system():
    """'linux-apt', 'linux-dnf', 'linux-pacman', 'linux', 'mac' or 'windows'."""
    if sys.platform == "darwin":
        return "mac"
    if sys.platform.startswith("win"):
        return "windows"
    for tool in ("apt", "dnf", "pacman"):
        if shutil.which(tool):
            return "linux-" + tool
    return "linux"


def _install(packages, sys_name):
    """A package-manager command for this computer, or ''."""
    if not packages.get(sys_name.split("-")[-1] if sys_name.startswith("linux-") else sys_name):
        return ""
    names = packages[sys_name.split("-")[-1] if sys_name.startswith("linux-") else sys_name]
    return {"linux-apt": "sudo apt install ", "linux-dnf": "sudo dnf install ",
            "linux-pacman": "sudo pacman -S ", "mac": "brew install ",
            "windows": "winget install "}.get(sys_name, "") + names


def _pip(packages):
    exe = sys.executable or "python3"
    return f"{exe} -m pip install {packages}"


def _version(module):
    try:
        from importlib.metadata import version
        return version(module)
    except Exception:
        return ""


def run(emulators=None, kickstarts=None, music_versions=None):
    """Every check, in the order they are shown. The emulator and Kickstart searches can be
    passed in (the window may have them already)."""
    from . import emulator, identify, music, turboview
    s = system()
    out = []

    # Reading disks
    try:
        importlib.import_module("amitools.fs.ADFSVolume")
        out.append(Check("amitools", "Reads Amiga disks and their files (AmigaDOS OFS and FFS)", OK,
                         f"version {_version('amitools')}"))
    except Exception:
        out.append(Check("amitools", "Reads Amiga disks and their files (AmigaDOS OFS and FFS)", MISSING,
                         without="Scanning can't read inside disk images", command=_pip("amitools")))
    try:
        importlib.import_module("lhafile")
        out.append(Check("lhafile", "Opens LHA archives (WHDLoad games and most PD archives)", OK,
                         f"version {_version('lhafile')}"))
    except Exception:
        out.append(Check("lhafile", "Opens LHA archives (WHDLoad games and most PD archives)", MISSING,
                         without="LHA archives are catalogued but not opened", command=_pip("lhafile")))
    tools = [t for t in ("7z", "lha") if helpers.which(t)]
    has_lha = "lha" in tools                 # only lha reads -lh1-; 7-Zip helps with header types
    out.append(Check(
        "lha (lhasa)", "Opens older LHA archives the built-in reader can't (the -lh1- method of "
        "1990–91; 7-Zip also helps with some header types)", OK if has_lha else MISSING,
        ", ".join(tools),
        without="" if has_lha else ("LHA archives packed with the 1990–91 -lh1- method show as "
                                    "unreadable" + (" (7-Zip can't open them)" if tools else "")),
        command="" if has_lha else _install({"apt": "p7zip-full lhasa", "dnf": "p7zip lhasa",
                                           "pacman": "p7zip lhasa", "mac": "p7zip lhasa",
                                           "windows": "7zip.7zip"}, s),
        important=False))
    xdms = helpers.which("xdms")
    out.append(Check(
        "xdms", "Unpacks DMS disk images", OK if xdms else MISSING, xdms or "",
        without="" if xdms else "DMS images can't be read or copied to a Gotek",
        command="" if xdms else _install({"apt": "xdms", "pacman": "xdms"}, s),
        url="" if xdms else "https://zakalwe.fi/~shd/foss/xdms/",
        advice="" if xdms or s.startswith("linux-") else "Download xdms and put it where your system "
                                                           "finds programs (on your PATH)."))

    # Music
    vers = music_versions if music_versions is not None else music.versions()
    try:
        importlib.import_module("PySide6.QtMultimedia")
        qtm = True
    except Exception:
        qtm = False
    out.append(Check("Qt Multimedia", "Sends music to your speakers", OK if qtm else MISSING,
                     "" if not qtm else "part of PySide6-Addons",
                     without="" if qtm else "Music can't be played",
                     command="" if qtm else _pip("PySide6-Addons")))
    lib = {"apt": "libopenmpt0", "dnf": "libopenmpt", "pacman": "libopenmpt", "mac": "libopenmpt"}
    win = "Download libopenmpt for Windows and put libopenmpt.dll in TurboCAT's turbocat/lib folder."
    out.append(Check(
        "libopenmpt", "Plays music modules (ProTracker, MED, XM, S3M, IT…)",
        OK if vers.get("libopenmpt") else MISSING, f"version {vers['libopenmpt']}" if vers.get("libopenmpt") else "",
        without="" if vers.get("libopenmpt") else "Music modules can't be played (libxmp plays some)",
        command="" if vers.get("libopenmpt") else _install(lib, s),
        url="" if vers.get("libopenmpt") else "https://lib.openmpt.org/libopenmpt/download/",
        advice=win if s == "windows" and not vers.get("libopenmpt") else ""))
    lib = {"apt": "libxmp4", "dnf": "libxmp", "pacman": "libxmp", "mac": "libxmp"}
    out.append(Check(
        "libxmp", "Plays the tunes libopenmpt can't, such as OctaMED synth songs",
        OK if vers.get("libxmp") else MISSING, f"version {vers['libxmp']}" if vers.get("libxmp") else "",
        without="" if vers.get("libxmp") else "OctaMED synth songs play silently",
        command="" if vers.get("libxmp") else _install(lib, s),
        url="" if vers.get("libxmp") else "https://xmp.sourceforge.net/", important=False))

    # Emulators
    emus = emulators if emulators is not None else emulator.find_emulators()
    found = ", ".join({"amiberry": "Amiberry", "fs-uae": "FS-UAE"}[k] +
                      (" (Flatpak)" if v[:1] == ["flatpak"] else "") for k, v in emus.items())
    if emus:
        out.append(Check("Amiga emulator", "Plays disks (Play in emulator) and runs TurboView", OK, found))
    elif s == "windows":
        out.append(Check(
            "Amiga emulator", "Plays disks (Play in emulator) and runs TurboView", MISSING,
            without="Play in emulator and TurboView", url="https://fs-uae.net/download",
            advice="Install FS-UAE. (WinUAE, the usual Windows emulator, isn't supported by TurboCAT yet.)"))
    elif s == "mac":
        out.append(Check(
            "Amiga emulator", "Plays disks (Play in emulator) and runs TurboView", MISSING,
            without="Play in emulator and TurboView", url="https://amiberry.com",
            advice="Install Amiberry (amiberry.com) or FS-UAE (fs-uae.net)."))
    else:
        out.append(Check(
            "Amiga emulator", "Plays disks (Play in emulator) and runs TurboView", MISSING,
            without="Play in emulator and TurboView",
            command="flatpak install flathub com.blitterstudio.amiberry" if shutil.which("flatpak") else "",
            url="https://amiberry.com",
            advice="Install Amiberry (from Flathub or amiberry.com) or FS-UAE (fs-uae.net)."))

    # Kickstart ROMs
    roms = kickstarts if kickstarts is not None else emulator.find_kickstarts()
    models = ("A500", "A600", "A1200")
    have = [m for m in models if m in roms]
    where = {"windows": "Documents\\FS-UAE\\Kickstarts, or Amiga Forever's Amiga Files\\Shared\\rom folder",
             "mac": "Documents/FS-UAE/Kickstarts or Amiberry's roms folder"}.get(
        s, ", ".join(emulator.ROM_DIRS[:2]) + "…")
    try:
        listed = emulator.kickstart_list()
    except Exception:
        listed = []
    names = "; ".join(dict.fromkeys(name for _p, name, _m in listed))
    if len(have) == len(models):
        out.append(Check("Kickstart ROMs", "The Amiga's built-in software, needed to start most disks", OK,
                         "found for " + ", ".join(have) + (f" ({names})" if names else "")))
    else:
        missing = [m for m in models if m not in roms]
        out.append(Check(
            "Kickstart ROMs", "The Amiga's built-in software, needed to start most disks",
            PARTIAL if have else MISSING,
            ("found for " + ", ".join(have) + "; " if have else "") + "none for " + ", ".join(missing)
            + (f". Found: {names}" if names else ""),
            without="The emulator falls back on its own free replacement (AROS), which some disks "
                    "don't work with",
            url="https://www.amigaforever.com",
            advice=f"Kickstart ROMs are copyrighted, so TurboCAT can't include them. They come with "
                   f"Amiga Forever, or can be copied from your own Amiga. Put them in {where} "
                   f"(Amiga Forever's encrypted ROMs work when rom.key is beside them).",
            important=not have))

    # TurboView and the optional online parts
    ok = os.path.exists(turboview.PROGRAM)
    out.append(Check("TurboView", "The Amiga side of TurboCAT: search your collection on an emulated "
                     "or a real Amiga",
                     OK if ok else MISSING, "included" if ok else "",
                     without="" if ok else "The TurboView button",
                     advice="" if ok else "Build it from amiga/turboview.c (see the README).",
                     important=False))
    have_list = identify.have_list()
    out.append(Check("List of Amiga disks", "Finds the proper names of disks with unhelpful file names",
                     OK if have_list else MISSING,
                     "downloaded" if have_list else "",
                     without="" if have_list else "Disks are known by their file names only",
                     advice="" if have_list else "Optional: Tools › Identify disks online… downloads it "
                                                  "(about 12 MB, it asks first).",
                     important=False, tags=["identify"]))
    return out


# ---------------------------------------------------------------- what works, feature by feature

@dataclass
class Feature:
    name: str
    status: str                  # OK, PARTIAL or MISSING
    effect: str                  # in plain words: what works, or what doesn't and for how many disks
    needs: list = field(default_factory=list)    # the Check names it depends on
    important: bool = True
    detail: str = ""             # the longer story, shown on hover


def impact(cat):
    """How much of this collection each optional part matters for (catalogue queries only)."""
    from . import emulator
    q = lambda sql: cat.db.execute(sql).fetchone()[0]
    out = {
        "dms": q("SELECT COUNT(*) FROM media WHERE kind='dms'"),
        "dms_unread": q("SELECT COUNT(*) FROM media WHERE warnings LIKE '%DMS not unpacked%'"),
        "lha_unread": q("SELECT COUNT(*) FROM media WHERE problems LIKE '%LHA archive unreadable%'"),
        "modules": q("SELECT COUNT(*) FROM media WHERE kind='module'"),
        "disks": 0, "A1200": 0, "A600": 0,
    }
    for r in cat.db.execute("SELECT source, kind FROM media WHERE parent_id IS NULL "
                            "AND kind NOT IN ('module', 'kickstart', 'folder') AND status != 'empty'"):
        out["disks"] += 1
        model = emulator.guess_model([os.path.basename(r["source"])])
        if model in ("A1200", "A600"):
            out[model] += 1
    return out


def features(checks, imp=None, roms=None):
    """What works on this computer, feature by feature, worded for the user. imp: impact(cat);
    roms: emulator.find_kickstarts() ({model: path})."""
    c = {x.name: x for x in checks}
    ok = lambda name: name in c and c[name].status == OK
    imp = imp or {}
    roms = roms or {}
    n = lambda k: imp.get(k, 0)
    out = []

    out.append(Feature("Reading disk images", OK if ok("amitools") else MISSING,
                       "Disks and their files are read" if ok("amitools")
                       else "Disk images are listed, but nothing inside them can be read", ["amitools"]))

    if not ok("lhafile"):
        out.append(Feature("LHA archives", MISSING, "LHA archives (most WHDLoad games and PD archives) "
                           "are listed but not opened", ["lhafile", "lha (lhasa)"]))
    elif ok("lha (lhasa)"):
        out.append(Feature("LHA archives", OK, "All LHA archives open, old 1990–91 ones too",
                           ["lhafile", "lha (lhasa)"]))
    else:
        out.append(Feature("LHA archives", PARTIAL if n("lha_unread") else OK,
                           (f"{n('lha_unread'):,} old LHA archive{'s' if n('lha_unread') != 1 else ''} in your "
                            "collection can't be opened until lha is installed") if n("lha_unread") else
                           "Open, apart from old 1990–91 ones (none in your collection so far)",
                           ["lhafile", "lha (lhasa)"], important=bool(n("lha_unread"))))

    if ok("xdms"):
        out.append(Feature("DMS disk images", OK, "DMS images are unpacked, read and copied", ["xdms"]))
    else:
        out.append(Feature("DMS disk images", MISSING if n("dms") else OK,
                           (f"{n('dms'):,} DMS image{'s' if n('dms') != 1 else ''} in your collection can't be "
                            "read, played or copied to a Gotek") if n("dms") else
                           "Not needed so far: there are no DMS images in your collection", ["xdms"],
                           important=bool(n("dms"))))

    if ok("Qt Multimedia") and ok("libopenmpt"):
        out.append(Feature("Playing music", OK if ok("libxmp") else PARTIAL,
                           "Music modules play" + ("" if ok("libxmp") else
                                                   ", apart from OctaMED synth songs (they need libxmp)"),
                           ["Qt Multimedia", "libopenmpt", "libxmp"], important=bool(n("modules"))))
    else:
        out.append(Feature("Playing music", MISSING,
                           (f"The {n('modules'):,} music modules in your collection can't be played"
                            if n("modules") else "Music modules can't be played"),
                           ["Qt Multimedia", "libopenmpt", "libxmp"], important=bool(n("modules"))))

    emu = ok("Amiga emulator")
    if not emu:
        out.append(Feature("Playing disks in an emulator", MISSING,
                           "Play in emulator doesn't work until an Amiga emulator is installed",
                           ["Amiga emulator", "Kickstart ROMs"]))
    else:
        gaps = []
        if "A500" not in roms:
            gaps.append("Most disks start with AROS, the free replacement, which many games don't "
                        "work with. An A500 Kickstart 1.3 fixes that.")
        if "A1200" not in roms and n("A1200"):
            gaps.append(f"{n('A1200'):,} AGA disk{'s' if n('A1200') != 1 else ''} in your collection "
                        "need an A1200 Kickstart 3.x.")
        if "A600" not in roms and n("A600"):
            gaps.append(f"{n('A600'):,} ECS disk{'s' if n('A600') != 1 else ''} need a Kickstart 2.x.")
        short = ("Works, but there are no Kickstart ROMs, so many games won't start" if not roms else
                 "Works, but some disks need a Kickstart you haven't got")
        out.append(Feature("Playing disks in an emulator", PARTIAL if gaps else OK,
                           short if gaps else "Disks start in the emulator with the right Kickstart",
                           ["Amiga emulator", "Kickstart ROMs"], detail="\n".join(gaps)))

    tv = ok("TurboView")
    out.append(Feature("TurboView", OK if emu and tv else PARTIAL if tv else MISSING,
                       "Search your collection on an emulated or a real Amiga" if emu and tv else
                       "Works on a real Amiga; starting it here needs an Amiga emulator" if tv else
                       "Needs the TurboView program",
                       ["Amiga emulator", "TurboView"], important=False))

    out.append(Feature("Copying to a Gotek stick", OK if ok("xdms") or not n("dms") else PARTIAL,
                       "Works" if ok("xdms") or not n("dms") else
                       "Works, apart from DMS images (they need xdms)", ["xdms"]))

    home = os.path.expanduser("~")
    writable = os.access(home, os.W_OK)
    out.append(Feature("Repairing damaged disks", OK if ok("amitools") and writable else MISSING,
                       "Repaired copies are made in ~/TurboCAT/Repaired" if ok("amitools") and writable
                       else "Needs amitools, and a home folder TurboCAT can write to", ["amitools"]))

    out.append(Feature("Proper names for disks", OK if ok("List of Amiga disks") else PARTIAL,
                       "Disks are identified by their checksums" if ok("List of Amiga disks") else
                       "Disks are known by their file names only, until the list of Amiga disks is "
                       "downloaded (Tools › Identify disks online…)", ["List of Amiga disks"], important=False))
    return out


def overall(feats):
    """'ok', 'partial' or 'missing': for the toolbar's status dot."""
    worst = [f.status for f in feats if f.important and f.status != OK]
    return MISSING if MISSING in worst else PARTIAL if worst else OK


def summary(checks):
    """(headline, missing important checks)."""
    missing = [c for c in checks if c.status != OK]
    important = [c for c in missing if c.important]
    if not missing:
        return "Everything TurboCAT uses is here.", []
    if not important:
        return "TurboCAT has everything it needs; a few optional extras are missing.", []
    return (f"{len(important)} thing{'s' if len(important) > 1 else ''} to set up "
            f"for everything to work.", important)


def platform_name():
    s = system()
    if s == "mac":
        return f"macOS {platform.mac_ver()[0]}".strip()
    if s == "windows":
        return f"Windows {platform.release()}"
    try:
        info = platform.freedesktop_os_release()
        return info.get("PRETTY_NAME", "Linux")
    except Exception:
        return "Linux"


# ---------------------------------------------------------------- hover notes for the Setup window

def _rom_folders():
    """Where Kickstart ROMs can go on this system, shortest list first."""
    s = system()
    if s == "windows":
        return [r"C:\Users\Public\Documents\Amiga Files\Shared\rom (Amiga Forever)",
                r"Documents\Amiga Files\Shared\rom"]
    if s == "mac":
        return ["~/Library/Application Support/Amiberry/Kickstarts (Amiberry)",
                "~/Documents/FS-UAE/Kickstarts (FS-UAE)"]
    return ["~/Amiberry/Kickstarts (Amiberry)",
            "~/.var/app/com.blitterstudio.amiberry/data/amiberry/roms (Amiberry from Flathub)",
            "~/Documents/FS-UAE/Kickstarts (FS-UAE)"]


def _found_roms():
    from . import emulator
    home = os.path.expanduser("~")
    dirs = sorted({d for d in emulator.EXTRA_ROM_DIRS if d})
    return [d.replace(home, "~", 1) for d in dirs]


def guide(name):
    """The hover note for a feature or part in the Setup window: what it does, what to do, and
    where any files go. "" if there's nothing more to say."""
    s = system()
    apt = s == "linux-apt"
    install = (lambda pkg: f"Install it: sudo apt install {pkg}" if apt else
               "It comes with TurboCAT on Windows and macOS." if s in ("windows", "mac") else
               f"Install the {pkg} package with your system's package manager.")
    roms = "\n".join("  • " + d for d in _rom_folders())
    found = _found_roms()
    found = ("\nTurboCAT found Kickstarts in:\n" + "\n".join("  • " + d for d in found)) if found else ""
    notes = {
        "Reading disk images": (
            "What it does: reads ADF, ADZ, DMS, HDF and IPF disk images, and the ZIP, LHA and LZX "
            "archives they come in, and lists every file on them.",
            "What to do: Scan ▾ › Choose scan folders…, and tick the folders where you keep your disks.",
            "Where files go: anywhere. TurboCAT only reads them; it never moves or changes them."),
        "LHA archives": (
            "What it does: opens LHA archives (WHDLoad games, Aminet and PD archives). Old ones from "
            "1990–91 need the lha program as well.",
            "What to do: " + install("lhasa") + " Then Rescan; archives it couldn't open are read again.",
            ""),
        "DMS disk images": (
            "What it does: unpacks DMS images, so they can be read, played and copied to a Gotek.",
            "What to do: " + install("xdms") + " Then Rescan.",
            ""),
        "Playing music": (
            "What it does: plays Amiga music modules (ProTracker, MED, and others) found on your disks.",
            "What to do: " + install("libopenmpt0") + " for the player.",
            ""),
        "Playing disks in an emulator": (
            "What it does: Play starts a disk (or a whole set) in Amiberry or FS-UAE, on the right Amiga "
            "with the right Kickstart.",
            "What to do: install Amiberry (amiberry.com, or Flathub) or FS-UAE (fs-uae.net"
            + (", or: sudo apt install fs-uae" if apt else "") + "), and add Kickstart ROMs: 1.3 for "
            "the A500, 2.05 for the A600, 3.1 for the A1200. Amiga Forever (amigaforever.com) sells "
            "them; or copy them from your own Amiga.",
            "Where Kickstart files go: any folder you scan (TurboCAT recognises ROMs by their "
            "contents, whatever they're called), or one of these:\n" + roms + found),
        "TurboView": (
            "What it does: TurboView is the Amiga side of TurboCAT. It lists and searches your whole "
            "collection on an Amiga, so you can find what is on each disk and which disk or Gotek "
            "image holds the game or tool you want. The TurboView button starts it in an emulated "
            "A1200 with your collection folders as drives; there it can also put a disk straight "
            "into a drive.",
            "What to do: in an emulator, it needs an emulator and a Kickstart 3.x ROM (see Playing "
            "disks in an emulator). On a real Amiga: Tools › TurboView on a real Amiga… makes two "
            "TurboView floppies that start by themselves (disk 1: your disks and what is on each; "
            "disk 2: quick searches of every file name), for a Gotek or real floppies, and says how to "
            "install them on a hard drive (TurboView INSTALL DH0:TurboCAT), with its own Workbench icon "
            "to keep it handy. It runs on Kickstart 1.3 and later (as a window from 2.04). Make them "
            "again after a scan, so it knows about new disks.",
            "Where files go: TurboView's folder is ~/Amiberry/HardDrives/TurboCAT if you have an "
            "Amiberry folder, otherwise ~/TurboCAT-Amiga. TurboCAT keeps TurboCAT.cat there up to "
            "date."),
        "Copying to a Gotek stick": (
            "What it does: copies disks to a USB stick for a Gotek floppy emulator, with their own names "
            "or numbered DSKA0000.ADF, DSKA0001.ADF… (for FlashFloppy's numbered mode).",
            "What to do: plug in a USB stick formatted FAT32; TurboCAT finds it once it's mounted.",
            "Where files go: the top folder of the stick."),
        "Repairing damaged disks": (
            "What it does: rebuilds a damaged disk as a new image, putting back damaged files from copies "
            "on your other disks. The original is never changed.",
            "What to do: nothing to install. Choose a disk under Problems › Can be fixed.",
            "Where files go: repaired copies in ~/TurboCAT/Repaired; a log of what came from where in "
            "~/.local/share/turbocat/repairs.csv."),
        "Proper names for disks": (
            "What it does: finds each disk's proper TOSEC name from its checksum, however its file is "
            "called.",
            "What to do: Tools › Identify disks online… downloads TOSEC's lists once (about 100 MB), "
            "and again every two months. Or put TOSEC .dat files beside your disks.",
            "Where files go: the lists are kept in ~/.cache/turbocat/tosec. Your files aren't renamed "
            "unless you choose Tools › Rename files to their proper names…"),
        "Kickstart ROMs": (
            "What it is: the Amiga's built-in software. Most disks need one to start.",
            "What to do: Amiga Forever (amigaforever.com) sells them legally, or copy them from your own "
            "Amiga. You want 1.3 (A500), 2.05 (A600) and 3.1 (A1200).",
            "Where Kickstart files go: any folder you scan, or one of these:\n" + roms + found),
        "Amiga emulator": (
            "What it is: the program that runs an Amiga on this computer, for Play and TurboView.",
            "What to do: install Amiberry (amiberry.com, or Flathub: com.blitterstudio.amiberry) or "
            "FS-UAE" + (" (sudo apt install fs-uae)" if apt else " (fs-uae.net)") + ". Both can be "
            "installed; the Play window lets you choose.",
            "Where files go: FS-UAE keeps its save states and disk changes in "
            "~/.local/share/turbocat/fs-uae. Play gives emulators copies of your disks, so your "
            "originals are never written to."),
    }
    aliases = {"amitools": "Reading disk images", "lhafile": "LHA archives", "lha (lhasa)": "LHA archives",
               "xdms": "DMS disk images", "libopenmpt": "Playing music", "libxmp": "Playing music",
               "Qt Multimedia": "Playing music", "List of Amiga disks": "Proper names for disks"}
    parts = notes.get(name) or notes.get(aliases.get(name, ""))
    return "\n\n".join(p for p in parts if p) if parts else ""
