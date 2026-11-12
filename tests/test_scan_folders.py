"""File > Scan folders…: a folder tree with tick boxes deciding what is scanned."""
import os
import tempfile
import unittest

from turbocat import folders, scanner
from turbocat.catalogue import Catalogue
from test_repair import make_adf

J = os.path.join


class SelectionTest(unittest.TestCase):
    """The tick boxes, without any disks."""

    def test_untick_inside_a_ticked_folder_leaves_it_out(self):
        s = folders.Selection(["/d"])
        s.untick("/d/Temp")
        self.assertEqual((s.roots, s.skips), (["/d"], ["/d/Temp"]))
        self.assertEqual(s.state("/d"), "part")
        self.assertEqual(s.state("/d/Temp"), "off")
        self.assertEqual(s.state("/d/Games"), "on")
        self.assertTrue(s.included("/d/loose.adf"))          # the folder's own files still scanned
        self.assertFalse(s.included("/d/Temp/x.adf"))

    def test_tick_inside_an_unticked_folder(self):
        s = folders.Selection(["/d"], ["/d/Temp"])
        s.tick("/d/Temp/Keep")
        self.assertTrue(s.included("/d/Temp/Keep/x.adf"))
        self.assertFalse(s.included("/d/Temp/other.adf"))
        self.assertEqual(s.state("/d/Temp"), "part")
        s.tick("/d/Temp")
        self.assertEqual((s.roots, s.skips), (["/d"], []))

    def test_parent_of_a_ticked_folder_is_half_ticked(self):
        s = folders.Selection(["/home/me/AMIGA"])
        self.assertEqual(s.state("/home/me"), "part")
        self.assertEqual(s.state("/home"), "part")
        self.assertEqual(s.state("/home/me/Music"), "off")
        s.untick("/home/me")
        self.assertEqual(s.roots, [])

    def test_ticking_a_parent_takes_in_the_folders_inside(self):
        s = folders.Selection(["/d/A", "/d/B"])
        s.tick("/d")
        self.assertEqual(s.roots, ["/d"])

    def test_gains(self):
        old = folders.Selection(["/d"], ["/d/Temp"])
        new = folders.Selection(["/d"], ["/d/Temp"])
        new.untick("/d/More")
        self.assertFalse(new.gains(old))
        new.tick("/d/Temp")
        self.assertTrue(new.gains(old))


class ScanFoldersTest(unittest.TestCase):
    """Scanning follows the ticks."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.a = J(t, "Games")
        self.junk = J(self.a, "Temp")
        self.keep = J(self.junk, "Keep")
        self.b = J(t, "Utils")
        for d, name in ((self.a, "One"), (self.junk, "Two"), (self.keep, "Four"), (self.b, "Three")):
            os.makedirs(d, exist_ok=True)
            with open(J(d, name + ".adf"), "wb") as f:
                f.write(make_adf(name, {"ReadMe": name.encode() * 50}))
        self.cat = Catalogue(J(t, "cat.db"))
        scanner.scan([self.a, self.b], self.cat, progress=None)

    def tearDown(self):
        self.cat.db.close()
        self.tmp.cleanup()

    def names(self):
        return sorted(os.path.basename(s) for s in self.cat.top_sources())

    def change(self, tick=(), untick=(), take_out=False):
        old, sel = self.cat.selection(), self.cat.selection()
        for p in untick:
            sel.untick(p)
        for p in tick:
            sel.tick(p)
        if take_out:
            self.cat.forget([s for s in self.cat.top_sources() if old.included(s) and not sel.included(s)])
        self.cat.save_selection(sel)

    def test_untick_and_keep_the_disks(self):
        self.change(untick=[self.b])
        self.assertEqual(self.cat.scan_roots(), [self.a])
        scanner.rescan_all(self.cat, progress=None)
        self.assertEqual(self.names(), ["Four.adf", "One.adf", "Three.adf", "Two.adf"])

    def test_untick_and_take_the_disks_out(self):
        self.change(untick=[self.b], take_out=True)
        scanner.rescan_all(self.cat, progress=None)
        self.assertEqual(self.names(), ["Four.adf", "One.adf", "Two.adf"])
        self.assertTrue(os.path.exists(J(self.b, "Three.adf")))           # file untouched

    def test_an_unticked_folder_inside_is_left_out(self):
        self.change(untick=[self.junk], take_out=True)
        s = scanner.rescan_all(self.cat, progress=None)
        self.assertEqual(self.names(), ["One.adf", "Three.adf"])
        self.assertEqual(s["left_out"], [self.junk])
        self.assertEqual(self.cat.skipped_folders(), [self.junk])         # a Rescan keeps it

    def test_a_ticked_folder_inside_an_unticked_one_is_scanned(self):
        self.change(untick=[self.junk], take_out=True)
        self.change(tick=[self.keep])
        scanner.rescan_all(self.cat, progress=None)
        self.assertEqual(self.names(), ["Four.adf", "One.adf", "Three.adf"])
        self.assertEqual(self.cat.scan_roots(), sorted([self.a, self.keep, self.b]))

    def test_counts(self):
        self.assertEqual(self.cat.count_under(self.a), 3)
        self.assertEqual(self.cat.count_under(self.junk), 2)


if __name__ == "__main__":
    unittest.main()
