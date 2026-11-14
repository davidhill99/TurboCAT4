"""A new user's first start: a welcome with one button instead of an empty list, no setup report
over it (that waits until there are disks), and no TurboView folder made before there is anything
to put in it."""
import os
import tempfile
import unittest
import qt_cleanup  # noqa: F401  (deletes leftover windows before Qt shuts down)
from unittest import mock


class FirstStartTest(unittest.TestCase):
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
        loader = getattr(self.w, "loader", None)
        if loader is not None:
            loader.wait(5000)
        self.app.processEvents()

    def tearDown(self):
        self.w.cat.db.close()
        self.w.deleteLater()
        self.app.processEvents()
        self.tmp.cleanup()

    def test_an_empty_catalogue_shows_the_welcome(self):
        self.w.run_search()
        self.assertIs(self.w.stack.currentWidget(), self.w.welcome)
        self.assertEqual(self.w.welcome_btn.text(), "Choose your Amiga folder…")
        with mock.patch.object(self.w, "scan_folder") as scan:
            self.w.welcome_btn.clicked.disconnect()
            self.w.welcome_btn.clicked.connect(scan)
            self.w.welcome_btn.click()
        scan.assert_called_once()

    def test_a_first_scan_says_disks_are_being_read(self):
        self.w.worker = object()                 # a scan running, nothing catalogued yet
        try:
            self.w.run_search()
            self.assertIs(self.w.stack.currentWidget(), self.w.message)
            self.assertIn("Reading your disks", self.w.message.text())
        finally:
            self.w.worker = None

    def test_the_setup_report_waits_until_there_are_disks(self):
        missing = mock.Mock(status="missing", important=True)
        missing.name = "Kickstart ROMs"
        with mock.patch.object(self.gui.setupcheck, "run", return_value=[missing]), \
                mock.patch.object(self.w, "setup_features", return_value=[]), \
                mock.patch.object(self.w, "check_setup") as shown:
            self.w._setup_on_start()
        shown.assert_not_called()
        self.assertTrue(self.w.setup_after_scan)

    def test_no_turboview_folder_while_the_catalogue_is_empty(self):
        folder = os.path.join(self.tmp.name, "TurboCAT-Amiga")
        with mock.patch.object(self.gui.turboview, "default_folder", return_value=folder):
            worker = self.gui.TurboViewWorker(self.w.db_path)
            worker.run()
        self.assertFalse(os.path.exists(folder))


if __name__ == "__main__":
    unittest.main()
