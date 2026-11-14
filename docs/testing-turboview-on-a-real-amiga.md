# Testing TurboView on a real Amiga

TurboView floppies and the hard-drive install have only been tried in emulators and in a
command-line Amiga simulator (vamos). **They need trying on real Amigas before release.**
If you can help, please work through what you can below and report it with
**Help › Report a problem…** in TurboCAT (or by email), saying which Amiga you used.

## What you need

- In TurboCAT: **Tools › TurboView on a real Amiga…**, then make the floppies (save them, or copy them
  to your Gotek stick).
- Any Amiga. Most useful: an A500 with only 512 KB, an A500 with 1 MB, an A500+, an A600, an A1200.
- A Gotek, or real floppies written with e.g. a Greaseweazle. A hard drive (CF/SD) for the install test.

## Checks

For each, note the Amiga (model, Kickstart, memory, Gotek or floppy) and roughly how long it took.

1. **Boots by itself**: disk 1 boots straight into TurboView (window on Kickstart 2.04+, Shell on 1.3).
2. **Finding a disk by name**: type part of a game's name. Right disk? How quick?
3. **A disk's contents**: pick a disk; does its list of files appear, and how long does it take?
4. **Searching every file name**, from disk 1 alone: search a common name (e.g. `startup-sequence`) and a
   rare one. How long until the results or "Nothing found"? Can you stop it with a click, a key or Ctrl-C?
5. **The search disk (disk 2)**: boot from it and repeat check 4. Is it clearly quicker? Does it say how
   to see a disk's contents?
6. **Both disks in two drives** (DF0: and DF1:): do searches use disk 2 and contents use disk 1, with no
   disk-swap requests?
7. **Memory**: on a 512 KB A500, does anything run out of memory?
8. **Hard-drive install**: with your hard drive booted and disk 1 in a drive, in a Shell:
   `TurboView:TurboView INSTALL DH0:TurboCAT` (use your own drive). Did it ask for disk 2 when needed,
   finish without errors, and leave a working TurboView (`DH0:TurboCAT/TurboView DH0:TurboCAT`)? How long
   did it take? Are searches and contents fast from the hard drive?
9. **On Workbench** (Kickstart 2.04 or later): with Workbench running, insert a TurboView disk. Do the
   disk and TurboView icons look right? Double-click TurboView: does it open in a window on Workbench,
   find its lists, and stay usable beside other programs? Does the zoom gadget shrink it to its title
   bar and back?
10. **The installed icon**: after the install, double-click TurboView in its drawer. Drag it into
    WBStartup and reboot: does it open by itself? Try the tooltypes in its icon (Icons › Information):
    remove the brackets from `(SCREEN=HIGH)` or `(FAVOURITES)`.
11. **Workbench 1.3**: double-clicking TurboView should explain that its window needs 2.04, and how to
    start it from a Shell instead.
12. **Updating, a week later**: scan some new disks in TurboCAT and make the TurboView disks again (on a
    Gotek with numbered images, check they replaced the old ones rather than adding new numbers). With
    TurboView installed on the hard drive and open on Workbench, insert the new disk 1: does it offer
    "Update now?" Does the update ask for disk 2, finish, and then show the new disks? Did your changes
    to TurboView's tooltypes survive? If TurboView is in WBStartup, is that copy updated too?
    (Shell version: it says newer disks are there; type `update`.)
13. **Anything confusing**: wording, requesters, what to do next.

## Known so far (from emulators, not real hardware)

- Contents of one disk: a few seconds.
- Searching every file name from disk 1 on an A500: seconds for common names; up to ~4¾ minutes for a
  rare name with a real-speed drive (unpacking ~2½ min, floppy reading ~2 min).
