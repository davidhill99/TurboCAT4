# TurboCAT 4 — Changelog

Author: David Hill

What changed in each release, newest first. Work not yet in a numbered release is under
**Unreleased**.

## Unreleased (for the next beta)

- **Fixed: links in the details couldn't be clicked** (such as where a picture came from): the
  text could be selected, but the links didn't open
- **New: find out about your games** (Tools › Find out about games online…, or the link under a
  game's details). TurboCAT matches your disks by name to Wikidata's list of about 2,000 Amiga games
  and programs, and the details then show *About this game*: a few lines from Wikipedia, its genre,
  who made and published it, when it first came out, how many can play, and links to Hall of Light,
  Lemon Amiga, MobyGames and Wikipedia. On a 78,000-item collection 17,000 disks (1,471 different
  titles) were recognised. Asks first; the list is fetched once and then every two months, and the
  Wikipedia lines one title at a time, a second apart. After that, new disks are looked up after
  each scan
- **Background work no longer slows TurboCAT down.** The picture search and the game look-up
  each run in a process of their own, side by side, at the lowest priority for the processor and
  the disk. (In a thread of the window's own process they still slowed it down: Python runs one
  thread at a time, so the window waited its turn.) They wait while you are clicking, typing or
  scrolling, and go on a moment after you stop. Measured on a 78,000-item collection, the window
  now answers within 22 ms 99% of the time while the search runs; showing newly found pictures
  every 8 seconds now reads only the new ones (reading them all held the window up for 0.4 s).
  Game details have their own place in the status bar, beside the picture search, and show in the
  details as soon as each is found. The status bar still shows what it is doing and how far it has
  got. When it finished, it used to read the whole list again in the window itself, which froze the
  window for about 40 seconds on a big collection: the list is now read in the background, too. A
  new index makes finding what is inside each archive quick (looking up pictures online read every
  disk in the catalogue once per item)
- **Fixed: TurboCAT stopped with an error during a long scan**
  ([issue #1](https://github.com/davidhill99/TurboCAT4/issues/1)). While a scan runs, the list
  reloads every few seconds; if the scan added a damaged disk in the moment between two steps of
  working out which disks can be repaired, it stopped with a KeyError. Such a disk now waits for the
  next reload a few seconds later. A test recreates the timing
- **Fixed: "TurboCAT 4 is not responding" during a big scan.** While a scan runs, the list
  showed new items by reading the whole catalogue every 4 seconds in the window itself; once the
  catalogue was big (8,800 items during a 74,000-file TOSEC scan) that took longer than 4 seconds,
  so the window never got a moment to respond. It is now read in the background, the window only
  shows the result (a quarter of a second instead of five), and the next reload waits twice as long
  as the last one took
- **Fixed: TurboCAT ran out of memory on a very big collection** (and was closed by the system,
  while looking for pictures after a 78,000-item scan). Working out which damaged disks can be
  repaired listed every copy of each lost file found elsewhere; common files such as
  devs/system-configuration are on 35,000 TOSEC disks, so 4,000 damaged disks made 2.5 million
  entries and over a gigabyte, rebuilt on every reload. Every copy is still counted, but only a
  few copies of the version that would be used are kept, and each file is looked up once however
  many disks lost it: about 1.3 GB less memory, and less than half the time
- **TurboCAT says it is starting on a big catalogue.** Before the window opens, TurboCAT checks the
  catalogue file for damage, which reads all of it: with an 850 MB catalogue that took 45 seconds
  with nothing on screen, so it looked as if it wouldn't start. A small window now says it is
  checking the catalogue (and how big it is) whenever the check takes more than a moment
- **Fixed: closing took over a minute on a big catalogue** when the picture search or a scan was
  running. They stopped quickly, but then the whole list was read again (in the window itself)
  before it closed. Closing now skips that
- **Opening a big catalogue is almost three times quicker**: reading 78,000 items took 106
  seconds, now 38. Choosing a title from the text on disks without a name checked the same words
  millions of times (now remembered); working out which damaged disks can be repaired now sums up
  each lost file's copies once, and a new index finds files by name and size together (built once,
  in a few seconds, while TurboCAT says it is checking the catalogue)
- **Opening a big catalogue shows how it is getting on**: instead of just "Opening the
  catalogue…", TurboCAT says how many items it is opening and that a large collection takes a
  while (and how long it took last time), and shows a progress bar, the step it is on and about
  how many seconds are left
- **The picture comes first in the details panel**, above the name and buttons, so it is seen
  without scrolling
- **The Big archives window says where each archive is**: under each name, the folder it is in
  (~/Dropbox/AMIGA), so one in a folder you meant to leave out is easy to spot and untick

## 4.0.0-beta.1 — first public test release (14 November 2026)

- **A welcome on the first start**: an empty catalogue shows "Welcome to TurboCAT 4" with one
  button, Choose your Amiga folder…, instead of an empty list. The setup report no longer opens over
  it: if something important is missing it comes once after the first scan, when there are disks it
  matters for (the Setup button shows the warning sign meanwhile). During that first scan the list
  says the disks are being read. TurboView's folder (~/TurboCAT-Amiga) is made only once something is
  catalogued, not the moment TurboCAT first opens
- **A README for users**: the README now starts with what TurboCAT 4 does, TurboView, and the
  downloads; running from source, the command line and rebuilding TurboView follow at the end
- **Auf Deutsch**: a German README (LIESMICH.md, linked at the top of the README) and German lines in
  the Aminet readme. The README has a short history: the Amiga Shopper coverdisk (1995) and reviews
  (85% and a 90% Star Buy, 1996), linked to the scans on the Internet Archive
- **Support TurboCAT**: TurboCAT stays free; Help › Support TurboCAT 4… and a line in the About box
  open its Ko-fi page (ko-fi.com/tcpturbocat) in your browser. It is also in the README, the
  Aminet readme and GitHub's Sponsor button, and Help › Privacy says it sends nothing
- **DMS disks work in the Windows and macOS packages too**: xdms 1.3.2 (public domain) is compiled
  from its official source in each build (checked by its SHA-256) and carried inside, so every package
  now reads LHA, DMS and music without installing anything. A new test packs a disk as a genuine DMS
  and checks it unpacks exactly, on every system, with the copy that ships
- **Ready-to-run packages, built by GitHub**: a Windows installer (per user, no admin) and portable
  zip, macOS .dmg files for Apple Silicon and Intel Macs, and a Linux AppImage, each with Python, Qt, 7-Zip and libopenmpt
  inside (and xdms on Linux). Built on demand or when a version is tagged (then attached to a draft
  release). Unsigned for now
- **Getting ready for Windows and macOS** (not yet released for them): TurboCAT's files go in each
  system's normal place (Linux keeps its folders); it finds WinUAE (also Amiga Forever's) and FS-UAE
  on Windows, and the Amiberry and FS-UAE apps on macOS, and starts WinUAE with a settings file; Gotek
  sticks are found from the system's drive list (drive letters, /Volumes); helper programs don't flash
  a console window on Windows; emulators keep running after TurboCAT closes; folder names ignore case
  on Windows. Tests run on Linux, Windows and macOS on every push
- **TurboView on a real Amiga fits the screen**: its explanation scrolls and its result line and
  buttons stay at the bottom, instead of the window growing taller than a 900-pixel screen
- **TurboView's icons are Workbench 2 icons**: marked revision 1 (as 2.04 and 3.1 make them), so
  TurboCAT draws a scanned TurboView disk as a Workbench 2 window (grey, with the cat in blue), not
  in 1.3 colours. Disk and drawer icons carry Workbench 2's view settings; Workbench 1.3 still reads them
- **A copier screen when TurboCAT writes disks**: the TurboView disks, Copy to Gotek stick (one disk
  or a batch) and repaired/tidied copies (including Fix all) now show each disk filling in, cylinder
  by cylinder (side 0 above side 1), coloured by what is really on each track (files, headers,
  folders, the disk's index, empty, blank, bad, not DOS), with the drive's step clicks, seeks and
  motor hum (made by TurboCAT, no recordings). Sound on/off and Fast (skips the picture) are
  remembered; Stop stops the writing. It never slows the writing: disks are handed over as they are
  written, and it speeds up when they come faster than it draws them
- **Help › How TurboView went on your Amiga…** (and a button in TurboView on a real Amiga): a short
  form for testers. The hard-drive install is marked experimental: meant for an A1200 or any Amiga
  with Kickstart 2.04+; a 1.3 A500 gets the Shell version and the install there is untested
- **Updating TurboView after the next scan is one click** (TurboView 4.0 alpha 6): an installed
  TurboView notices newer TurboView disks in a drive (at start, or when a disk goes in) and offers
  "Update now?"; the Shell version says so and takes `update`. Fixes to the install, which an update
  re-runs: the new list of files is always unpacked (before, a second install kept the old one), the
  icon's tooltypes and position are kept, a copy of TurboView in WBStartup is updated too, and an old
  search index is removed if disk 2 isn't there. On a Gotek with numbered images, new TurboView disks
  replace the old ones' slots instead of taking new numbers
- **TurboView is a Workbench tool again, like the original** (TurboView 4.0 alpha 5): the floppies
  have Workbench icons (disk, TurboView, ReadMe), so with Workbench running you can insert one and
  double-click TurboView to keep it open beside your work; it reads its icon's tooltypes
  (CATALOGUE=, SCREEN=, FAVOURITES), and otherwise the drawer it is in; problems show in a
  requester. A zoom gadget shrinks its window to the title bar. INSTALL gives the hard drive a
  drawer icon and a TurboView icon with CATALOGUE= set, ready to drag into WBStartup
- **Two TurboView floppies, and a hard-drive install from them** (TurboView 4.0 alpha 4). Disk 1
  ("TurboView") has your disks and what is on each; disk 2 ("TurboView2") has a name index
  (TurboCAT.nix: every file and folder name once, with its disks), so searching every file name
  unpacks a third as much: about 1½ minutes on an A500 at real floppy speed instead of ~4¾. Each disk
  works alone; with both in two drives TurboView uses each for what it does best, without
  "insert disk" requesters. `TurboView:TurboView INSTALL DH0:TurboCAT` copies both disks to a hard
  drive and unpacks the full list there (searches and contents then quick). Tools › TurboView on a
  real Amiga makes both disks (or copies both to the Gotek stick) and explains the install.
  **Not yet tried on a real Amiga**: docs/testing-turboview-on-a-real-amiga.md is the tester checklist
- **TurboView's file search on a floppy stops once its list is full** (300 in the window, 20 in the
  Shell) and says there are more on later disks, instead of unpacking everything to count them:
  common names (startup-sequence) now take seconds rather than minutes on an A500. One disk with a
  huge file list can no longer stop the packed list opening (each disk is capped at 64 KB, with a note)
- **The TurboView floppy carries the list of every file, packed** (TurboCAT.fz, standard deflate in
  32 KB blocks, ~4.1 MB -> ~520 KB) when it won't fit as it is, so TurboView on a real Amiga shows
  each disk's contents (one block unpacked: seconds). Searching every file name from the floppy is
  slow (minutes on an A500 or A1200), so it shows how far it has got and stops on a click, a key or
  Ctrl-C. TurboView 4.0 alpha 3 also hides the "PC:" line when there's no computer path. TurboView
  unpacks with Keir Fraser's 68000 inflate in assembly (amiga/inflate.asm, public domain): a full
  file-name search from the floppy takes about 2½ minutes of unpacking on an A500 (about 4¾ with a
  real-speed drive), three times faster than portable C
- **TurboView's file list leaves out looping-directory junk**: a damaged disk whose directory loops
  back on itself made the scan record nonsense paths hundreds of folders deep (one disk added 1.2 MB).
  Paths over 16 folders deep or 255 characters are left out, with one line saying how many
- **The TurboView floppy is much smaller and carries no personal paths**: its main list drops the
  computer's own paths (meaningless on a real Amiga), so it shrinks by two thirds (about 500 KB to
  217 KB on a 1,700-item collection), leaving room for more
