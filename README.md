# TurboCAT 4

*[Deutsch: LIESMICH.md](LIESMICH.md)*

**TurboCAT 4 catalogues your Amiga disk images on Windows, macOS and Linux, and with TurboView you
can search your whole collection on the Amiga itself, real or emulated.**

TurboCAT is the revival of TurboCAT and TurboCAT-Pro, an Amiga disk cataloguer from 1994–1996 by
David Hill. Version 4 continues the original numbering.

> **Beta.** This is a public test release (4.0.0-beta.2). Reports of what works and what
> doesn't are very welcome: Help › Report a problem… in TurboCAT, or tcpturbocat@gmail.com.

## What it does

- **Reads everything:** ADF (DD and HD), DMS, ADZ, HDF hard-drive images, LHA (including WHDLoad
  packs), LZX, ZIP (including TOSEC packs) and folders used as emulator hard drives. Archives inside
  archives are opened too.
- **Finds anything:** every file, disk name and WHDLoad game, instantly.
- **Checks your disks:** damaged disks, suspicious bootblocks (the behaviour of bootblock viruses) and
  duplicates. Duplicates are only hidden, never deleted.
- **Recognises them:** games, demos, utilities and magazine coverdisks by their checksums (TOSEC
  lists); multi-disk sets on one row, with missing disks pointed out.
- **Pictures and music:** title screens, screenshots and magazine covers; music modules (MOD, MED and
  more) play straight from the disk.
- **Plays them:** one click starts a disk in an emulator (WinUAE, FS-UAE or Amiberry). You supply the
  Kickstart ROMs (from Amiga Forever or your own Amiga); Help › Check setup explains where they go.
- **Gotek:** copies disks to a Gotek USB stick, numbered if you like.
- **Repairs:** makes repaired copies of damaged disks and looks on Aminet for missing files. Your
  original images are never changed.

## TurboView: your collection on the Amiga

If you use a Gotek you know the problem: hundreds of images on the stick, and a display that shows
only a three-digit number. TurboView puts the catalogue on the Amiga itself: type part of a name and
it tells you which disk, or which Gotek image, holds the game, tool or file. No PC needed.

- **Runs on any Amiga from Kickstart 1.3:** a window on Workbench from 2.04, the Shell on 1.3.
- **No hard drive needed:** Tools › TurboView on a real Amiga… makes two TurboView floppies that start
  by themselves, for a Gotek or real disks. Disk 1 has every disk and what is on it; disk 2 a quick
  index of every file name.
- **Or on a hard drive:** `TurboView:TurboView INSTALL DH0:TurboCAT`. Like the original it is a
  Workbench tool: double-click its icon (its CATALOGUE tooltype says where its lists are), keep it
  open beside your work, zoom it down to its title bar, or put it in WBStartup. The hard-drive
  install is **experimental**: meant for an A1200 or any Amiga with Kickstart 2.04+.
- **Stays up to date:** after the next scan, make the disks again. An installed TurboView notices the
  new disk 1 in a drive and offers to update itself (keeping its icon's tooltypes, and a copy in
  WBStartup).
- **In an emulator:** the TurboView button starts it with your folders as drives, and it can put the
  disk you found straight into a drive.

