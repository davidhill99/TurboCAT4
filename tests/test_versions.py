"""Versions: TOSEC variants of one disk ([h], [m], [o], [!] ...), and which one is shown.

Run with:  ~/turbocat-env/bin/python -m unittest discover -s tests
"""
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from turbocat import versions            # noqa: E402
from turbocat.catalogue import Catalogue  # noqa: E402

BASE = "/c/PD Games Volume 001 (199x)(The Assassins)(PD)"


def item(id, suffix, status="ok", spare_of=0):
    return SimpleNamespace(id=id, number=id, path=BASE + suffix, status=status, spare_of=spare_of,
                           version_key="", versions=1, version_of=0, other_versions=())


class VersionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cat = Catalogue(os.path.join(self.tmp.name, "t.db"))

    def tearDown(self):
        self.cat.db.close()
        self.tmp.cleanup()

    def test_tags_in_words(self):
        self.assertEqual(versions.describe("h ALE"), "hacked by ALE")
        self.assertEqual(versions.describe("cr FLT"), "cracked by FLT")
        self.assertEqual(versions.describe("o"), "overdump (extra data at the end)")
        self.assertEqual(versions.describe("a2"), "alternate version")
        self.assertEqual(versions.describe("docs"), "docs")

    def test_versions_share_a_key_but_disks_of_a_set_do_not(self):
        k = versions.version_key
        self.assertEqual(k(BASE + ".zip"), k(BASE + "[h ALE].zip"))
        self.assertEqual(k(BASE + ".zip"), k(BASE + "[o].adf"))
        self.assertNotEqual(k("/x/Game (1990)(Disk 1 of 2).adf"), k("/x/Game (1990)(Disk 2 of 2).adf"))

    def test_the_standard_version_is_shown(self):
        hacked, plain, over = item(2, "[h ALE].zip"), item(1, ".zip"), item(4, "[o].zip")
        versions.mark([hacked, plain, over], self.cat)
        self.assertEqual((plain.version_of, plain.versions), (0, 3))
        self.assertEqual(set(plain.other_versions), {2, 4})
        self.assertEqual(hacked.version_of, 1)

    def test_verified_beats_plain_and_bad_dumps_lose(self):
        plain, good, bad = item(1, ".zip"), item(2, "[!].zip"), item(3, "[b].zip")
        versions.mark([bad, plain, good], self.cat)
        self.assertEqual(good.version_of, 0)
        bad2, hacked = item(5, "[b].zip"), item(6, "[h X].zip")
        versions.mark([bad2, hacked], self.cat)
        self.assertEqual(hacked.version_of, 0)        # a hacked disk beats a damaged one

    def test_choice_is_remembered_and_spares_stay_out(self):
        versions.choose(self.cat, versions.version_key(BASE + ".zip"), BASE + "[o].zip")
        plain, over, spare = item(1, ".zip"), item(4, "[o].zip"), item(9, "[m x].zip", spare_of=1)
        versions.mark([plain, over, spare], self.cat)
        self.assertEqual((over.version_of, plain.version_of), (0, 4))
        self.assertEqual(spare.versions, 1)


class GoodCopyTest(unittest.TestCase):
    """R2: a damaged disk with a version that reads fully is pointed to it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cat = Catalogue(os.path.join(self.tmp.name, "t.db"))

    def tearDown(self):
        self.cat.db.close()
        self.tmp.cleanup()

    def test_damaged_disk_points_to_the_good_version(self):
        bad, good, warn = item(1, "[b].zip", "error"), item(2, ".zip"), item(3, "[h ALE].zip", "warning")
        versions.mark([bad, good, warn], self.cat)
        self.assertEqual(bad.good_copy, 2)               # the best healthy one: no tags, no warning
        self.assertFalse(hasattr(good, "good_copy"))

    def test_no_good_copy_when_every_version_is_damaged(self):
        a, b = item(1, "[b].zip", "error"), item(2, ".zip", "error")
        versions.mark([a, b], self.cat)
        self.assertFalse(hasattr(a, "good_copy") or hasattr(b, "good_copy"))

    def test_an_empty_file_points_to_a_working_version(self):
        empty, good = item(1, ".zip", "empty"), item(2, "[a].zip")
        versions.mark([empty, good], self.cat)
        self.assertEqual(empty.good_copy, 2)

    def test_a_bad_dump_that_reads_is_not_a_good_copy(self):
        bad, also_bad = item(1, ".zip", "error"), item(2, "[b virus damage].zip")
        versions.mark([bad, also_bad], self.cat)
        self.assertFalse(hasattr(bad, "good_copy"))

    def test_a_version_with_no_files_is_not_a_good_copy(self):
        bad, wrecked = item(1, ".zip", "error"), item(2, "[a].zip")
        bad.files, wrecked.files = "220", "—"           # TurboCAT could list nothing on it
        versions.mark([bad, wrecked], self.cat)
        self.assertFalse(hasattr(bad, "good_copy"))

    def test_spare_copies_of_the_damaged_disk_get_it_too(self):
        bad, good = item(1, "[b].zip", "error"), item(2, ".zip")
        spare = item(3, "[b] copy.zip", "error", spare_of=1)
        versions.mark([bad, good, spare], self.cat)
        self.assertEqual(spare.good_copy, 2)

    def test_a_different_disk_is_not_a_good_copy(self):
        bad = item(1, "[b].zip", "error")
        other = SimpleNamespace(**{**vars(item(2, ".zip")), "path": "/c/Other Disk (PD).zip"})
        versions.mark([bad, other], self.cat)
        self.assertFalse(hasattr(bad, "good_copy"))


if __name__ == "__main__":
    unittest.main()
