"""Disk sets: grouping "(Disk N of M)" names, and what makes a set complete.

Run with:  ~/turbocat-env/bin/python -m unittest discover -s tests
"""
import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from turbocat import dups, sets     # noqa: E402

GAME = "Cannon Fodder (1993)(Virgin)"


def disk(n, of, tag="[cr FLT]", status="ok", number=None, folder="/a"):
    name = f"{GAME}(Disk {n} of {of}){tag}.adf"
    return SimpleNamespace(file=name, path=f"{folder}/{name}", status=status,
                           number=number if number is not None else n)


class SetsTest(unittest.TestCase):
    def one(self, items):
        found = sets.group(items, dups.keeper_order)
        self.assertEqual(len(found), 1)
        return found[0]

    def test_complete_set(self):
        s = self.one([disk(1, 3), disk(2, 3), disk(3, 3)])
        self.assertTrue(s.complete)
        self.assertEqual(s.badge(), ("Complete · 3 of 3", "ok"))
        self.assertEqual([n for n, _, _ in s.disks], [1, 2, 3])

    def test_missing_disk(self):
        s = self.one([disk(1, 3), disk(3, 3)])
        self.assertEqual(s.missing, [2])
        self.assertEqual(s.badge(), ("Disk 2 missing", "problem"))

    def test_damaged_disk_makes_it_incomplete(self):
        s = self.one([disk(1, 2), disk(2, 2, status="error")])
        self.assertFalse(s.complete)
        self.assertEqual(s.badge()[0], "Disk 2 has problems")

    def test_mixed_releases_are_flagged_but_complete(self):
        s = self.one([disk(1, 2, "[cr FLT]"), disk(2, 2, "[cr CSL]")])
        self.assertTrue(s.complete)
        self.assertEqual(s.badge()[1], "warn")

    def test_disks_in_different_folders_still_make_one_set(self):
        s = self.one([disk(1, 2, folder="/a"), disk(2, 2, folder="/b")])
        self.assertTrue(s.complete)

    def test_best_copy_of_a_disk_is_used(self):
        bad = disk(1, 2, status="error", number=1)
        good = disk(1, 2, tag="[cr FLT][a]", number=5)
        s = self.one([bad, good, disk(2, 2, number=2)])
        n, used, others = s.disks[0]
        self.assertIs(used, good)
        self.assertEqual(others, [bad])

    def test_single_disks_are_not_sets(self):
        self.assertEqual(sets.group([disk(1, 1)], dups.keeper_order), [])


class SystemFileTest(unittest.TestCase):
    def test_workbench_commands_count_outside_c(self):
        for p in ("Assign", "Game/SetPatch", "Tools/IconX", "c/Assign", "Execute"):
            self.assertTrue(sets.is_system_file(p), p)

    def test_folders_and_extensions_still_count(self):
        for p in ("libs/diskfont.library", "Game/devs/narrator.device", "s/Startup-Sequence"):
            self.assertTrue(sets.is_system_file(p), p)

    def test_ordinary_game_files_do_not(self):
        for p in ("Game/Assign.doc", "Assigned", "Game/main.exe", "data/level1", "Copy.info"):
            self.assertFalse(sets.is_system_file(p), p)


if __name__ == "__main__":
    unittest.main()
