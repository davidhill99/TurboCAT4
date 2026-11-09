"""Which catalogued items are utilities and applications, and why.

Like games.py, each rule gives a reason shown to the user. An item is a utility when:
  * a folder it is in is called UTILITIES, Utils, Tools, Applications, Apps or Programs
    (including TOSEC folders such as "Commodore Amiga - Applications");
  * a collection list beside it (an Internet Archive list or TOSEC DAT) is a list of applications;
  * or its name says so: a copier, tracker, editor, paint program, virus killer, assembler...
Games always stay games, and disks of modules or samples are music, not utilities.
"""
import os
import re

from .pictures import clean_title

FOLDER = re.compile(r"(^|[\s\-_])(utilit(y|ies)|utils?|tools?|applications?|apps?|programs?|"
                    r"productivity)($|[\s\-_])", re.I)
NAME = re.compile(
    r"\b(copy|copier|x-?copy|disk ?master|backup|cruncher|packer|unpacker|ripper|archiver|lha|lzx|"
    r"tracker|editor|composer|sequencer|sampler|synth|paint|dpaint|draw|sketch|animator|"
    r"patch(es)?|fix(es)?|repair|doctor|salv\w*|virus|killer|checker|scanner|monitor|debugger|"
    r"assembler|compiler|devpac|seka|amos|blitz ?basic|basic|disassembler|reassembler|"
    r"utility|utilities|utils?|tools?|toolkit|workbench|kickstart|installer|format(ter)?|"
    r"speed ?up|accelerat\w*|boot ?(maker|menu|block)|menu ?maker|word ?processor|wordworth|"
    r"database|spreadsheet|calc|terminal|modem|printer|font|icon ?(editor|maker)|"
    r"action replay|degrader|relokick|emulator|viewer|converter|benchmark|sysinfo|diagnostics?)\b",
    re.I)
MUSIC_DATA = re.compile(r"\b(modules?|mods|samples?|music ?disk|songs?)\b", re.I)


def classify(cat, rows, game_why, lists, roots):
    """{media id: reason} for the top-level rows that are utilities.
    rows: media rows; game_why: games.classify's result; lists: datlists for their folders;
    roots: the scanned folders (folder names above them don't count)."""
    app_lists = {os.path.dirname(l.path): l for l in lists if l.applications}
    app_shas = {}
    for l in lists:
        if l.applications:
            for sha in l.by_sha1:
                app_shas[sha] = l
    out = {}
    for m in rows:
        if m["id"] in game_why or m["kind"] == "module":
            continue
        path = m["source"]
        title = clean_title(path)
        lst = app_shas.get((m["sha1"] or "").lower()) or app_lists.get(os.path.dirname(path))
        if lst is not None:
            out[m["id"]] = f"listed in {lst.title}"
            continue
        root = next((r for r in roots if path.startswith(r.rstrip("/") + "/")), "")
        inside = ([os.path.basename(root.rstrip("/"))] +
                  os.path.dirname(path)[len(root):].strip("/").split("/")) if root else []
        folder = next((f for f in inside if FOLDER.search(f)), None)
        if folder:
            out[m["id"]] = f"in a folder called {folder}"
            continue
        if MUSIC_DATA.search(title):
            continue
        word = NAME.search(title)
        if word:
            out[m["id"]] = f"the name says so (“{word.group(0)}”)"
    return out
