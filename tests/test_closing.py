"""Closing during the picture search or a scan stops it, and then closes at once: the list is not
read again for a window that is going (on a 78,000-item catalogue that took over a minute)."""
import os
import tempfile
import unittest
import qt_cleanup  # noqa: F401  (deletes leftover windows before Qt shuts down)
from unittest import mock


class ClosingTest(unittest.TestCase):
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
        with mock.patch.object(gui.QTimer, "singleShot"):
            self.w = gui.MainWindow(os.path.join(self.tmp.name, "cat.db"))
        self.w.loader.wait(5000)
        self.app.processEvents()

    def tearDown(self):
        self.w.worker = None
        self.w.cat.db.close()
        self.w.deleteLater()
        self.app.processEvents()
        self.tmp.cleanup()

    def test_picture_search_stopped_by_closing_does_not_reload(self):
        self.w.closing = True
        with mock.patch.object(self.w, "reload") as reload:
            self.w._pic_done({"disk": {"looked": 3, "found": 1, "stopped": True}})
        reload.assert_not_called()

    def test_scan_stopped_by_closing_does_not_reload(self):
        self.w.closing = True
        with mock.patch.object(self.w, "reload") as reload:
            self.w._show_result("Stopped")
        reload.assert_not_called()

    def test_otherwise_the_list_is_read_again(self):
        with mock.patch.object(self.w, "reload") as reload:
            self.w._pic_done({"disk": {"looked": 3, "found": 1, "stopped": False}})
            self.w._show_result("Scan finished")
        self.assertEqual(reload.call_count, 2)

    def test_background_steps_say_what_they_are_doing(self):
        """The search nobody asked for shows in the status bar, with how far it has got."""
        self.w.pic_asked = self.w.pic_shown = False
        self.w._pic_progress("reading", 0, 0, "")
        self.assertIn("Bringing the list up to date", self.w.foot_left.text())
        self.w._pic_progress("disk", 10, 900, "Lemmings.adf")
        self.assertIn("11 of 900", self.w.foot_left.text())

    def test_game_details_show_beside_the_picture_search(self):
        """Game details have their own place in the status bar, so both can be seen at once."""
        self.w._pic_progress("disk", 10, 900, "Lemmings.adf")
        self.w._info_progress("list", 0, 0, "")
        self.assertIn("Wikidata", self.w.foot_info.text())
        self.w._info_progress("text", 4, 1471, "Lemmings")
        self.assertIn("5 of 1,471", self.w.foot_info.text())
        self.assertIn("11 of 900", self.w.foot_left.text())
        self.assertFalse(self.w.foot_info.isHidden())

    def test_the_list_read_in_the_background_is_used(self):
        items = list(self.w.all_items)
        with mock.patch.object(self.w, "reload") as reload:
            self.w._pic_done({"disk": {"looked": 0, "found": 0}, "items": items})
        reload.assert_called_once_with(items)
        self.w._info_done({"matched": 3, "texts": 2, "stopped": False})
        self.assertIn("found out about 2 more games", self.w.foot_info.text())

    def test_turboview_behind_the_catalogue_is_noticed(self):
        """TurboView listed 1,771 disks after a 78,000-item scan: its copy is brought up to date
        when TurboCAT starts if the count differs."""
        self.w.all_items = [mock.Mock()]               # one item (an empty catalogue never counts)
        folder = os.path.join(self.tmp.name, "TV")
        os.makedirs(folder)
        self.w.cat.set_meta("turboview_dir", folder)
        with open(os.path.join(folder, "TurboCAT.cat"), "w") as f:
            f.write(f"TURBOVIEW 1\nMADE 2026-11-14 20:47\tHOST x\tITEMS {len(self.w.all_items) + 1771}\n")
        self.assertTrue(self.w._turboview_behind())
        with open(os.path.join(folder, "TurboCAT.cat"), "w") as f:
            f.write(f"TURBOVIEW 1\nMADE 2026-11-15 12:00\tHOST x\tITEMS {len(self.w.all_items)}\n")
        self.assertFalse(self.w._turboview_behind())

    def test_turboview_is_updated_after_a_scan_without_waiting_for_pictures(self):
        self.w.pic_worker = object()                  # the picture search is running
        with mock.patch.object(self.gui.TurboViewWorker, "start") as start, \
                mock.patch.object(self.w, "find_pictures"):
            self.w._scan_finished()
        start.assert_called_once()
        self.w.pic_worker = None
        self.w.tv_worker = None

    def test_long_status_lines_dont_widen_the_window(self):
        """A long game title in the status bar made the window wider than the screen."""
        self.w.resize(1280, 860)
        self.w.show()
        self.app.processEvents()
        before = self.w.minimumSizeHint().width()
        self.w._info_progress("text", 119, 1471, "Mixed-Up Mother Goose: The Deluxe Multimedia "
                              "Edition for the Commodore Amiga CD32, with every extra disk")
        self.w._pic_foot("Looking for pictures and music on disks… inside TOSEC.2016.11.11."
                         "Commodore.Amiga.AlphaBot Games ADF: 4,701 of 32,788", 4701, 32788)
        self.app.processEvents()
        self.assertLessEqual(self.w.minimumSizeHint().width(), before)
        self.w.hide()


if __name__ == "__main__":
    unittest.main()
