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


if __name__ == "__main__":
    unittest.main()
