"""Workbench icons for TurboView: classic .info files that icon.library and TurboCAT's own icon
reader both understand, with the right kind, picture and tooltypes."""
import os
import struct
import tempfile
import unittest

from turbocat import amigaimg, readers, turboview, wbicon
from test_turboview_real import tv_folder


class IconTest(unittest.TestCase):
    def test_tool_icon_carries_its_tooltypes(self):
        data = wbicon.tool_icon(["CATALOGUE=DH0:TurboCAT", "(FAVOURITES)"])
        self.assertEqual(data[:4], b"\xe3\x10\x00\x01")                 # magic, version
        self.assertEqual(wbicon.read(data), (wbicon.WBTOOL, ["CATALOGUE=DH0:TurboCAT", "(FAVOURITES)"], ""))
        self.assertEqual(struct.unpack(">I", data[74:78])[0], 40000)     # TurboView's stack

    def test_icons_decode_as_64_by_32_pictures(self):
        for data in (wbicon.tool_icon(), wbicon.disk_icon(), wbicon.drawer_icon(), wbicon.readme_icon()):
            img = amigaimg.decode_icon(data)
            self.assertEqual((img.width, img.height), (64, 32))

    def test_they_are_workbench_2_icons(self):
        """Marked revision 1, as 2.04 and 3.1 make them, so they're shown (and drawn by TurboCAT) in
        Workbench 2 colours; disks and drawers end with Workbench 2's view settings."""
        for data in (wbicon.tool_icon(), wbicon.disk_icon(), wbicon.drawer_icon(), wbicon.readme_icon()):
            self.assertEqual(struct.unpack(">I", data[44:48])[0], 1)
            self.assertEqual(amigaimg.decode_icon(data).note, "Workbench 2+")
        for data in (wbicon.disk_icon(), wbicon.drawer_icon()):
            self.assertEqual(data[-6:], struct.pack(">IH", 1, 1))

    def test_disks_and_drawers_have_a_window(self):
        self.assertEqual(wbicon.read(wbicon.disk_icon())[0], wbicon.WBDISK)
        self.assertEqual(wbicon.read(wbicon.drawer_icon())[0], wbicon.WBDRAWER)
        self.assertNotEqual(struct.unpack(">I", wbicon.disk_icon()[66:70])[0], 0)   # DrawerData there

    def test_readme_opens_in_more(self):
        self.assertEqual(wbicon.read(wbicon.readme_icon()), (wbicon.WBPROJECT, [], "SYS:Utilities/More"))

    def test_the_pixel_art_uses_all_four_pens(self):
        pens = {p for row in wbicon.art("mark") for p in row}
        self.assertEqual(pens, {0, 1, 2, 3})


class FloppyIconTest(unittest.TestCase):
    def test_both_floppies_show_on_workbench(self):
        with tempfile.TemporaryDirectory() as t:
            f = tv_folder(t)
            for maker, out in ((turboview.make_floppy, "a.adf"), (turboview.make_search_floppy, "b.adf")):
                path = os.path.join(t, out)
                maker(f, path)
                with open(path, "rb") as fh:
                    files = {e.path: e for e in readers.read_adf(fh.read()).files}
                for name in ("Disk.info", "TurboView.info", "ReadMe.info", "S/Drawer.icon"):
                    self.assertIn(name, files, f"{out} lacks {name}")
                kind, types, _ = wbicon.read(files["TurboView.info"].read())
                self.assertEqual((kind, types), (wbicon.WBTOOL, []))      # no CATALOGUE: its own disk


if __name__ == "__main__":
    unittest.main()
