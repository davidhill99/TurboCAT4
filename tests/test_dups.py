"""Duplicates: which copy TurboCAT keeps, and that a choice is remembered.

Run with:  ~/turbocat-env/bin/python -m unittest discover -s tests
"""
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from turbocat import dups                      # noqa: E402
from turbocat.catalogue import BLANK_SHA1, Catalogue   # noqa: E402


def item(id, path, key, status="ok"):
    return SimpleNamespace(id=id, number=id, path=path, dup_key=key, status=status,
                           copies=1, dup=False, spare_of=0, spares=())


class DupsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cat = Catalogue(os.path.join(self.tmp.name, "t.db"))

    def tearDown(self):
        self.cat.db.close()
        self.tmp.cleanup()

    def test_keeps_one_and_hides_the_rest(self):
        a, b, c = item(1, "/x/Game.adf", "k"), item(2, "/y/Game.adf", "k"), item(3, "/z/Other.adf", "o")
        dups.mark([a, b, c], self.cat)
        self.assertEqual((a.copies, a.spare_of, a.spares), (2, 0, (2,)))
        self.assertEqual((b.copies, b.spare_of), (2, 1))
        self.assertEqual((c.copies, c.dup), (1, False))

    def test_prefers_a_copy_without_problems_then_a_clean_name(self):
        bad = item(1, "/x/Game.adf", "k", status="error")
        flagged = item(2, "/x/Game [b].adf", "k")
        clean = item(3, "/y/Game.adf", "k")
        dups.mark([bad, flagged, clean], self.cat)
        self.assertEqual(clean.spare_of, 0)
        self.assertEqual({bad.spare_of, flagged.spare_of}, {3})

    def test_the_users_choice_is_remembered(self):
        a, b = item(1, "/x/Game.adf", "k"), item(2, "/y/Game.adf", "k")
        dups.choose(self.cat, "k", "/y/Game.adf")
        a2, b2 = item(1, "/x/Game.adf", "k"), item(2, "/y/Game.adf", "k")
        dups.mark([a2, b2], self.cat)
        self.assertEqual((a2.spare_of, b2.spare_of), (2, 0))

    def test_blank_and_empty_disks_are_not_duplicates(self):
        blank = [item(i, f"/b/{i}.adf", BLANK_SHA1[1]) for i in (1, 2)]
        empty = [item(i, f"/e/{i}.adf", "e", status="empty") for i in (3, 4)]
        dups.mark(blank + empty, self.cat)
        self.assertTrue(all(it.copies == 1 for it in blank + empty))


if __name__ == "__main__":
    unittest.main()
