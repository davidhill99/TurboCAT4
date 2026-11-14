"""TurboView on a real Amiga: a bootable TurboView floppy (with the file list only if it fits), the
full files for a hard drive, and the window that makes them and copies the floppy to a Gotek."""
import os
import tempfile
import unittest
import qt_cleanup  # noqa: F401  (deletes leftover windows before Qt shuts down)
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from turbocat import bootblock, readers, turboview


def tv_folder(root, fil_size=1000, cat_size=2000):
    f = os.path.join(root, "tv")
    os.makedirs(f)
    with open(os.path.join(f, "TurboView"), "wb") as o:
        o.write(b"\x00\x00\x03\xf3" + b"\x00" * 3000)
    with open(os.path.join(f, "TurboCAT.cat"), "w", encoding="latin-1") as o:
        o.write("TURBOVIEW 1\nMADE 2026-11-13 20:20\tHOST amiga-pc\tITEMS 2\n")
        o.write("I\t1\tG\tGame\tLemmings\tLemmings.adf\t/x\t/x\n" * (cat_size // 40))
    for name, size in (("TurboCAT.idx", 100), ("TurboCAT.mus", 100), ("TurboCAT.fil", fil_size)):
        with open(os.path.join(f, name), "wb") as o:
            o.write(b"F\t1\tc/Dir\t100\n" * (size // 16 + 1))
    return f


class FloppyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = os.path.join(self.tmp.name, "TurboView.adf")

    def tearDown(self):
        self.tmp.cleanup()

    def read(self, path):
        with open(path, "rb") as f:
            data = f.read()
        return data, {e.path: e for e in readers.read_adf(data).files}

    def test_a_bootable_floppy_that_starts_turboview(self):
        r = turboview.make_floppy(tv_folder(self.tmp.name), self.out)
        self.assertTrue(r["with_files"])
        data, files = self.read(self.out)
        self.assertEqual(len(data), 901120)
        self.assertTrue(bootblock.analyse(data[:1024])["bootable"])
        for name in ("TurboView", "TurboCAT.cat", "TurboCAT.fil", "ReadMe", "S/Startup-Sequence"):
            self.assertIn(name, files)
        self.assertIn(b"TurboView SYS:", files["S/Startup-Sequence"].read())
        self.assertIn(b"amiga-pc", files["ReadMe"].read())

    def test_a_big_file_list_goes_on_packed(self):
        r = turboview.make_floppy(tv_folder(self.tmp.name, fil_size=2_000_000), self.out)
        self.assertEqual(r["files"], "packed")
        _, files = self.read(self.out)
        self.assertNotIn("TurboCAT.fil", files)
        self.assertNotIn("TurboCAT.idx", files)          # it points into TurboCAT.fil
        self.assertEqual(turboview.unpack_file_list(files["TurboCAT.fz"].read())[1][0], "c/Dir")
        self.assertIn(b"packed to fit", files["ReadMe"].read())

    def test_the_file_list_is_left_off_when_even_packed_it_does_not_fit(self):
        import random
        f = tv_folder(self.tmp.name)
        rnd = random.Random(1)
        with open(os.path.join(f, "TurboCAT.fil"), "w", encoding="latin-1") as o:
            for i in range(60000):           # names that don't pack: random letters
                o.write(f"F\t{i // 50}\t{''.join(rnd.choice('abcdefghijklmnopqrstuvwxyz0123456789') for _ in range(20))}\t1\n")
        r = turboview.make_floppy(f, self.out)
        self.assertEqual(r["files"], "none")
        _, files = self.read(self.out)
        self.assertNotIn("TurboCAT.fz", files)
        self.assertIn(b"too big for a floppy", files["ReadMe"].read())

    def test_one_huge_disk_cannot_break_the_packed_list(self):
        fil = b"".join(b"F\t5\tdir%05d/file\t1\n" % i for i in range(20000))     # ~300 KB for one disk
        fz = turboview.pack_file_list(fil)
        import struct
        self.assertLessEqual(struct.unpack(">4I", fz[4:20])[2], turboview.FZ_DISK_MAX + 100)      # plus its header and the note
        paths = turboview.unpack_file_list(fz)[5]
        self.assertIn("left out", paths[-1])

    def test_packing_round_trips_every_path(self):
        fil = (b"F\t3\tc/Dir\t10\nF\t3\tc/DiskCopy\t9\nF\t3\tc/Dis\t1\nF\t3\ts/\t0\n"
               b"F\t3\ts/startup-sequence\t5\nF\t9\t#hash/#name\t1\nF\t9\t\xe9t\xe9\t2\n")
        fz = turboview.pack_file_list(fil)
        self.assertEqual(turboview.unpack_file_list(fz),
                         {3: ["c/Dir", "c/DiskCopy", "c/Dis", "s/", "s/startup-sequence"],
                          9: ["#hash/#name", "\xe9t\xe9"]})

    def test_too_big_for_any_floppy_says_so(self):
        with self.assertRaises(ValueError) as e:
            turboview.make_floppy(tv_folder(self.tmp.name, cat_size=1_200_000), self.out)
        self.assertIn("hard drive", str(e.exception))
        self.assertFalse(os.path.exists(self.out))

    def test_files_for_a_hard_drive_have_everything(self):
        out = turboview.copy_files(tv_folder(self.tmp.name), self.tmp.name + "/card")
        self.assertEqual(sorted(os.listdir(out)), ["TurboCAT.cat", "TurboCAT.fil", "TurboCAT.idx",
                                                    "TurboCAT.mus", "TurboCAT.nix", "TurboView"])

    def test_the_search_disk_has_the_name_index(self):
        out = os.path.join(self.tmp.name, "TurboView2.adf")
        turboview.make_search_floppy(tv_folder(self.tmp.name), out)
        data, files = self.read(out)
        self.assertTrue(bootblock.analyse(data[:1024])["bootable"])
        self.assertIn("TurboCAT.nix", files)
        self.assertNotIn("TurboCAT.fz", files)
        self.assertIn(b"search disk", files["ReadMe"].read())
        self.assertEqual(turboview.read_name_index(files["TurboCAT.nix"].read()), {"Dir": [1]})

    def test_the_name_index_lists_each_name_once_with_its_disks(self):
        fil = (b"F\t3\tc/Dir\t1\nF\t3\tc/\t0\nF\t5\tC/DIR\t1\nF\t5\tc/MuchMore\t2\n"
               b"F\t9\tc/MuchMore\t2\nF\t9\tTools/MuchMore.doc\t3\n")
        idx = turboview.read_name_index(turboview.build_name_index(fil))
        self.assertEqual(idx["c/"], [3])
        self.assertEqual(sorted(idx[k] for k in idx if k.lower() == "dir"), [[3, 5]])   # case folded
        self.assertEqual(idx["MuchMore"], [5, 9])
        self.assertEqual(idx["MuchMore.doc"], [9])


class SlimmerTest(unittest.TestCase):
    def test_looping_directory_junk_is_spotted_and_real_paths_are_not(self):
        loop = "/".join([">>> TMF Crunchdisk 2.0 <<", ">>> The MAGNUM Force <<"] * 10) + "/x"
        self.assertTrue(turboview.junk_path(loop))
        self.assertTrue(turboview.junk_path("a" * 300))
        for real in ("c/Dir", "Pinball Fantasies (Digital Illusions + 21st Century) A.adf",
                     "Devs/Monitors/a/b/c/d/e/f/PAL"):
            self.assertFalse(turboview.junk_path(real))

    def test_the_floppy_list_drops_the_computers_paths_but_keeps_every_field(self):
        cat = (b"TURBOVIEW 1\nMADE x\tHOST pc\tITEMS 1\nROOT\t/home/me/Amiga\tAmiga\n"
               b"I\t7\tG\tADF\tLemmings\tLemmings.adf\t/home/me/Amiga/Lemmings.adf\t/home/me/Amiga/Lemmings.adf\n")
        slim = turboview.floppy_catalogue(cat)
        self.assertNotIn(b"/home/me", slim)
        self.assertNotIn(b"ROOT", slim)
        line = [l for l in slim.split(b"\n") if l.startswith(b"I\t")][0].split(b"\t")
        self.assertEqual(line, [b"I", b"7", b"G", b"ADF", b"Lemmings", b"Lemmings.adf", b"-", b"-"])

    def test_the_floppy_carries_no_personal_paths(self):
        with tempfile.TemporaryDirectory() as t:
            f = tv_folder(t)
            with open(os.path.join(f, "TurboCAT.cat"), "a", encoding="latin-1") as o:
                o.write("ROOT\t/home/zorro/Amiga\tAmiga\n")
            out = os.path.join(t, "tv.adf")
            turboview.make_floppy(f, out)
            with open(out, "rb") as o:
                self.assertNotIn(b"/home/zorro", o.read())


class RealAmigaWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        from turbocat import gui
        cls.app = QApplication.instance() or QApplication([])
        gui._pick_theme()

    def setUp(self):
        from turbocat import gui
        self.gui = gui
        self.tmp = tempfile.TemporaryDirectory()
        with mock.patch.object(gui.QTimer, "singleShot"):        # no start-up timers after the test
            self.w = gui.MainWindow(os.path.join(self.tmp.name, "cat.db"))
        self.w.cat.set_meta("turboview_dir", tv_folder(self.tmp.name))
        self.w.cat.set_meta("drive_sound", False)                     # the copier screen stays quiet
        self.stick = os.path.join(self.tmp.name, "stick")
        os.makedirs(self.stick)

    def tearDown(self):
        loader = getattr(self.w, "loader", None)
        if loader is not None:
            loader.wait(5000)
        self.app.processEvents()                 # the loader's results, while the catalogue is open
        from PySide6.QtCore import QEvent, QTimer
        for t in self.w.findChildren(QTimer):   # nothing of this window runs during the next test
            t.stop()
        self.w.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        self.w.cat.db.close()
        self.tmp.cleanup()

    def dialog(self):
        with mock.patch.object(self.gui.gotek, "find_sticks", return_value=[(self.stick, "GOTEK", 10**9)]):
            dlg = self.gui.RealAmigaDialog(self.w)
        dlg._fresh = lambda: None                 # the test's catalogue files are already there
        return dlg

    def test_copies_the_floppy_to_the_gotek_by_name(self):
        dlg = self.dialog()
        self.assertTrue(dlg.gotek_btn.isEnabled())
        dlg.to_gotek()
        self.assertTrue(os.path.exists(os.path.join(self.stick, "TurboView.adf")))
        self.assertTrue(os.path.exists(os.path.join(self.stick, "TurboView2.adf")))
        self.assertIn("choose TurboView.adf (disk 1", dlg.result.text())

    def test_a_numbered_gotek_gets_the_next_number(self):
        open(os.path.join(self.stick, "DSKA0000.ADF"), "wb").close()
        self.w.cat.set_meta("gotek_numbered", True)
        dlg = self.dialog()
        dlg.to_gotek()
        self.assertTrue(os.path.exists(os.path.join(self.stick, "DSKA0001.ADF")))
        self.assertTrue(os.path.exists(os.path.join(self.stick, "DSKA0002.ADF")))
        self.assertIn("image number 1 (disk 1; disk 2 is number 2)", dlg.result.text())

    def test_copying_again_reuses_the_same_numbers(self):
        open(os.path.join(self.stick, "DSKA0000.ADF"), "wb").close()     # someone else's disk
        self.w.cat.set_meta("gotek_numbered", True)
        dlg = self.dialog()
        dlg.to_gotek()
        before = sorted(os.listdir(self.stick))
        self.assertEqual(before, ["DSKA0000.ADF", "DSKA0001.ADF", "DSKA0002.ADF"])
        self.assertEqual(turboview.volume_of(os.path.join(self.stick, "DSKA0002.ADF")), "TurboView2")
        dlg.to_gotek()                                                  # week 2
        self.assertEqual(sorted(os.listdir(self.stick)), before)        # replaced, not added
        self.assertEqual(os.path.getsize(os.path.join(self.stick, "DSKA0000.ADF")), 0)   # left alone

    def test_no_stick_no_gotek_button(self):
        with mock.patch.object(self.gui.gotek, "find_sticks", return_value=[]):
            dlg = self.gui.RealAmigaDialog(self.w)
        self.assertFalse(dlg.gotek_btn.isEnabled())
        self.assertIn("Plug in", dlg.gotek_btn.toolTip())


if __name__ == "__main__":
    unittest.main()
