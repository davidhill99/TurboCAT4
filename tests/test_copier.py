"""The copier screen: each disk written fills in track by track, coloured by what is really on it,
with drive sounds that can be muted (remembered), and Fast to skip the picture."""
import os
import tempfile
import time
import unittest
import qt_cleanup  # noqa: F401  (deletes leftover windows before Qt shuts down)
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from turbocat import drivesound
from test_repair import make_adf


class TrackTest(unittest.TestCase):
    def test_tracks_show_what_is_on_the_disk(self):
        from turbocat import gui
        adf = bytes(make_adf("Tools", {"c/Tool": bytes(range(256)) * 40}))
        kinds = gui.track_kinds(adf)
        self.assertEqual(len(kinds), 160)
        self.assertEqual(kinds[0], "boot")
        self.assertIn("data", kinds)                     # the file's tracks
        self.assertIn("free", kinds)                     # most of the disk is empty
        self.assertEqual(set(gui.track_kinds(bytes(901120))), {"boot", "blank"})        # an empty disk
        self.assertEqual(gui.track_kinds(b"\x12" * 901120)[5], "nondos")   # a game's own format

    def test_the_sounds_are_short_wavs(self):
        import wave
        with mock.patch.object(drivesound, "SOUND_DIR", tempfile.mkdtemp()):
            files = drivesound.files()
        self.assertEqual(sorted(files), ["motor", "seek", "step"])
        for path in files.values():
            with wave.open(path) as w:
                self.assertEqual((w.getnchannels(), w.getsampwidth()), (1, 2))
                self.assertLess(w.getnframes() / w.getframerate(), 1.5)


class CopierTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        from turbocat import gui
        cls.app = QApplication.instance() or QApplication([])
        gui._pick_theme()

    def setUp(self):
        from turbocat.catalogue import Catalogue
        self.tmp = tempfile.TemporaryDirectory()
        self.cat = Catalogue(os.path.join(self.tmp.name, "cat.db"))
        self.cat.set_meta("drive_sound", False)          # no sound in tests
        self.adf = bytes(make_adf("Disk", {"File": b"x" * 5000}))

    def tearDown(self):
        self.cat.db.close()
        self.tmp.cleanup()

    def wait(self, dlg, seconds=10):
        end = time.monotonic() + seconds
        while dlg.close_btn.text() != "Close" and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.01)

    def test_disks_fill_in_and_the_summary_comes_last(self):
        from turbocat import gui
        dlg = gui.CopierDialog(None, self.cat, "Writing", total=2)
        dlg.add_disk("One", "STICK  DSKA0000.ADF", self.adf)
        dlg.add_disk("Two", "STICK  DSKA0001.ADF", self.adf)
        dlg.finish("Copied 2 disks.")
        self.assertEqual(dlg.close_btn.text(), "Stop")   # still showing them
        self.wait(dlg)
        self.assertEqual(dlg.close_btn.text(), "Close")
        self.assertEqual(dlg.summary.text(), "Copied 2 disks.")
        self.assertEqual(dlg.grid.kinds, gui.track_kinds(self.adf))     # the last disk, all written
        self.assertIn("2 of 2", dlg.lines[0].text())

    def test_fast_and_sound_are_remembered(self):
        from turbocat import gui
        dlg = gui.CopierDialog(None, self.cat)
        self.assertEqual(dlg.sound_btn.text(), "Sound: off")
        dlg.sound_btn.setChecked(True)
        dlg.fast.setChecked(True)
        self.assertTrue(self.cat.get_meta("drive_sound"))
        self.assertTrue(self.cat.get_meta("copier_fast"))
        dlg.sound_btn.setChecked(False)
        again = gui.CopierDialog(None, self.cat)
        self.assertTrue(again.fast.isChecked())
        self.assertFalse(again.sound_btn.isChecked())

    def test_stop_asks_the_writer_to_stop(self):
        from turbocat import gui
        dlg = gui.CopierDialog(None, self.cat)
        asked = []
        dlg.stop_requested.connect(lambda: asked.append(1))
        dlg.close_btn.click()
        self.assertEqual(asked, [1])
        self.assertEqual(dlg.close_btn.text(), "Stopping…")


class GotekWrittenTest(unittest.TestCase):
    def test_each_disk_written_is_handed_over(self):
        from turbocat import gotek
        seen = []
        with tempfile.TemporaryDirectory() as t, \
                mock.patch.object(gotek, "adf_bytes", return_value=b"A" * 901120):
            disks = [gotek.Disk(i, i, f"Game{i}.adf", 901120, "x", "ok") for i in range(2)]
            gotek.copy_disks(None, disks, t, numbered=True, written=lambda d, name, adf: seen.append(name))
        self.assertEqual(seen, ["DSKA0000.ADF", "DSKA0001.ADF"])


if __name__ == "__main__":
    unittest.main()
