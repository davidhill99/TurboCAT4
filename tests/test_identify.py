"""Identifying disks by checksum, guesses from folders, and planning renames.

Run with:  ~/turbocat-env/bin/python -m unittest discover -s tests
"""
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from turbocat import identify     # noqa: E402

DAT = '''clrmamepro (
	name "Commodore - Amiga"
)
game (
	name "Superfrog (Disk 1)[cr CSL]"
	rom ( name "Superfrog (1993)(Team 17)(Disk 1 of 4)[cr CSL].adf" size 901120 crc 459F2DA1 md5 9F1C4077C2AA5C2071BA91690435B9E9 sha1 D042ECDD24DEC61F7823DD322F0A2314D06BC2D1 )
)
'''
SHA = "d042ecdd24dec61f7823dd322f0a2314d06bc2d1"


class IdentifyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        identify.DAT_PATH = os.path.join(self.tmp.name, "list.dat")
        identify.INDEX_PATH = os.path.join(self.tmp.name, "list.json")
        identify._index = None
        with open(identify.DAT_PATH, "w") as f:
            f.write(DAT)

    def tearDown(self):
        identify._index = None
        self.tmp.cleanup()

    def test_a_disk_is_known_by_its_checksum_whatever_its_name(self):
        rows = {7: [{"sha1": "0" * 40}, {"sha1": SHA.upper()}]}      # e.g. an ADF inside a ZIP
        found = identify.identify(rows)
        self.assertEqual(found[7][0], "Superfrog (1993)(Team 17)(Disk 1 of 4)[cr CSL].adf")
        self.assertEqual(identify.identify({8: [{"sha1": "1" * 40}]}), {})

    def test_guesses_only_for_names_that_say_nothing(self):
        self.assertEqual(identify.guess("/a/Superfrog/Disk1.adf"), "Superfrog")
        self.assertEqual(identify.guess("/a/Amiga/Disk1.adf"), "")            # the folder says nothing
        self.assertEqual(identify.guess("/a/Superfrog/Frog intro.adf"), "")   # the name says something

    def test_rename_plan_keeps_the_extension_and_skips_names_already_right(self):
        folder = self.tmp.name
        paths = [os.path.join(folder, n) for n in ("Disk1.zip", "Superfrog (1993)(Team 17)(Disk 1 of 4)[cr CSL].adf")]
        for p in paths:
            open(p, "w").close()
        name = "Superfrog (1993)(Team 17)(Disk 1 of 4)[cr CSL]"
        items = [SimpleNamespace(path=p, type="ADF", tosec_name=name) for p in paths]
        plan = identify.rename_plan(items)
        self.assertEqual(len(plan), 1)
        self.assertEqual(os.path.basename(plan[0][2]), name + ".zip")


if __name__ == "__main__":
    unittest.main()
