"""While a scan runs, the list shows new items by reading the catalogue in the background, so the
window keeps responding however big the catalogue is (a 74,000-file first scan made it "not
responding": reading took longer than the time between reloads)."""
import os
import tempfile
import time
import unittest
import qt_cleanup  # noqa: F401  (deletes leftover windows before Qt shuts down)
from unittest import mock


class LiveReloadTest(unittest.TestCase):
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
        if self.w.live_loader is not None:
            self.w.live_loader.wait(5000)
        self.w.worker = None
        self.w.cat.db.close()
        self.w.deleteLater()
        self.app.processEvents()
        self.tmp.cleanup()

    def _wait(self):
        end = time.monotonic() + 10
        while self.w.live_loader.isRunning() and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.01)
        self.app.processEvents()

    def test_reads_in_the_background_and_shows_the_result(self):
        self.w.worker = mock.Mock()                 # a scan is running and has found something
        self.w.found_count = 1
        items = [mock.Mock()]
        with mock.patch.object(self.gui, "load_items", return_value=items) as load, \
                mock.patch.object(self.w, "reload") as shown:
            self.w._live_reload()
            self.w._live_reload()                   # the first is still reading: not started twice
            self._wait()
        self.assertEqual(load.call_count, 1)
        shown.assert_called_once_with(items)
        self.assertGreaterEqual(self.w.live.interval(), 4000)

    def test_a_result_after_the_scan_finished_is_dropped(self):
        self.w.worker = mock.Mock()
        self.w.found_count = 1
        with mock.patch.object(self.gui, "load_items", return_value=[]), \
                mock.patch.object(self.w, "reload") as shown:
            self.w._live_reload()
            self.w.worker = None                    # the scan ends; its own reload is newer
            self._wait()
        shown.assert_not_called()


if __name__ == "__main__":
    unittest.main()
