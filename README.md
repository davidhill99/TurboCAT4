# TurboCAT 4 — engine preview (4.0.0-alpha.4)

Author: David Hill

The scanning engine for TurboCAT 4, the modern revival of TurboCAT /
TurboCAT-Pro (1994–1996). Version 4 continues the original numbering: TurboCAT 3 was
on the Amiga Shopper issue 52 coverdisk in August 1995. This preview runs from the terminal, with a first
desktop window (catalogue list, search and details) under way.

## What it reads

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

Archives and images inside other images are opened too (up to 3 levels).

## What's new

See [CHANGELOG.md](CHANGELOG.md) for the changes in each release.

## Checks

- **Damaged disks** — full AmigaDOS filesystem validation; unreadable files reported
- **Bootblocks** — standard / custom loader / non-DOS, and a warning for code that installs itself in memory (the behaviour of bootblock viruses — some virus killers do this too)
- **Duplicates** — the same disk catalogued more than once (any format): one copy is shown, the spares are hidden, nothing is deleted; disks that share an archive are noted too

## Setup on Linux Mint / Ubuntu

Unzip into your home folder, then in a terminal:

```
sudo apt install python3-venv xdms libopenmpt0 libxmp4
python3 -m venv ~/turbocat-env
~/turbocat-env/bin/pip install amitools lhafile
~/turbocat-env/bin/pip install PySide6-Essentials   # for the desktop window
~/turbocat-env/bin/pip install PySide6-Addons       # to play music modules (Qt Multimedia)
cd ~/TurboCAT4
alias tc='~/turbocat-env/bin/python -m turbocat'
```

To rebuild TurboView (the Amiga program; a built copy is included in `turbocat/amiga/`), install
[vbcc](http://phoenix.owl.de/vbcc/) with the m68k-kick13 target and the
[NDK 3.2](https://aminet.net/package/dev/misc/NDK3.2), then run
`vc +kick13 -O2 -I<NDK>/Include_H -o turbocat/amiga/TurboView amiga/turboview.c`.

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

## Use

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

## Roadmap

**Version 1**
- Desktop window
- Watched folders: new, changed and deleted images picked up automatically
- TurboView catalogue file, re-exported automatically to chosen places (Gotek stick, emulator hard-drive folder, Pi SD card) whenever the catalogue changes
- Sync to Gotek stick: copy images to the stick with the catalogue, handling slot numbers
- TurboView for the Amiga: window and Shell versions done; still to come: a start-up freshness check that flags new and missing images, playing modules, and an "I want this" list that TurboCAT copies to the Gotek stick

**Version 1.1**
- TurboView reads new ADFs on the Amiga itself into a top-up file until the next desktop scan

**Ideas being considered**
- *Music Modules disks for the Gotek* (a preference): copying modules, rather than whole disks, adds them to a "Music Modules" ADF on the stick, created if needed, instead of using a whole disk per tune. When it is full TurboCAT offers "Music Modules 2", and so on. Thoughts so far: write OFS/FFS with amitools; Amiga-friendly names ("mod.title", at most 30 characters); skip tunes already on the disk; warn about modules too big for a floppy (offer an HD disk) and formats a stock Amiga can't play easily (XM, IT, S3M); tunes found inside music-disk programs become ordinary modules; possibly a bootable disk with a free module player

- *Disk sets, next steps*: use TOSEC DAT files (TurboCAT can now read them) to recognise sets even when files have been renamed, and group disks without "(Disk N of M)" in their names by volume name and numbering. TurboView could also offer a Utilities choice in its Show menu
- *Module ratings*: The Mod Archive can rate tunes and give their real titles, artists and genres, looked up by checksum, but its API needs a key granted on application (and asks not to be scraped). With a key TurboCAT could add a Rating column and a "hide unrated / low-rated" filter
- *Releases for Windows, macOS and Linux*: packages that include Python, Qt, amitools, lhafile, the music libraries and a DMS unpacker, so only an emulator and Kickstart ROMs need installing (Check setup already explains those). Before a Windows release, support WinUAE, the usual Windows emulator


**Later**
- PFS3/SFS partitions · extended (MFM) ADFs · virus signature database · Windows, Raspberry Pi and Mac packages
