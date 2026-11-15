"""While a big catalogue opens (78,000 items take about 40 seconds), the window says it is a large
collection, what it is doing, how far it has got and about how long is left."""
import os
import tempfile
import unittest
import qt_cleanup  # noqa: F401  (deletes leftover windows before Qt shuts down)
from unittest import mock


class OpeningTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        from turbocat import gui
        cls.app = QApplication.instance() or QApplication([])
        gui._pick_theme()
        cls.gui = gui

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        with mock.patch.object(self.gui.QTimer, "singleShot"):
            self.w = self.gui.MainWindow(os.path.join(self.tmp.name, "cat.db"))
        self.w.loader.wait(5000)
        self.app.processEvents()

    def tearDown(self):
        self.w.open_timer.stop()
        self.w.worker = None
        self.w.cat.db.close()
        self.w.deleteLater()
        self.app.processEvents()
        self.tmp.cleanup()

    def test_seconds(self):
        s = self.gui._seconds
        self.assertEqual(s(1), "5 seconds")
        self.assertEqual(s(23), "25 seconds")
        self.assertEqual(s(60), "1 minute")
        self.assertEqual(s(131), "2 minutes 10 seconds")

    def test_a_big_catalogue_says_so_and_shows_how_far(self):
        self.w.cat.set_meta("open_seconds", 38.0)
        real = self.w.cat.db

        class Count:                       # 78,055 top-level items, without making them
            def execute(self, sql, *a):
                if "COUNT(*) FROM media WHERE parent_id IS NULL" in sql:
                    return real.execute("SELECT 78055")
                return real.execute(sql, *a)

            def __getattr__(self, name):
                return getattr(real, name)

        self.w.cat.db = Count()
        try:
            self.w._opening_start()
        finally:
            self.w.cat.db = real
        self.assertIn("78,055 items", self.w.open_head.text())
        self.assertIn("large collection", self.w.open_about.text())
        self.assertIn("about 40 seconds last time", self.w.open_about.text())
        self.w.open_started -= 10                       # 10 seconds in, a quarter of the way
        self.w._opening_progress(0.25, "Working out which damaged disks can be repaired")
        self.assertEqual(self.w.open_bar.value(), 250)
        self.assertIn("Working out which damaged disks can be repaired", self.w.open_step.text())
        self.assertIn("about 30 seconds left", self.w.open_step.text())
        self.w._opening_end()
        self.assertFalse(self.w.open_timer.isActive())

    def test_load_items_reports_its_progress(self):
        seen = []
        self.gui.load_items(self.w.cat, lambda f, what: seen.append((f, what)))
        fractions = [f for f, _ in seen]
        self.assertEqual(fractions, sorted(fractions))
        self.assertEqual(fractions[0], 0.0)
        self.assertEqual(fractions[-1], 1.0)


if __name__ == "__main__":
    unittest.main()
