"""The Big archives window says which folder each archive is in, so one in a folder you meant to
leave out is easy to spot (and untick)."""
import os
import tempfile
import unittest
import qt_cleanup  # noqa: F401  (deletes leftover windows before Qt shuts down)
from unittest import mock


class BigArchivesTest(unittest.TestCase):
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
        loader = getattr(self.w, "loader", None)
        if loader is not None:
            loader.wait(5000)

    def tearDown(self):
        self.w.worker = None
        self.w.cat.db.close()
        self.w.deleteLater()
        self.app.processEvents()
        self.tmp.cleanup()

    def test_each_archive_shows_its_folder(self):
        from PySide6.QtWidgets import QDialog, QLabel
        home = os.path.expanduser("~")
        path = os.path.join(home, "Dropbox", "AMIGA", "compilations.zip")
        shown = []

        def fake_exec(dlg):
            shown.extend(lab.text() for lab in dlg.findChildren(QLabel))
            return QDialog.DialogCode.Rejected

        self.w.worker = mock.Mock()
        with mock.patch.object(QDialog, "exec", fake_exec):
            self.w._ask_big([(path, "zip", 800 << 20)], 2e6)
        self.assertIn("in " + os.path.join("~", "Dropbox", "AMIGA"), shown)
        self.w.worker.answer_big.assert_called_once_with([])      # closed: left for now

    def test_home_short(self):
        home = os.path.expanduser("~")
        self.assertEqual(self.gui._home_short(os.path.join(home, "Amiga")), os.path.join("~", "Amiga"))
        self.assertEqual(self.gui._home_short(home), "~")
        self.assertEqual(self.gui._home_short(home + "x"), home + "x")      # not inside home
        self.assertEqual(self.gui._home_short(os.sep + "media"), os.sep + "media")


if __name__ == "__main__":
    unittest.main()
