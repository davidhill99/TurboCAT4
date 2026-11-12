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
    tools = [t for t in ("7z", "lha") if shutil.which(t)]
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
    xdms = shutil.which("xdms")
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
    where = ", ".join(emulator.ROM_DIRS[:2]) + "…"
    if len(have) == len(models):
        out.append(Check("Kickstart ROMs", "The Amiga's built-in software, needed to start most disks", OK,
                         "found for " + ", ".join(have)))
    else:
        missing = [m for m in models if m not in roms]
        out.append(Check(
            "Kickstart ROMs", "The Amiga's built-in software, needed to start most disks",
            PARTIAL if have else MISSING,
            ("found for " + ", ".join(have) + "; " if have else "") + "none for " + ", ".join(missing),
            without="The emulator falls back on its own free replacement (AROS), which some disks "
                    "don't work with",
            url="https://www.amigaforever.com",
            advice=f"Kickstart ROMs are copyrighted, so TurboCAT can't include them. They come with "
                   f"Amiga Forever, or can be copied from your own Amiga. Put them in {where} "
                   f"(Amiga Forever's encrypted ROMs work when rom.key is beside them).",
            important=not have))

    # TurboView and the optional online parts
    ok = os.path.exists(turboview.PROGRAM)
    out.append(Check("TurboView", "The Amiga side of TurboCAT, run inside the emulator",
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