TurboView on real hardware is new and not yet widely tested. Please report how it went with
Help › How TurboView went on your Amiga…; the
[tester's checklist](docs/testing-turboview-on-a-real-amiga.md) says what to try.

## Download

Ready-to-run packages are on the [Releases](https://github.com/davidhill99/TurboCAT4/releases) page.
Each carries everything it needs (Python, Qt, 7-Zip for LHA, xdms for DMS, libopenmpt for music):
you only install an emulator and Kickstart ROMs.

- **Windows:** `TurboCAT-…-Windows-Setup.exe` (installs for you only, no admin rights), or the
  portable zip. Until the package is signed Windows says "Windows protected your PC": More info ›
  Run anyway.
- **macOS:** `TurboCAT-…-macOS-AppleSilicon.dmg` (M1 and later) or `TurboCAT-…-macOS-Intel.dmg`
  (older Macs). Also unsigned, so the first time: right-click the app › Open.
- **Linux:** `TurboCAT-…-x86_64.AppImage`. Make it executable and run it.

Included programs: 7-Zip (LGPL, 7-zip.org), xdms 1.3.2 (public domain, compiled from
zakalwe.fi/~shd/foss/xdms), libopenmpt (BSD, lib.openmpt.org).

## Format details

| Format | Notes |
|---|---|
| ADF (DD and HD) | AmigaDOS OFS/FFS disks fully listed; non-DOS game/demo disks identified by bootblock and readable text |
| DMS | Unpacked with `xdms`; fingerprinted as the disk inside, so a DMS and its ADF count as duplicates |
| ADZ | Gzipped ADF |
| HDF | RDB hard drives (all OFS/FFS partitions) and single-partition images. PFS3/SFS partitions are reported but not read yet |
| LHA | Including WHDLoad packs — game name and credits read from the `.slave` |
| LZX | Contents listed (experimental — not yet tested on a real LZX archive) |
| ZIP | Including TOSEC packs — the disk inside is read and listed |
| Amiga folders | Folders used as emulator hard drives (detected by `S/Startup-Sequence` etc.) |

## A bit of history

TurboCAT was written in CanDo between 1994 and 1996, and the UK magazine *Amiga Shopper* featured it
three times (scans on the Internet Archive):

- **August 1995, issue 52:** TurboCat 3 as an exclusive version on the coverdisk, already with
  TurboView as its "companion program" for searching the collection.
  [Page 6](https://archive.org/details/Amiga_Shopper_Issue_52_1995-08_Future_Publishing_GB/page/n5/mode/2up)
- **February 1996, issue 59:** TurboCAT-Pro 1.2 reviewed, **85%**.
  [Pages 76–77](https://archive.org/details/Amiga_Shopper_Issue_59_1996-02_Future_Publishing_GB/page/n75/mode/2up)
- **May 1996, issue 62:** TurboCAT-Pro 2 reviewed, **90% and a Star Buy**: "my favourite cataloguer".
  [Pages 70–71](https://archive.org/details/Amiga_Shopper_Issue_62_1996-05_Future_Publishing_GB/page/n69/mode/2up)

## Licence and contact

TurboCAT 4 is free software: you can use, share and change it under the terms of the **GNU General
Public License, version 3 or later** (see [LICENSE](LICENSE)). It builds on amitools (GPL-2.0-or-later),
Qt for Python (LGPL), lhafile (BSD), libopenmpt (BSD), 7-Zip (LGPL) and xdms (public domain), and on
Keir Fraser's public-domain 68000 inflate in TurboView.

Contact: **tcpturbocat@gmail.com** (or Help › Report a problem / Suggest an idea in TurboCAT).

**Support TurboCAT:** it's free, and always will be. If it's helped you, you can buy its author a coffee at [ko-fi.com/tcpturbocat](https://ko-fi.com/tcpturbocat) (also Help › Support TurboCAT 4…).

## Privacy

TurboCAT collects nothing about you: no accounts, analytics or tracking, and your disks and catalogue never leave your computer. [PRIVACY.md](PRIVACY.md) lists what it contacts online and when (the same text is in Help › Privacy).

## What's new and what's next

[CHANGELOG.md](CHANGELOG.md) lists the changes in each release. Planned next:

- **German** (and other languages) in TurboCAT itself, once the beta wording settles: translators
  welcome
- **Watched folders:** new, changed and deleted images picked up automatically
- **TurboView kept up to date by itself:** its catalogue re-exported to chosen places (Gotek stick,
  emulator hard-drive folder, Pi SD card) whenever the catalogue changes; a start-up check that flags
  new and missing images; an "I want this" list that TurboCAT copies to the Gotek stick
- **TurboView on the Amiga:** playing modules, and reading new ADFs on the Amiga itself into a
  top-up file until the next scan
- **Ideas being considered:** "Music Modules" disks for the Gotek (tunes collected onto ADFs rather
  than a whole disk each); recognising disk sets from TOSEC lists even when renamed; module ratings
  from The Mod Archive
- **Later:** PFS3/SFS partitions, extended (MFM) ADFs, a virus signature database, a Raspberry Pi
  package, signed Windows and macOS packages

## Running from source

For developers, or to run the latest code. The packages above are easier.

### Setup on Linux Mint / Ubuntu

Clone or unzip into your home folder, then in a terminal:

```
sudo apt install python3-venv xdms libopenmpt0 libxmp4
python3 -m venv ~/turbocat-env
~/turbocat-env/bin/pip install amitools lhafile
~/turbocat-env/bin/pip install PySide6-Essentials   # for the desktop window
~/turbocat-env/bin/pip install PySide6-Addons       # to play music modules (Qt Multimedia)
cd ~/TurboCAT4
alias tc='~/turbocat-env/bin/python -m turbocat'
```

The PySide6 packages must be the same version (`pip list | grep PySide6`).

**Music playback** needs two things; everything else works without them, and the window says
what is missing when you press play:

- **libopenmpt**, which turns modules into sound. Most Linux desktops already have it (VLC uses
  it); otherwise `sudo apt install libopenmpt0` (`dnf install libopenmpt` on Fedora,
  `pacman -S libopenmpt` on Arch). On Windows put `libopenmpt.dll` from
  [lib.openmpt.org](https://lib.openmpt.org/libopenmpt/download/) in `turbocat/lib/`; on macOS
  `brew install libopenmpt`.
- **libxmp** (optional, `sudo apt install libxmp4`): used for the tunes libopenmpt can't play
  properly, such as OctaMED songs made from synthesised instruments, which otherwise stay silent.
- **Qt Multimedia** (`PySide6-Addons`, above), which plays the sound on Linux (PipeWire,
  PulseAudio or ALSA), Windows and macOS.

### Command line

```
tc scan ~/Amiga            # scan a folder (rescans only what changed)
tc rescan                  # rescan every folder scanned before; drops deleted files
tc search "turrican"       # files, volumes, WHDLoad names, disk text
tc show 12                 # everything about disk #12
tc dups                    # duplicates
tc sets                    # multi-disk sets: missing or mixed-up disks
tc problems                # damaged disks and suspicious bootblocks
tc export disks disks.csv  # numbered disk list (spreadsheet)
tc export csv files.csv    # every file (spreadsheet)
tc window                  # desktop window: the catalogue with search (Ctrl F)
```

Run the commands from inside the `TurboCAT4` folder.

The catalogue is stored in `~/turbocat.db` (change with `--db FILE`).

### Rebuilding TurboView

To rebuild TurboView (the Amiga program; a built copy is included in `turbocat/amiga/`), install
[vbcc](http://www.compilers.de/vbcc.html) (the ready-built Linux package, vbcc_linux_x64.tar.gz, includes the m68k-kick13 target) with the m68k-kick13 target and the
[NDK 3.2](https://aminet.net/package/dev/misc/NDK3.2), then run
`vasmm68k_mot -Fhunk -m68000 -o inflate_glue.o amiga/inflate_glue.asm` and then
`vc +kick13 -O2 -I<NDK>/Include_H -o turbocat/amiga/TurboView amiga/turboview.c inflate_glue.o`.
(`amiga/inflate.asm` is Keir Fraser's 68000 inflate, public domain, from github.com/keirf/amiga-stuff:
it unpacks the packed file list on TurboView floppies.)
