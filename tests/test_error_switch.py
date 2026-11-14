"""The error reports' kill switch: boxes stop when the tester says so (for good) or when they come
too often (for the session), and when there was a real reason TurboCAT offers - never sends - a
report saying why."""
import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from turbocat import feedback


def err(message, kind=ValueError):
    try:
        raise kind(message)
    except Exception:
        return sys.exc_info()


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class CrashLogTest(unittest.TestCase):
    def test_a_storm_is_three_boxes_or_twenty_errors_in_ten_minutes(self):
        clock = Clock()
        log = feedback.CrashLog(clock)
        for _ in range(2):
            log.add(*err("x"))
            log.box_shown()
        self.assertFalse(log.storm())
        log.box_shown()
        self.assertTrue(log.storm())
        clock.now += 11 * 60                       # long ago now
        self.assertFalse(log.storm())
        for _ in range(20):
            log.add(*err("same again"))
        self.assertTrue(log.storm())

    def test_the_reason_says_what_happened_and_where(self):
        clock = Clock()
        log = feedback.CrashLog(clock)
        for _ in range(3):
            log.add(*err("no colour"))
        log.add(*err("'accent'", KeyError))
        clock.now += 5 * 60
        text = log.reason("auto")
        self.assertIn("paused its error reports by itself", text)
        self.assertIn("4 unexpected errors in 5 minutes", text)
        self.assertIn("3x ValueError: no colour", text)
        self.assertIn("test_error_switch.py", text)          # where in the code
        self.assertIn("switched error reports off", log.reason("user"))


class WindowSwitchTest(unittest.TestCase):
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
        self.boxes, self.reports = [], []
        self.w.report = lambda kind="problem", error="", happened="": self.reports.append((error, happened))

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

    def answer(self, tick=False, press=None):
        """Patch the message boxes: note each, tick its checkbox, press a button by its words."""
        boxes = self.boxes

        def exec_(box):
            boxes.append(box.objectName())     # (macOS shows no titles on message boxes)
            if tick and box.checkBox() is not None:
                box.checkBox().setChecked(True)
            for b in box.buttons():
                if press and b.text() == press:
                    b.click()
            return 0
        return mock.patch.object(self.gui.QMessageBox, "exec", exec_)

    def test_dont_show_again_turns_them_off_and_offers_the_reason(self):
        with self.answer(tick=True, press="Report it…"):
            self.w.show_crash(*err("first"))
        # the error box (whose own Report it… opened the form), then no second offer
        self.assertEqual(self.boxes, ["crashBox"])
        self.assertFalse(self.w.error_reports_on())
        self.assertFalse(self.w.act_errors.isChecked())
        self.boxes.clear()
        with self.answer():
            self.w.show_crash(*err("second"))
        self.assertEqual(self.boxes, [])                       # off: no box at all
        self.assertIn("error reports are off", self.w.foot_left.text())

    def test_turning_off_after_errors_offers_a_report_with_the_reason(self):
        with self.answer(tick=True, press="Carry on"):
            self.w.show_crash(*err("first"))
        self.assertEqual(self.boxes[-1], "errorReportsBox")      # the offer
        self.assertEqual(self.reports, [])                     # nothing unless asked
        self.w.switch_offered = False
        with self.answer(press="Report it…"):
            self.w._offer_switch_report("user")
        error, happened = self.reports[-1]
        self.assertIn("The tester switched error reports off", error)
        self.assertIn("ValueError: first", happened)

    def test_no_offer_without_a_reason(self):
        with self.answer():
            self.w.set_error_reports(False)
        self.assertEqual(self.boxes, [])                       # no errors: nothing to say

    def test_too_many_boxes_pause_them_for_the_session(self):
        with self.answer(press="Carry on"):
            for i in range(feedback.STORM_SHOWN):
                self.w.show_crash(*err(f"problem {i}"))
            self.assertEqual(len(self.boxes), feedback.STORM_SHOWN)
            self.w.show_crash(*err("one more"))
        self.assertEqual(self.boxes[-1], "errorReportsBox")     # paused, with the offer
        self.assertTrue(self.w.crash_paused)
        self.assertTrue(self.w.error_reports_on())             # only for this session
        n = len(self.boxes)
        with self.answer():
            self.w.show_crash(*err("and another"))
        self.assertEqual(len(self.boxes), n)

    def test_the_same_error_again_is_not_shown_twice(self):
        with self.answer(press="Carry on"):
            self.w.show_crash(*err("same"))
            self.w.show_crash(*err("same"))
        self.assertEqual(self.boxes, ["crashBox"])


if __name__ == "__main__":
    unittest.main()
