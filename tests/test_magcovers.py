"""Magazine covers: matching Internet Archive titles to a magazine's issues.

Run with:  ~/turbocat-env/bin/python -m unittest discover -s tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from turbocat import magcovers     # noqa: E402


class MatchTest(unittest.TestCase):
    def test_issue_titles(self):
        m = magcovers.match_issue
        self.assertEqual(m("Amiga Shopper", "Amiga Shopper - Issue 21 (1993-01)(Future Publishing)(GB)"), "21")
        self.assertEqual(m("CU Amiga", "CU Amiga Magazine Issue 082"), "82")
        self.assertEqual(m("Amiga Action", "Amiga Action #35 (1992-08)"), "35")
        self.assertEqual(m("Amiga Computing", "Amiga Computing Issue 092 Nov 95"), "92")

    def test_not_issues(self):
        m = magcovers.match_issue
        self.assertIsNone(m("Amiga Format", "Amiga Format 1995 Annual"))
        self.assertIsNone(m("Amiga Action", "Amiga Action Coverdisk Scans 2 To 40 TIFF Format"))
        self.assertIsNone(m("Amiga Shopper", "Amiga Shopper Issue 71 1997 01 Future Publishing GB subscribers newsletter"))
        self.assertIsNone(m("Amiga Format", "Amiga Format Issue #21 CDROM Disc (Apr 1991)"))
        self.assertIsNone(m("Amiga Power", "Amiga Shopper - Issue 21 (1993-01)"))

    def test_issue_key(self):
        self.assertEqual(magcovers.issue_key("021"), "21")
        self.assertEqual(magcovers.issue_key("87-04&05"), "87-04&05")


if __name__ == "__main__":
    unittest.main()