- **Tools › TurboView on a real Amiga…**: explains the two ways to get TurboView onto a real Amiga
  and makes what each needs. (1) A TurboView floppy, TurboView.adf, that starts TurboView by itself
  on any Amiga (Kickstart 1.3 or later), saved anywhere or copied straight to the Gotek stick (as
  DSKAnnnn.ADF on a numbered stick); the list of every file goes on only if it fits. (2) The full
  files for a hard drive, with how to get them across (FAT card with fat95, network, or the floppy)
  and how to start it. Booted in FS-UAE as an A1200 (window) and an A500 with 1.3 (Shell)
- **TurboView is explained as running on a real Amiga too**, not only in an emulator: the toolbar
  button, the Tools menu, Check setup and the README say it lists and searches your collection on
  an Amiga (to find which disk or Gotek image holds what), and how to copy it to a real one. Without
  an emulator, Check setup now shows TurboView as working on a real Amiga instead of missing
- **Privacy statement**: Help › Privacy, a Privacy link in the feedback forms, and PRIVACY.md (linked
  from the README). It says what TurboCAT contacts online and what it sends (only when you use those
  features), what it never does, and what it keeps on your computer. All three come from one text
  (privacy.py); a test fails if PRIVACY.md falls out of step, or if the code contacts a site the
  statement doesn't name
