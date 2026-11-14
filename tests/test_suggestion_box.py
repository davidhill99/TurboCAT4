"""The suggestion box is easy to find: a "Got an idea?" link always in the status bar, a button
in About, and one reminder (only one) after ten starts."""
import os
import tempfile
import unittest
import qt_cleanup  # noqa: F401  (deletes leftover windows before Qt shuts down)
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class SuggestionBoxTest(unittest.TestCase):
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
        self.ideas = []
        self.w.report = lambda kind="problem", error="", happened="": self.ideas.append(kind)

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

    def test_the_status_bar_link_opens_the_idea_form(self):
        self.assertIn("Got an idea?", self.w.idea_link.text())
        self.w.idea_link.linkActivated.emit("idea")
        self.assertEqual(self.ideas, ["idea"])

    def test_about_has_a_suggest_button(self):
        dlg = self.gui.AboutDialog(self.w, self.w.cat, self.w.db_path)
        btn = next(b for b in dlg.findChildren(self.gui.QPushButton) if b.text() == "Suggest an idea…")
        btn.click()
        self.assertEqual(self.ideas, ["idea"])

    def test_about_and_help_link_to_ko_fi(self):
        from turbocat import DONATE
        dlg = self.gui.AboutDialog(self.w, self.w.cat, self.w.db_path)
        self.assertIn(DONATE, dlg.findChild(self.gui.QLabel, "supportLink").text())
        help_menu = next(a.menu() for a in self.w.menuBar().actions() if a.text() == "&Help")
        self.assertTrue(any(a.text().startswith("&Support") for a in help_menu.actions()))

    def test_the_reminder_comes_once_after_ten_starts(self):
        shown = []
        with mock.patch.object(self.gui.QTimer, "singleShot", lambda ms, fn: shown.append(fn)), \
                mock.patch.object(self.gui.IdeaNudge, "show_above", lambda s, w: shown.append("nudge")):
            for _ in range(self.w.IDEA_NUDGE_AT - 1):
                self.w._count_start()
            self.assertEqual(shown, [])                        # not yet
            self.w._count_start()                              # the tenth start
            self.assertEqual(len(shown), 1)
            fire = shown.pop()
            self.w.show()
            self.app.processEvents()
            shown.clear()                                      # the window's own timers
            self.w._busy = lambda: ""
            fire()                                             # the reminder's timer fires
            self.assertEqual(shown, ["nudge"])
            shown.clear()
            self.w._count_start()                              # the eleventh: never again
            self.assertEqual(shown, [])

    def test_the_reminder_waits_while_busy(self):
        self.w.show()
        self.app.processEvents()
        self.w._busy = lambda: "the scan"
        later = []
        with mock.patch.object(self.gui.QTimer, "singleShot", lambda ms, fn: later.append(ms)):
            self.w._idea_nudge()
        self.assertEqual(later, [60000])
        self.assertFalse(self.w.cat.get_meta("idea_nudged", False))


if __name__ == "__main__":
    unittest.main()
