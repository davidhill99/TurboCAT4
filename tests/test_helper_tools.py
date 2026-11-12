"""Items that couldn't be read for want of a helper program (lha, xdms) are read again once
after it is installed, even though their files haven't changed."""
import os
import tempfile
import unittest
from unittest import mock

from turbocat.catalogue import Catalogue
from turbocat import readers, scanner


class HelperToolRetryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        # looks like an LHA archive (-lh1- header) but can't be opened by anything
        with open(os.path.join(self.root, "Old.lha"), "wb") as f:
            f.write(b"\x20\x00-lh1-" + b"\xff" * 200)
        with open(os.path.join(self.root, "Fine.adf"), "wb") as f:
            f.write(bytes(901120))
        self.cat = Catalogue(os.path.join(self.root, "cat.db"))

    def tearDown(self):
        self.cat.db.close()
        self.tmp.cleanup()

    def scan(self, tools):
        with mock.patch.object(readers, "helper_tools", return_value=tools):
            return scanner.scan([self.root], self.cat, progress=None)["scanned"]

    def test_read_again_once_when_a_tool_arrives(self):
        self.assertEqual(self.scan([]), 2)             # first scan reads both
        self.assertEqual(self.scan([]), 0)             # nothing changed, no new tools
        self.assertEqual(self.scan(["lha"]), 1)        # lha installed: only the LHA item again
        self.assertEqual(self.scan(["lha"]), 0)        # and only once

    def test_unrelated_tool_does_not_retry(self):
        self.scan([])
        self.assertEqual(self.scan(["xdms"]), 0)       # no DMS item had trouble

    def test_finds_items_by_their_message(self):
        self.scan([])
        found = self.cat.sources_with_message(["LHA archive unreadable"])
        self.assertEqual({os.path.basename(p) for p in found}, {"Old.lha"})
        self.assertEqual(self.cat.sources_with_message([]), set())

    def test_says_what_would_fix_it(self):
        with mock.patch.object(readers.shutil, "which", return_value=None):
            self.assertEqual(readers.local_fixes(["x.lha: LHA archive unreadable: bad"]),
                             [("lha", "lhasa", False)])
        with mock.patch.object(readers.shutil, "which", return_value="/usr/bin/xdms"):
            self.assertEqual(readers.local_fixes(["DMS not unpacked: no xdms"]),
                             [("xdms", "xdms", True)])
        self.assertEqual(readers.local_fixes(["Disk is truncated"]), [])


if __name__ == "__main__":
    unittest.main()
