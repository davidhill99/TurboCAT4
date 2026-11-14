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
        identify.TOSEC_DIR = os.path.join(self.tmp.name, "tosec")        # no TOSEC lists here
        identify.TOSEC_INDEX = os.path.join(self.tmp.name, "tosec.json")
        identify._tosec = None
        with open(identify.DAT_PATH, "w") as f:
            f.write(DAT)

    def tearDown(self):
        identify._index = None
        identify._tosec = None
        self.tmp.cleanup()

    def test_a_disk_is_known_by_its_checksum_whatever_its_name(self):
        rows = {7: [{"sha1": "0" * 40}, {"sha1": SHA.upper()}]}      # e.g. an ADF inside a ZIP
        found = identify.identify(rows)
        self.assertEqual(found[7][0], "Superfrog (1993)(Team 17)(Disk 1 of 4)[cr CSL].adf")
        self.assertEqual(identify.identify({8: [{"sha1": "1" * 40}]}), {})

    def test_an_archive_holding_a_whole_set_is_named_for_the_set(self):
        """Walker in one zip, disks A, B and C: it is the whole game, not disk 1 of 3."""
        names = [f"Walker (1993)(Psygnosis)(Disk {n} of 3)[cr FLT].adf" for n in (1, 2, 3)]
        self.assertEqual(identify.several_disks(names[0], names), "Walker (1993)(Psygnosis)[cr FLT].adf")
        self.assertEqual(identify.several_disks(names[0], names[:2]),
                         "Walker (1993)(Psygnosis)(Disks 1, 2 of 3)[cr FLT].adf")
        self.assertEqual(identify.several_disks(names[0], names[:1]), names[0])
        other = "Lemmings (1991)(Psygnosis)(Disk 2 of 2).adf"
        self.assertEqual(identify.several_disks(names[0], [names[0], other]), names[0])
        from turbocat import sets
        self.assertIsNone(sets.parse("Walker (1993)(Psygnosis)[cr FLT].adf"))   # so not a set's disk

    def test_a_disk_shared_with_another_release_doesnt_split_the_set(self):
        """Pinball Fantasies: disk A matches the 4-disk release's disk 1, B and C say "of 3"."""
        names = ["Pinball Fantasies (1992)(21st Century)(Disk 1 of 4)[cr SR].adf",
                 "Pinball Fantasies (1992)(21st Century)(Disk 2 of 3)[cr SP].adf",
                 "Pinball Fantasies (1992)(21st Century)(Disk 3 of 3)[cr SP].adf"]
        self.assertEqual(identify.several_disks(names[0], names),
                         "Pinball Fantasies (1992)(21st Century)[cr SP].adf")

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

    def test_rename_plan_leaves_spare_copies_and_never_doubles_the_extension(self):
        folder = self.tmp.name
        name = "Kickstart v3.1 r40.068 (1993-12)(Commodore)(A1200)[!].rom"
        paths = [os.path.join(folder, n) for n in ("KS31 A1200.rom", "KS31 A1200 (1).rom")]
        for p in paths:
            open(p, "w").close()
        items = [SimpleNamespace(path=p, type="ROM", tosec_name=identify.stem(name)) for p in paths]
        spares = []
        plan = identify.rename_plan(items, spares)
        self.assertEqual([os.path.basename(t) for _, _, t in plan], [name])       # not .rom.rom
        self.assertEqual(len(spares), 1)
        os.rename(plan[0][1], plan[0][2])                 # the first run renamed one copy
        items[[it.path for it in items].index(plan[0][1])].path = plan[0][2]
        spares = []
        self.assertEqual(identify.rename_plan(items, spares), [])     # nothing offered again
        self.assertEqual(len(spares), 1)

    def test_a_doubled_extension_from_before_is_put_right(self):
        name = "Kickstart v2.04 r37.175 (1991-05)(Commodore)(A3000).rom"
        p = os.path.join(self.tmp.name, name + ".rom")
        open(p, "w").close()
        plan = identify.rename_plan([SimpleNamespace(path=p, type="ROM", tosec_name=identify.stem(name))])
        self.assertEqual(os.path.basename(plan[0][2]), name)


if __name__ == "__main__":
    unittest.main()
