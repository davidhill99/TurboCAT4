# TurboCAT 4 — engine preview (4.0.0-alpha.3)

Author: David Hill

The scanning engine for TurboCAT 4, the modern revival of TurboCAT /
TurboCAT-Pro (1994–1996). Version 4 continues the original numbering: TurboCAT 3 was
on the Amiga Shopper issue 52 coverdisk in August 1995. This preview has no window yet; it runs from the
terminal. The desktop window comes next.

## What it reads

| Format | Notes |
|---|---|
| ADF (DD and HD) | AmigaDOS OFS/FFS disks fully listed; non-DOS game/demo disks identified by bootblock and readable text |
| DMS | Unpacked with `xdms`; fingerprinted as the disk inside, so a DMS and its ADF count as duplicates |
| ADZ | Gzipped ADF |
| HDF | RDB hard drives (all OFS/FFS partitions) and single-partition images. PFS3/SFS partitions are reported but not read yet |
| LHA | Including WHDLoad packs — game name and credits read from the `.slave` |
| LZX | Contents listed (experimental — not yet tested on a real LZX archive) |
| Amiga folders | Folders used as emulator hard drives (detected by `S/Startup-Sequence` etc.) |

Archives and images inside other images are opened too (up to 3 levels).

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
sudo apt install python3-venv xdms
python3 -m venv ~/turbocat-env
~/turbocat-env/bin/pip install amitools lhafile
cd ~/TurboCAT4
alias tc='~/turbocat-env/bin/python -m turbocat'
```

## Use

```
tc scan ~/Amiga            # scan a folder (rescans only what changed)
tc search "turrican"       # files, volumes, WHDLoad names, disk text
tc show 12                 # everything about disk #12
tc dups                    # duplicates
tc sets                    # multi-disk sets: missing or mixed-up disks
tc problems                # damaged disks and suspicious bootblocks
tc export disks disks.csv  # numbered disk list (spreadsheet)
tc export csv files.csv    # every file (spreadsheet)
```

Run the commands from inside the `TurboCAT4` folder.

The catalogue is stored in `~/turbocat.db` (change with `--db FILE`).

## Roadmap

**Version 1**
- Desktop window
- Watched folders: new, changed and deleted images picked up automatically
- TurboView catalogue file, re-exported automatically to chosen places (Gotek stick, emulator hard-drive folder, Pi SD card) whenever the catalogue changes
- Sync to Gotek stick: copy images to the stick with the catalogue, handling slot numbers
- TurboView for the Amiga (68000, 1 MB, Kickstart 2.04+; Shell mode also on 1.3), with a start-up freshness check that flags new and missing images

**Version 1.1**
- TurboView reads new ADFs on the Amiga itself into a top-up file until the next desktop scan

**Later**
- PFS3/SFS partitions · extended (MFM) ADFs · virus signature database · Windows, Raspberry Pi and Mac packages
