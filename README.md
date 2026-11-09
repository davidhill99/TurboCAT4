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

## Changes in 4.0.0-alpha.4

- Desktop window (`tc window`): the catalogue list with search, and a details panel for the selected item — facts, problems and warnings, duplicates (click to jump to the other copy), WHDLoad details, the full contents list or the text found on a non-DOS disk, and Show in folder
- New **Empty** status for 0-byte files and blank (all-zero) disks, instead of Problem or OK. Existing catalogues are updated when opened
- Empty and blank images are no longer reported as duplicates of each other
- **Scan folder…** and **Rescan** buttons in the window (Rescan also on F5 and as `tc rescan`): rescans every folder scanned before, reading only new and changed files and removing items whose files were deleted. Runs in the background with a Stop button
- Scans show a progress bar: how many new or changed files are left, the time remaining, and the file being read. Unchanged files are skipped without being read, so a rescan with nothing new is almost instant
- Filter chips above the list: All items, Problems, Warnings, Duplicates, WHDLoad games, Non-DOS disks, Hard drives and Empty, with counts that follow the search
- Long titles and facts in the details panel are no longer cut off
- **Copy to Gotek stick** (header button, details panel or Ctrl+G): copies the selected disks to a USB stick or any folder as plain ADF files, unpacked from ZIP, LHA, DMS or ADZ. Names them for FlashFloppy, or DSKA0000.ADF style for stock Gotek / HxC firmware. Hard drives, WHDLoad games, blank disks and IPF images are left out with the reason. Select several items with Ctrl or Shift
- **Pictures:** each disk's own Workbench icon is shown in the list, and the best picture on the disk (a title screen where there is one) at the top of the details panel. Classic, Workbench 1.3 and GlowIcon icons and IFF ILBM/PBM pictures (including HAM and EHB) are decoded. Found in the background when the window opens and after each scan; kept in ~/.cache/turbocat/pictures
- **Find pictures online:** for disks with no picture of their own, a title screen is fetched from the libretro-thumbnails collection (as used by RetroArch) when the title matches exactly. These belong to the games' publishers and are kept locally for personal use; asked once before the first lookup
- List columns can be resized by dragging the dividers in the header (double-click one to fit the column); the widths are remembered
- **Games** filter chip: shows only game disks. An item counts as a game when it has a WHDLoad slave, its name or folder says game ("PD Games Volume", "(Game)", "(demo-playable)"), it has a trainer, its TOSEC name has a games publisher, its title is in the libretro game list, or (not for PD disks) it boots its own loader; the other disks of a set follow. Utilities, music, coverdisks and demos are not counted on the weaker signs. The details panel says why each one counts
- Games show their picture (title screen) in the list; other items show their own Workbench icon. Score tables and strips of graphics are no longer picked as a disk's picture, and a game with no picture offers a Find pictures online link
- **Music** filter chip and player: music modules on disks and in archives are recognised by their contents (ProTracker and relatives, OctaMED, FastTracker 2, Scream Tracker 3, Impulse Tracker, Oktalyzer; AHX listed but not played), including ProTracker modules built into music-disk programs. The details panel lists an item's tunes; double-click one to play it. A player bar (pause, next, stop) keeps playing while you browse. Sound is rendered by libopenmpt with Amiga-style filtering and played through Qt Multimedia, so it works on Linux, Windows and macOS (see Setup)
- **Tunes list:** with the Music chip selected, switch from Disks to Tunes for one row per module: name, format, size, length, item number and where it is. Sort by any column, search, double-click to play (playback carries on down the list as sorted), and Export list… saves it as a spreadsheet. Lengths are measured in the background once
- OctaMED tunes made from synthesised instruments (e.g. on MED v3.22's demo songs) now play: libxmp takes over whenever libopenmpt reports it can't play a tune properly
- Music modules lying loose in a scanned folder (.mod, .xm, .s3m, .it, MED, Oktalyzer, AHX) are now catalogued, one item per tune, recognised by their contents rather than their names; tunes up to 32 MB are found (was 4 MB). Double-clicking one (or Ctrl+P) plays it in TurboCAT's player rather than starting an emulator
- **Safety copies of the catalogue:** each time the window opens, TurboCAT checks the catalogue and, if it is healthy, keeps a copy in a folder beside it (turbocat.db → turbocat-backups/, at most one new copy an hour, the newest 5 kept). If the catalogue is ever damaged, TurboCAT says so on start and offers to put the newest copy back; the damaged file is kept beside it, renamed
- Searching matches each word on its own, and spaces, underscores and dashes all count as gaps between words: "space debris" finds space_debris.mod, "lemmings 2" finds Lemmings_2_The_Tribes. Tune titles are searched too ("stardust memories" finds stardstm.mod)
- **Menu bar:** File (Scan folder… Ctrl+O, Rescan F5, Export tune list…, Quit Ctrl+Q), Disk (Play Ctrl+P — "Play tune" for a music module, "Play in emulator" for a disk —, Copy to Gotek stick… Ctrl+G, Show in folder Ctrl+Shift+O), Tools (Find pictures online, Start TurboView) and Help (About, TurboCAT 4 on GitHub). The header buttons stay as shortcuts to the most used commands
- **About box** (Help → About TurboCAT 4, or F1): the version, the catalogue in use (its file, items and size), its safety copies with a button to show them, and what TurboCAT is built on (Python, Qt, amitools, libopenmpt and libxmp, with their versions or how to install the missing ones)
- **Progress for picture searches:** Find pictures online now shows the progress bar under the search box: a moving bar while the list of pictures is fetched from GitHub, then "Looking for pictures online… 7 of 383" with the disk being looked up, and a Stop button. It ends with what was found, e.g. "17 pictures found online for 371 disks looked up". Bigger searches of your own disks after a scan use the same bar; small ones stay in the footer
- **Play in emulator** (double-click an item, Ctrl+P, or the button in the details panel): starts the disk in Amiberry or FS-UAE. One disk of a set brings the whole set (Disk 1 in DF0:, Disk 2 in DF1:, all in the disk swapper); an A1200 is suggested for AGA titles, an A600 for ECS, otherwise an A500; Kickstart ROMs are found by their contents (Amiga Forever ROMs with rom.key work); IPF originals inside ZIPs are unpacked for the emulator; WHDLoad archives go to Amiberry's WHDLoad booter
- **TurboView**, the Amiga side: a Workbench window on Kickstart 2.04 and later (search as you type; Show: all, games, music, problems, duplicates; In: titles, files or tunes; the selected disk's details, contents and music; Boot it / Into DF0: / Into DF1: / Drives buttons, Boot only for disks that start by themselves), and a Shell version on Kickstart 1.3 or with the SHELL option. TurboCAT keeps a catalogue for it in `~/Amiberry/HardDrives/TurboCAT` (written after each look through the disks), and the **TurboView** button starts an emulated A1200 that boots from that folder as `TurboCAT:` with the collection folders mounted read-only. Search titles, files and tunes, see a disk's contents, music and where it is (PC path and Amiga path), and in Amiberry `insert 9` / `boot 9` put a disk in a drive or restart into it (`drives` shows what is in each). Runs on Kickstart 1.3 and later
- ZIP archives are read (TOSEC packs each disk in a .zip); an archive holding a single disk is listed as that disk
- Overdumped ADFs (TOSEC "[o]", extra tracks past the end of the disk) are read normally with a note, instead of being reported as a problem and mis-read as high density

## Changes in 4.0.0-alpha.3

- Renamed from TurboCAT 2026 to TurboCAT 4; the command is now `python -m turbocat` and the default catalogue `~/turbocat.db`

## Changes in 0.1.2

- New `sets` command: recognises multi-disk sets from collector file names such as "(Disk 2 of 4)" and reports missing disks and mixed-up disk counts
- `dups` no longer lists files that a game repeats across its own disks, and groups common system files (libraries, fonts) into one line

## Changes in 0.1.1

- Filesystem quirks on disks whose files all read (stale free-space maps on game disks) are now notes or warnings, not problems
- Truncated images say how many tracks are missing and still list the files that survive
- A DOS header with no readable filesystem is reported as a custom-format data disk (warning)
- The word "virus" in a bootblock is only a note unless the code behaves like a virus
- A mistyped folder gives a plain message instead of an error dump

## Checks

- **Damaged disks** — full AmigaDOS filesystem validation; unreadable files reported
- **Bootblocks** — standard / custom loader / non-DOS, and a warning for code that installs itself in memory (the behaviour of bootblock viruses — some virus killers do this too)
- **Duplicates** — identical images and archives (any format), plus files stored on more than one disk

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

- *Group disk sets*: a Group button shows each multi-disk game as one row (the lead disk, with the game's picture), expandable to its disks. Sets with missing or damaged disks, or disks from different releases mixed together (e.g. [cr FLT] and [cr CSL] cracks, which often don't work together), are flagged. A Clean up list names the replacement disks needed to complete each set, noting where a good copy is already elsewhere in the catalogue; it can be exported. Thoughts so far: TOSEC names give "Disk N of M", so missing disks are known exactly; other names fall back on volume names and numbering; optionally check sets against TOSEC DAT files for certainty


**Later**
- PFS3/SFS partitions · extended (MFM) ADFs · virus signature database · Windows, Raspberry Pi and Mac packages
