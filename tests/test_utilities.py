"""Utilities, and checking files against collection lists (Internet Archive, TOSEC DAT).

Run with:  ~/turbocat-env/bin/python -m unittest discover -s tests
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from turbocat import datlists, utilities     # noqa: E402

IA_FILES = """<?xml version="1.0" encoding="UTF-8"?>
<files>
  <file name="X-Copy Pro (1990)(Cachet).zip" source="original"><sha1>aaaa</sha1></file>
  <file name="Damaged (1990)(Someone).zip" source="original"><sha1>bbbb</sha1></file>
  <file name="apps_meta.xml" source="metadata"><sha1>cccc</sha1></file>
</files>"""
IA_META = """<?xml version="1.0" encoding="UTF-8"?>
<metadata><title>Commodore Amiga - Applications</title></metadata>"""
DAT = """<?xml version="1.0"?>
<datafile><header><name>Commodore Amiga - Games - [ADF]</name></header>
  <game name="Lemmings (1991)(Psygnosis)"><rom name="Lemmings (1991)(Psygnosis).adf" sha1="dddd"/></game>
</datafile>"""


def row(id, path, sha1="", kind="zip"):
    return {"id": id, "source": path, "sha1": sha1, "kind": kind}


class UtilitiesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.apps = os.path.join(self.root, "Downloads")
        os.makedirs(self.apps)
        with open(os.path.join(self.apps, "apps_files.xml"), "w") as f:
            f.write(IA_FILES)
        with open(os.path.join(self.apps, "apps_meta.xml"), "w") as f:
            f.write(IA_META)
        with open(os.path.join(self.root, "games.dat"), "w") as f:
            f.write(DAT)
        self.lists = datlists.lists_in([self.apps, self.root])

    def tearDown(self):
        self.tmp.cleanup()

    def test_lists_are_read_with_their_titles(self):
        titles = sorted(l.title for l in self.lists)
        self.assertEqual(titles, ["Commodore Amiga - Applications (Internet Archive)",
                                  "Commodore Amiga - Games - [ADF] (TOSEC)"])
        apps = next(l for l in self.lists if l.kind == "ia")
        self.assertTrue(apps.applications)
        self.assertNotIn("apps_meta.xml", apps.by_name)       # the list's own files don't count

    def test_match_differs_and_unknown(self):
        check = lambda name, shas, folder=None: datlists.check(name, folder or self.apps, shas, self.lists)[0]
        self.assertEqual(check("X-Copy Pro (1990)(Cachet).zip", {"aaaa"}), "match")
        self.assertEqual(check("Damaged (1990)(Someone).zip", {"ffff"}), "differs")
        self.assertIsNone(check("Other.zip", {"eeee"}))
        # a TOSEC DAT recognises a disk image wherever it is, e.g. inside a ZIP elsewhere
        self.assertEqual(check("Lemmings.zip", {"9999", "dddd"}, folder="/elsewhere"), "match")

    def test_utilities_by_list_folder_and_name(self):
        rows = [row(1, os.path.join(self.apps, "Anything (1990)(Someone).zip")),
                row(2, os.path.join(self.root, "UTILITIES", "Thing (1990).zip")),
                row(3, os.path.join(self.root, "Misc", "Virus Killer (1991)(PD).zip")),
                row(4, os.path.join(self.root, "Misc", "Lemmings (1991)(Psygnosis).zip")),
                row(5, os.path.join(self.root, "Misc", "ProTracker Modules (19xx).zip")),
                row(6, os.path.join(self.root, "Misc", "Copylock Game (1990).zip")),
                row(7, os.path.join(self.root, "Misc", "Disk Copier (1990).zip"))]
        why = utilities.classify(None, rows, {4: "game"}, self.lists, [self.root])
        self.assertIn("listed in", why[1])
        self.assertEqual(why[2], "in a folder called UTILITIES")
        self.assertIn("Virus", why[3])
        self.assertNotIn(4, why)            # a game stays a game
        self.assertNotIn(5, why)            # module disks are music, not utilities
        self.assertNotIn(6, why)            # "Copylock" is not "copy"
        self.assertIn("Copier", why[7])


if __name__ == "__main__":
    unittest.main()
