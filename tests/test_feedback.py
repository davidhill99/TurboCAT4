"""Report a problem / Suggest an idea, and the crash catcher: nothing personal goes in a report,
the GitHub link carries the form's fields, a huge error still fits, and errors reach the window."""
import os
import sys
import unittest
import qt_cleanup  # noqa: F401  (deletes leftover windows before Qt shuts down)
import urllib.parse
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from turbocat import feedback


class FeedbackTest(unittest.TestCase):
    def test_home_folder_and_user_name_are_taken_out(self):
        home = os.path.expanduser("~")
        with mock.patch("getpass.getuser", return_value="zorro"):
            text = feedback.scrub(f"Can't read {home}/Amiga/Game.adf (asked by zorro, not zorrotron)")
        self.assertNotIn(home, text)
        self.assertIn("~/Amiga/Game.adf", text)
        self.assertIn("asked by <user>", text)
        self.assertIn("zorrotron", text)                 # only the whole word

    def test_details_say_what_tester_would_not_know(self):
        text = feedback.details(items=1406)
        self.assertIn("TurboCAT", text)
        self.assertIn("Python", text)
        self.assertIn("1,406 items", text)

    def test_link_fills_the_github_form(self):
        url = feedback.issue_url("problem", "Worms asks for disk 3",
                                 {"what": "Pressing Play", "happened": "It asks for disk 3", "expected": ""},
                                 "TurboCAT 4")
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        self.assertTrue(url.startswith(feedback.REPO + "/issues/new?"))
        self.assertEqual(q["template"], ["problem.yml"])
        self.assertEqual(q["title"], ["Worms asks for disk 3"])
        self.assertEqual(q["happened"], ["It asks for disk 3"])
        self.assertNotIn("expected", q)                  # empty boxes are left out
        self.assertEqual(q["details"], ["TurboCAT 4"])

    def test_a_huge_error_is_cut_to_fit(self):
        url = feedback.issue_url("problem", "Crash", {"happened": "x"}, "Traceback line\n" * 3000)
        self.assertLessEqual(len(url), feedback.MAX_URL)
        self.assertIn("Copy+details+has+it+all", url.replace("%20", "+"))

    def test_the_catcher_passes_errors_on(self):
        seen = []
        old_hook, old_thread = sys.excepthook, __import__("threading").excepthook
        try:
            with mock.patch("sys.stderr"):
                hook = feedback.install_catcher(lambda *a: seen.append(a[0]))
                try:
                    raise ValueError("boom")
                except ValueError:
                    hook(*sys.exc_info())
        finally:
            sys.excepthook, __import__("threading").excepthook = old_hook, old_thread
        self.assertEqual(seen, [ValueError])


class FeedbackDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        from turbocat import gui
        cls.app = QApplication.instance() or QApplication([])
        gui._pick_theme()

    def tearDown(self):
        """Delete the test's forms now: left to Python's shutdown, Qt crashes on the way out."""
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QDialog
        for w in self.app.topLevelWidgets():
            if isinstance(w, QDialog):
                w.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)

    def test_the_form_shows_what_will_be_sent(self):
        from turbocat import gui
        dlg = gui.FeedbackDialog(None, "problem", items=12)
        self.assertFalse(dlg.open_btn.isEnabled())       # nothing written yet
        dlg.boxes["happened"].setPlainText(f"It froze reading {os.path.expanduser('~')}/x.adf")
        self.assertTrue(dlg.open_btn.isEnabled())        # the first line serves as the title
        shown = dlg.preview.toPlainText()
        self.assertIn("It froze reading ~/x.adf", shown)
        self.assertIn("12 items", shown)

    def test_an_error_fills_the_form(self):
        from turbocat import gui
        dlg = gui.FeedbackDialog(None, "problem", error="Traceback: KeyError 'accent'")
        self.assertIn("stopped with an error", dlg.boxes["happened"].toPlainText())
        self.assertIn("KeyError 'accent'", dlg.preview.toPlainText())

    def test_how_turboview_went_has_its_own_boxes(self):
        from turbocat import gui
        dlg = gui.FeedbackDialog(None, "amiga")
        self.assertEqual(list(dlg.boxes), ["amiga", "tried", "went"])
        self.assertIn("template=amiga.yml", feedback.issue_url("amiga", "A1200 works", {"went": "fine"}, "x"))

    def test_ideas_have_their_own_boxes(self):
        from turbocat import gui
        dlg = gui.FeedbackDialog(None, "idea")
        self.assertEqual(list(dlg.boxes), ["idea", "why"])


if __name__ == "__main__":
    unittest.main()