- **The suggestion box is easy to find**: a "Got an idea?" link always in the status bar, a
  "Suggest an idea…" button in About, and one reminder (only ever one) after the tenth start: a
  small note above the link, shown when nothing else is open and TurboCAT isn't busy
- **Error reports' kill switch**: the error box has "Don't show these again", and Help › Show error
  reports turns them off or on. TurboCAT also pauses them by itself for the rest of the session when
  they come too often (3 boxes, or 20 errors, in 10 minutes). When they are switched off after real
  errors, it offers once to report why: how many errors, which kinds, how often and where in the
  code. Nothing is sent unless the tester chooses to
- **Help › Report a problem… / Suggest an idea…**: a short form whose report opens as a new GitHub
  issue with the technical details filled in (TurboCAT, Python and Qt versions, the system, what
  Check setup found, the catalogue's size). The exact text is shown first; the home folder and user
  name are taken out; no file lists or catalogue are sent. Copy details is for anyone without a
  GitHub account. Issue forms for both are in .github/ISSUE_TEMPLATE
- **Crash catcher**: an unexpected error now shows "TurboCAT hit a problem" (once per kind of
  error) with Report it…, Copy details and Carry on, instead of only printing to the console
- **Rename files to their proper names** no longer offers the same renames every time: a spare
  copy of a disk whose properly named file is already in the folder is left as it is (and said so),
  instead of failing quietly on each run. ROMs no longer get ".rom.rom"; ROMs already renamed that
  way are offered the single ".rom"
- **Tools › Look on Aminet for missing files…**: damaged files that none of your disks have are
  looked for on Aminet (freely distributable software only, Fred Fish disks included). Only a file
  with exactly the same name and size is downloaded, and only that file is kept
  (~/.cache/turbocat/aminet); each name is looked up once. Commodore's own files and names too
  plain to search for ("1", "d") are never looked for. Fix all then uses what was found; repaired
  copies say "from Aminet <package>" in their note and in repairs.csv
- The window can be maximised again after a scan: the result message in the progress bar wraps
  onto more lines, and the "Inside archive…" line shortens with …, rather than making the window
  wider than the screen (which made the desktop drop the maximise button)
- TurboView in FS-UAE shows its whole screen: FS-UAE cut off part of TurboView's 1280x512
  super-hires screen, so in FS-UAE TurboView now opens a 640x512 one (Amiberry keeps the sharper
  super-hires screen)

- Disk map: the details panel shows every block of a floppy as X-Copy did, 80 cylinders across with
  side 0 above side 1: boot, root, bitmap, folders, file headers and lists, file data, blocks in a
  damaged file, bad blocks (checksum wrong), free and blank blocks, or a non-DOS disk's own data.
  Hover over a square for its cylinder, side, sector and the file it belongs to
- Tools › Collection stats…: a league table of the groups that cracked, trained, fixed and hacked
  your disks (TOSEC's short names such as SR and FLT shown in full), your publishers, and a chart of
  disks by year. Double-click a group or publisher to find its disks

- Disks whose files all read but whose index (directory) has errors say so plainly ("The disk's
  index has 2 small errors — every file still reads"), with the technical findings on hover, and
  offer "Make a tidied copy…": the same files in a fresh disk with a correct index, checked file by
  file, saved in ~/TurboCAT/Repaired as [f TurboCAT] and logged; the original isn't changed. A name
  a broken index lists twice is kept once (or, if the two differ, the second as name.2)

- Hover notes are easier to read: black on pale yellow with a thin black border whatever the desktop
  theme, and long ones wrapped into a squarer box instead of one very wide line

- Fixed: the panel lost TurboCAT's icon (showing a plain gear) once a tune started playing. TurboCAT
  now runs as "turbocat4", so its windows' class matches its launcher (turbocat4.desktop), and its
  icon is set for every window it opens

- OctaMED songs with synthesised or hybrid instruments play properly: TurboCAT uses its own copy of
  libopenmpt (0.8 or later, in turbocat/lib) before the system's. The libopenmpt 0.7 that Linux Mint
  22 has left those instruments silent; libxmp stays as the fallback

- Setup window: hovering over any feature or part explains what it does, what to do to get it
  working, and where its files go (for Kickstart ROMs, the folders TurboCAT looks in, and where it
  found yours)
- A small round "i" now shows beside anything with a hover note (the details panel's notes and
  facts, the Setup rows, the item count, the scan bar, the version in the status line), so it's
  clear there's more to read. Buttons and menus keep their usual hover text without one

- `dups`: standard AmigaDOS / Workbench commands (Assign, SetPatch, IconX, Execute and the other
  Workbench 1.3–3.x C: commands) count as common system files wherever they are on a disk, not
  only inside `C/`, so copies that games keep in their own root or drawers are grouped with the
  other system files instead of listed as duplicates
- Old LHA archives packed with the 1990–91 `-lh1-` method need `lha` (from the `lhasa` package):
  7-Zip can't open them, so Help › Check setup no longer counts 7-Zip alone as enough
- Details: an item that couldn't be read for want of a helper program (lha, xdms) gets a
  **Can be fixed on this computer** note saying what to install; once it is installed, the note
  becomes **Can be fixed now** and points to Disk › Recheck
- New **Can be fixed** filter chip lists those items (it only appears when there are some), and
  says what to install for the rest; **Fix them now** reads again every one that can be fixed
  with what is installed already
- **You have a good copy** (repair R2): a damaged disk with another version that reads fully says
  so in Details, with a link to that version and what its TOSEC tags mean, and is no longer counted
  under Problems. A version TOSEC tags as a bad dump `[b]` never counts as a good copy, even if it
  reads. The Problems line says how many damaged disks were left out for this reason
- Problems in plain English: Details says e.g. **1 of 220 files damaged — the other 219 read
  fine** and names the files; TurboCAT's technical findings are on hover. The list's Problem badge
  says the same on hover
- A damaged disk with no good copy says whether your collection can help: **Could be rebuilt** /
  **Partly rebuildable** (its damaged files are on your other disks, and which), or **Can't be
  fixed from your collection**, with the reason on hover (e.g. the other version is a bad dump too)
- A damaged disk that matches a collection list exactly no longer says "Verified … undamaged":
  it says the damage was already in the collection's copy. A version with no readable files is
  never taken as a good copy
- **Make repaired copy…** (repair R4): on a damaged floppy whose damaged files are on your other
  disks, a button in Details (and Disk › Make repaired copy…) shows what TurboCAT would do — each
  file, the disk it comes from and how sure the match is — and asks first. It then writes a **new**
  disk image to `~/TurboCAT/Repaired` and adds it to the catalogue; the original is only read.
  The copy is rebuilt file by file, checked (no filesystem errors, every file as planned) and marked
  as not original: `[f TurboCAT]` in its name, a `Repaired-by-TurboCAT` note on the disk and a file
  note on each restored file (can be turned off), and a log (`~/.local/share/turbocat/repairs.csv`)
  so TurboCAT recognises it even if renamed. A boot block that looks like a virus is replaced with
  the standard one. Repaired copies get a **Repaired copies** chip and say so in Details; the damaged
  original points to its repaired copy, and a disk set counts it, so a set can become complete
- The list says how each damaged disk can be fixed, next to its Problem badge: **Can be rebuilt**,
  **Partly rebuildable**, **Can be fixed now** / **Fix: install …**, **Partly repaired** or
  **Repaired copy** (hover for details). The **Can be fixed** chip now covers rebuildable disks too
- **Fix all…** on the Can be fixed chip: one window lists every disk TurboCAT can fix, complete
  rebuilds ticked and partial ones unticked (hover a disk for each file and where it comes from),
  says what it will do and roughly how long, and asks first. The repairs run with a progress
  window and time left; Stop keeps the copies already made. A summary says what was made
- A replacement file that can't be read from one disk is taken from another identical copy;
  overdumped source disks are read at their normal size, and files are taken from archives
  sitting on disk images (e.g. ZIP › ADF › LHA). A damaged disk is linked to its repaired
  copy through TurboCAT's repair log, so it works even when the names differ
- After a partial repair TurboCAT says what's still missing and how to finish the job: the Fix all
  summary lists each disk's missing files (with **Save list of missing files…** for a spreadsheet),
  the repaired copy says **Still missing …**, and the original says **Partly repaired** with a link to
  its copy; hover for how to fix it fully (get a good copy, or add disks that have the files). When
  a later scan finds every missing file, the original says **Can be fully rebuilt now** and goes
  back under Can be fixed
- Fix all no longer leaves partial rebuilds unticked when they are all that is left
- An empty file (0 bytes) of a disk you have a working copy of — the same coverdisk (magazine,
  issue and disk), or another version of the same disk — says **Empty file, but you have a working
  copy**, with a link to it, and is left out of the Empty list, which now shows only what is really
  missing. The Empty line says how many were left out
- Damaged files whose names end in a space are recognised; a file that turns out unreadable while
  copying is left out and listed as missing instead of stopping that disk's repair
- When a helper program (lha, 7-Zip, xdms) is installed after a scan, the next scan or Rescan reads
  again, once, the items that couldn't be read without it, even though their files haven't changed.
  Before, they stayed "unreadable" until rechecked by hand

- **Setup button** on the toolbar, with a green, amber or red mark: hover for what isn't working,
  click for Check setup. Check setup now starts with **What works** on this computer, feature by
  feature (reading disks, LHA, DMS, music, playing disks, TurboView, Gotek, repair, proper names),
  in terms of your collection — e.g. a missing xdms only matters if you have DMS images, and
  missing Kickstarts say how many AGA and ECS disks need them (hover for more). The parts list
  follows, with how to get each missing one
- Kickstart ROMs: every ROM found is listed, AROS is called what it is (a free replacement, not a
  real Kickstart), and TurboCAT also looks where Windows (Amiga Forever's `Amiga Files/Shared/rom`)
  and macOS (Amiberry's folders) keep them
- Helper programs (lha, xdms, 7z) are looked for in a `bin` folder that comes with TurboCAT before
  the system's, so the Windows and macOS packages can include their own copies
- File > Scan folders… shows your folders as a tree with tick boxes, like a cloud drive's
  selective sync: ticked folders are scanned with everything inside them, unticked ones are left
  out, and a half tick means some folders inside are left out (a folder inside an unticked one can
  still be ticked). Each folder shows how many catalogue items came from it. On Save, if unticked
  folders hold catalogued items, TurboCAT asks whether to keep them or take them out; files on disk
  are never touched. Drives and network shares that are plugged in are listed too
- Files that aren't Amiga are left out of the catalogue: Word, Excel and LibreOffice documents (they
  are zips inside), e-books, Java programs, and zips holding only PC documents, pictures, chats or
  other computers' games (a Game Boy ROM). Amiga zips with no disk image inside (demo programs, IPF
  disks, firmware ROMs) stay. Ones catalogued before go on the next Rescan, and the scan says how
  many were left out
- A music module or ROM on its own is no longer counted as a game because of its name
- The list is easier to read: each disk's title is shown on its own, with its year, publisher,
  country and TOSEC tags in plain words on the line underneath ("cracked by Fairlight", "bad dump
  (damaged)"), and disk numbers kept with the title ("Dune · Disk 2 of 3"). The full file name is
  on hover. The name column takes up the spare width when the window changes size (dragging any divider is smooth: Status, the last column, takes up the difference), the Status column is only as wide as its
  labels, column headings are no longer cut off, and the green OK label is gone: only disks that
  need attention have a label
- The details panel puts what matters first: the disk's proper name (with its year, publisher and
  tags in plain words), then the buttons (Play, Gotek, Show in folder), the picture, then what's
  wrong and what can be done about it, then other notes, the facts and the contents. Facts that
  don't apply are left out instead of showing "—", and the disk's own volume name is shown only
  when it says something different. The versions and "identified" notes are shorter, with the
  technical detail (how versions differ, the full TOSEC name) on hover
- The filter buttons are in two labelled rows: SHOW (All items, Favourites, Games, Music, Utilities,
  Coverdisks…) and NEEDS ATTENTION (Problems, Can be fixed, Warnings, Sets to complete, Duplicates,
  Empty, Repaired copies). Non-DOS disks and Hard drives are under More, which shows the one chosen.
  The Needs attention row goes when nothing needs attention
- In a narrow window the name column keeps its room: Volume / Title gives way first, and comes back
  when the window is wider
- The counts agree: the heading shows the same number of items as All items, and every "of N
  items" line uses it too. Hover over the heading for what isn't counted (spare copies, grouped
  versions, empty files). The All items line counts empty files the same way as the Empty chip,
  and says separately how many more are empty but have a working copy. The status bar no longer
  has its own, different, problem counts
- The toolbar has what you do most: Play (Ctrl+P) first, which says "Play tune" for tunes and is
  greyed out when what is selected can't be played; Copy to Gotek stick; a Scan menu (Rescan all
  folders F5, Add a folder… Ctrl+O, Choose scan folders…); TurboView; Setup. Find pictures online
  has moved to the Tools menu (it runs by itself after a scan anyway). The toolbar now fits in a
  narrower window
- An archive holding several disks of one game (Walker's zip, with disks A, B and C) is named for
  the whole game, not for its first disk, so it no longer shows as a set with disks missing. If it
  holds only some of the disks, its name says which ("Disks 1, 2 of 3"). On David's catalogue this
  fixed 23 games wrongly shown as missing disks (Lemmings, Monkey Island, The Settlers, Flashback,
  Ambermoon…). When one of an archive's disks also matches another release of the game (Pinball
  Fantasies' disk 1 is the same as the four-disk release's), the number of disks most of them agree
  on wins
- Work TurboCAT does by itself (looking for pictures after a scan) shows as a slim bar with Stop in
  the status line, instead of a full-width bar above the list; scans, and searches you ask for,
  still get the big bar. The status line shows TurboCAT's version, with the catalogue file on hover
  (Help › About has it too)
- "Group sets and versions" is a tick box, so it's clear whether it's on
- Finding pictures online matches more names: when the exact name isn't in the picture list,
  TurboCAT tries again ignoring small words, version numbers and edition words ("Dune II - The
  Battle for Arrakis" finds "Dune II - Battle for Arrakis"; "Aladdin - HD Installer", "Epic -
  Trainer +5" and "Chambers of Shaolin CD32" find their games). Disks not found before are tried
  again once. Tunes and ROMs on their own are no longer looked up as games
- Disks with no picture of their own and none online get one drawn from the disk: its Workbench
  window, with the disk's own icons where the disk puts them, in the colours of the Workbench they
  were drawn for; or, for a disk with no icons, an AmigaDOS Shell window listing it. A title screen
  found later always takes their place. Games still without a picture show a generic Game picture,
  and utilities with nothing to draw a generic picture for their kind (disk tools, virus killers,
  music tools, graphics, programming, packers, system, office). On David's catalogue: 1,276 more
  utility disks with a picture
- Fixed: a scan stopped with "'utf-8' codec can't encode character … surrogates not allowed" when
  an old LHA archive, unpacked with the lha program, held an Amiga file named in Latin-1 (such as
  "Français"). Those names are now read as Latin-1, any name that still isn't valid text is cleaned
  before it's stored, and one file that can't be catalogued no longer stops the scan: it's skipped
  and named in the scan's result
- Faster: the window opens at once ("Opening the catalogue…") and reads the catalogue in the
  background; reloads take about a third of the time (results that don't change between reloads,
  such as tidied names, coverdisk matching, repair plans and collection lists, are remembered until
  something changes); and while pictures are being found, the list shows them in place instead of
  rebuilding everything every 8 seconds, which used to freeze the window
- Play puts a set of up to four disks in DF0: to DF3: (an Amiga's four drives), so a game asking for
  disk 3 finds it, as Worms - The Director's Cut does. Before, only the first two disks were in
  drives and the rest only in the emulator's disk swapper. Sets of more than four are in the swapper
  too
- Play's A1200 has 8 MB of Fast RAM, as most A1200s had with a trapdoor expansion: some AGA games
  crash with a "Software Failure" on a plain 2 MB A1200 (Worms - The Director's Cut)
- Play never hands an emulator an original disk image: a plain ADF is copied to TurboCAT's play
  folder first, so a game that saves to its disk (high scores, settings) changes the copy, which is
  kept for next time. FS-UAE keeps its own files (save states, disk overlays) in TurboCAT's folder
  (~/.local/share/turbocat/fs-uae) instead of ~/Documents/FS-UAE

## 4.0.0-alpha.4 — 8–10 Nov 2026

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
- **Duplicates are hidden, never deleted:** when the same disk is catalogued more than once (the same bytes, or the same disk as an ADF, in a ZIP or as a DMS), TurboCAT shows one copy and hides the others as spare copies; the files stay where they are. The copy shown is the one without problems, then the one with the cleanest collector name, then the first catalogued; "Keep this copy instead" in the details panel changes it, and the choice is remembered across rescans. The Duplicates chip shows each set together, the copy kept first. Different disks that merely contain the same archive are no longer called duplicates: both are kept and the details panel says what they share
- **Disk sets on one row:** with **Group sets and versions** on (above the list, remembered), each multi-disk game or program named "(Disk N of M)" shows as one row: its picture, its title without the disk numbers, and a badge — Complete · 3 of 3, Disk 2 missing, Disk 3 has problems, or Complete · mixed releases (disk counts that disagree, or disks from different cracks such as [cr FLT] and [cr CSL], which don't always work together). Disks of a set in different folders still make one set. Double-click or Play starts the whole set, disk 1 first; Copy to Gotek copies all its disks. The details panel lists each disk with a link to it, marks the gaps and shows other versions of a disk. The **Sets to complete** chip lists the sets with missing or damaged disks, and File › Export sets to complete… saves what each one needs as a spreadsheet. Turn grouping off to see every disk and version on its own row
- **Versions on one row:** TOSEC collections keep every variant of a disk, told apart by tags in square brackets — [h ALE] hacked, [m bamcopy] modified, [o] overdump, [a] alternate, [cr FLT] cracked, [t] trained, [b] bad dump, [!] verified good dump. They aren't duplicates (the bytes differ), so with grouping on TurboCAT shows one version of each disk with a "4 versions" pill and hides the others; nothing is deleted. It shows a verified [!] dump if there is one, then the version without tags, then the one with fewest tags, avoiding bad dumps. The details panel lists every version with its tags in words and how its files differ from the one shown ("same files", or "changed S/startup-sequence; extra ale"); "show this one instead" changes the version shown and is remembered. Disk sets use the version shown of each disk
- **Closing while busy:** closing TurboCAT (or File › Quit) during a scan or a picture search no longer freezes the window or crashes. The bar says "Closing: stopping the scan first…", the window greys out, and TurboCAT closes as soon as the work has stopped, usually within a second; nothing new (such as the picture search after a scan) starts while closing. Downloading the picture list can now be stopped part-way. If something still hasn't stopped after 15 seconds (one very large disk image being read), TurboCAT offers to quit anyway: every item catalogued so far is already saved
- **Utilities chip:** tools and applications get their own chip, next to Games and Music. An item counts when it is in a folder called UTILITIES, Utils, Tools, Applications, Apps or Programs (TOSEC "Commodore Amiga - Applications" folders included), when a collection list beside it is a list of applications, or when its name says so (a copier, tracker, editor, paint program, virus killer, assembler, patch or fix disk…). Games stay games, and disks of modules or samples stay music. The details panel says why: "Utility — in a folder called UTILITIES"
- **Verified against collection lists:** TurboCAT reads the lists that come with downloaded collections, Internet Archive file lists (`*_files.xml`, titled by `*_meta.xml`) and TOSEC DAT files (`*.dat`), from the folders it has scanned. A file that matches its list exactly gets a "Verified — complete and undamaged" note; one the list names but with different contents gets a warning that it may be damaged or a different version. TOSEC DATs check disk images wherever they are, also inside ZIPs
- **Disks identified by their checksums:** Tools › Identify disks online… (it asks first) downloads the TOSEC catalogue of Amiga disks that libretro publishes on GitHub (about 12 MB, once, refreshed every two months; only the list is downloaded, nothing about your disks is sent) and looks up each disk's checksum in it, together with any TOSEC .dat files in the scanned folders. A disk called Disk1.adf then shows as "Superfrog (1993)(Team 17)(Disk 1 of 4)[cr CSL]" with its file name underneath, its tags explained in words, and it joins its set, its versions, the Games chip (from a games publisher) and the picture lookup under its real title. Searching finds the real name too. Files are never renamed by themselves: Tools › Rename files to their proper names… lists every rename first, renames only the ticked ones, keeps the catalogue in step and logs each rename in ~/.local/share/turbocat/renames.csv. For a file whose name says nothing and that isn't in any list, the details panel offers a guess from its folder ("Possibly Superfrog"), marked as a guess and never used for renaming
- **Check setup** (Help › Check setup…): every part TurboCAT uses — amitools, lhafile, xdms, Qt Multimedia, libopenmpt, libxmp, an Amiga emulator, Kickstart ROMs, TurboView and the list of Amiga disks — with ✓ or ✗, what each is for, what doesn't work without it, and how to get it on this computer: a command to copy (apt, dnf or pacman on Linux, Homebrew on a Mac) or a web page (Windows, Kickstart ROMs). It opens by itself on start if something important is missing (once for each set of missing parts), and the "no emulator", "no Kickstart" and "can't play music" messages point to it. Finding Amiga Forever's encrypted Kickstart ROMs is also about 20 times faster, so Play in emulator and TurboView open sooner
- **Tunes list, clearer:** the same size of text as the main list; each tune's song name read from the tune itself (OctaMED, XM, S3M and IT names too), with an Artist column when any tune records one. Tunes with no song name show their file name in grey italics, with the folder in front when the name says little ("Columns › song.0")
- **Favourites:** star disks, games, utilities, sets and tunes — Disk › Add to favourites (Ctrl+D), the Favourite button in the details panel, or a click on the star by a row's number (or on a tune's note). Starred items show under the Favourites chip; the Tunes list has a Favourites button. Favourites are stored by content, so they survive renames and rescans, and TurboView gets them a few seconds later: its Show menu has Favourites (every disk and tune you starred) and Utilities, favourites are marked » in its lists, its Shell version has `favs`, `favtunes` and `utils`, and `TurboView TurboCAT: FAVOURITES` starts in Favourites
- **TOSEC's full lists and coverdisks:** Tools › Identify disks online… now downloads TOSEC's own DAT pack from tosecdev.org (about 100 MB once, asking first; only its 68 Amiga floppy lists, about 35 MB and close to 100,000 disks, are kept) instead of libretro's games-only copy. Disks are identified across games, applications, coverdisks, demos, diskmags, collections and Workbench; disks in TOSEC's application lists count as utilities. A new **Coverdisks** chip lists magazine coverdisks, titled by magazine, issue, date and disk ("Amiga Shopper #47 · Mar 1995 · Disk 2 of 3"): by checksum when the copy matches TOSEC exactly, otherwise by its file and folder names, with a note saying whether the copy matches, differs or is empty. Disks made from a coverdisk (e.g. "Created Disks" beside an issue's disks) are listed under their issue
- **Magazine covers and Play for coverdisks:** Find pictures online also fetches the cover of each magazine issue you have coverdisks from, from the magazine scans on the Internet Archive (all of Amiga Shopper, most of CU Amiga, Amiga Computing and Amiga Action; only the magazine's name is searched for), and every disk of that issue shows it. An empty copy of a coverdisk gets a **Play a good copy** button when another copy of the same disk is catalogued, or a greyed-out Play button saying why it can't be played
- **The window can be maximised again:** the filter chips wrap onto a second line, and the result summary and the status line's catalogue path shorten, rather than making the window wider than a 1920-pixel screen (which made the desktop drop the maximise button)
- **Big archives of archives no longer look stuck:** while one is read (e.g. an Internet Archive download of 1,300 zipped disks), the progress bar moves, the file name shows how far inside it has got ("collection.zip › X-Copy.zip › X-Copy.adf"), and Stop works part way through; a file stopped part way is left out, so the next scan reads it again. Its inner files are no longer all held in memory at once
- **Big archives are asked about first:** before a scan reads anything, archives of 200 MB or more are listed with their size and roughly how long each will take (from the speed measured on this computer), and any can be unticked to leave for now (the next scan offers them again). While a big file is read, a second bar under the main one shows how far into it the scan is ("Inside collection.zip: 171 of 1,311 opened") and the time left for that file; both bars are thicker. A big file shows the second bar from the moment it starts loading from disk ("Loading collection.zip: 340 of 756 MB")
- **The picture search no longer stalls on big archives:** it read the whole archive from disk again for every disk inside it (hours for an archive of 1,300 zipped disks); now each archive is opened once and gone through in one pass (3 minutes for that one), with the same pictures, icons and tunes chosen. The second bar shows how far through what's inside it is, and Stop works part way (the item is looked through again next time)
- **Recheck (Shift+F5):** looks again at just the selected items (a set: all its disks) and the folder they are in, instead of every folder: their files are read again even if their dates haven't changed, and disks replaced, added or deleted beside them are picked up, so a set being repaired (a bad disk 3 swapped for a good one) can be checked at once. In the Disk menu, a Recheck button under the details, and a new right-click menu on the list (Play, Recheck, Show in folder, Copy to Gotek stick, Favourites). The folders inside it and the rest of the collection are left alone, and the rechecked item stays selected
- **Multi-disk coverdisks are listed under Coverdisks:** an issue whose disks form a set ("Amiga Shopper #47 (1995)…(Disk 1 of 3)", Disk 2 of 3…) is one row titled by its issue ("Amiga Shopper #47 · Mar 1995") and shows under the Coverdisks chip; before, the set's row was left out of that chip and took disk 1's title
- **Empty files are listed under the Empty chip only:** 0-byte files (nothing to read or play) no longer fill the other lists or count in their chips; the line above the list says how many were left out ("201 empty files hidden (see Empty)")
- **Workbench first, for disks that don't start by themselves:** a disk with no boot block (many coverdisks and utility disks were opened from Workbench) now starts with a Workbench disk from your collection in DF0: and itself in DF1:, so its icon is on the Workbench screen to double-click. Play in emulator ticks "Start Workbench first" for such disks (it can be ticked for any disk), lists the Workbench disks catalogued ("Workbench3.1", "Workbench1.3"… by their volume names), moves up to an Amiga whose Kickstart that Workbench needs, and runs the floppy drives fast so Workbench is up in about 20 seconds. If no Workbench disk is catalogued, it says how to add one
- Older LHA archives that the built-in reader can't open (the -lh1- method of 1990–91 and some header types, common on early coverdisks) are opened with 7-Zip or lha when either is installed, instead of being reported as unreadable; Check setup lists them as optional
- **Kickstart ROMs:** scanning a folder now finds Kickstart ROMs (including Amiga Forever's encrypted ones, when rom.key is beside them) and lists them under a Kickstart ROMs chip, named by what they are — Kickstart 1.3, 3.1 (A3000), CD32 extended ROM, AROS… — from exec's version and well-known checksums, with the machine each was made for and which model Play in emulator uses it for. Play and TurboView also look for ROMs in the folders where scanning found them, and ROMs made for the A3000, A4000 or CD32 are no longer picked for an A500, A600 or A1200
- Keyboard shortcuts are shown: the Scan folder…, Rescan and Copy to Gotek stick buttons carry their keys (Ctrl+O, F5, Ctrl+G) like the search box's Ctrl F, the menus list every shortcut, and the buttons' tooltips name theirs
- The details panel's buttons wrap onto a second line when the panel is narrow, instead of pushing pictures and long paths off its right edge
- **Emulator screen size:** Play in emulator has a Screen choice — Full screen (the default: borderless at your screen's size, e.g. 1920 × 1080), a 1080p window, or a normal window — remembered and used by the TurboView button too. The Amiga's picture keeps its shape and is centred, rather than being stretched to widescreen. In Amiberry, F12 opens its settings, to quit or leave full screen. (On a 1080p screen a 1080p window is trimmed by the window title and desktop panel, so Full screen is the true 1080p.)
- **TurboView on its own sharper screen:** started from TurboCAT, TurboView opens its own 1280 × 512 super-hires screen (built into Kickstart 3 on ECS/AGA Amigas) instead of the 640 × 256 Workbench screen, and the emulator is told to show super-hires detail, so at full screen on a big monitor TurboView is a normal-sized window in the middle of the screen rather than filling it. The options are `SCREEN=SUPER` (1280 × 512) and `SCREEN=HIGH` (640 × 512); without one TurboView opens on the Workbench screen as before
- **Play in emulator** (double-click an item, Ctrl+P, or the button in the details panel): starts the disk in Amiberry or FS-UAE. One disk of a set brings the whole set (Disk 1 in DF0:, Disk 2 in DF1:, all in the disk swapper); an A1200 is suggested for AGA titles, an A600 for ECS, otherwise an A500; Kickstart ROMs are found by their contents (Amiga Forever ROMs with rom.key work); IPF originals inside ZIPs are unpacked for the emulator; WHDLoad archives go to Amiberry's WHDLoad booter
- **TurboView**, the Amiga side: a Workbench window on Kickstart 2.04 and later (search as you type; Show: all, games, music, problems, duplicates; In: titles, files or tunes; the selected disk's details, contents and music; Boot it / Into DF0: / Into DF1: / Drives buttons, Boot only for disks that start by themselves), and a Shell version on Kickstart 1.3 or with the SHELL option. TurboCAT keeps a catalogue for it in `~/Amiberry/HardDrives/TurboCAT` (written after each look through the disks), and the **TurboView** button starts an emulated A1200 that boots from that folder as `TurboCAT:` with the collection folders mounted read-only. Search titles, files and tunes, see a disk's contents, music and where it is (PC path and Amiga path), and in Amiberry `insert 9` / `boot 9` put a disk in a drive or restart into it (`drives` shows what is in each). Runs on Kickstart 1.3 and later
- ZIP archives are read (TOSEC packs each disk in a .zip); an archive holding a single disk is listed as that disk
- Overdumped ADFs (TOSEC "[o]", extra tracks past the end of the disk) are read normally with a note, instead of being reported as a problem and mis-read as high density

## 4.0.0-alpha.3 — 7 Nov 2026

- Renamed from TurboCAT 2026 to TurboCAT 4; the command is now `python -m turbocat` and the default catalogue `~/turbocat.db`

## 0.1.2 — 7 Nov 2026 (as TurboCAT 2026)

- New `sets` command: recognises multi-disk sets from collector file names such as "(Disk 2 of 4)" and reports missing disks and mixed-up disk counts
- `dups` no longer lists files that a game repeats across its own disks, and groups common system files (libraries, fonts) into one line

## 0.1.1 — before 7 Nov 2026 (as TurboCAT 2026)

- Filesystem quirks on disks whose files all read (stale free-space maps on game disks) are now notes or warnings, not problems
- Truncated images say how many tracks are missing and still list the files that survive
- A DOS header with no readable filesystem is reported as a custom-format data disk (warning)
- The word "virus" in a bootblock is only a note unless the code behaves like a virus
- A mistyped folder gives a plain message instead of an error dump
