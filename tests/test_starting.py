"""On a big catalogue the start-up check reads the whole file (45 seconds for 850 MB after a
restart), so TurboCAT says what it is doing instead of seeming not to start."""
import os
import tempfile
import time
import unittest
import qt_cleanup  # noqa: F401  (deletes leftover windows before Qt shuts down)
from unittest import mock


class StartingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        from turbocat import gui
        cls.app = QApplication.instance() or QApplication([])
        gui._pick_theme()
        cls.gui = gui

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "cat.db")
        with open(self.db, "wb") as f:
            f.write(b"\0" * (3 << 20))

    def tearDown(self):
        self.tmp.cleanup()

    def _notes(self):
        from PySide6.QtWidgets import QApplication
        return [w for w in QApplication.topLevelWidgets()
                if w.objectName() == "startingNote" and w.isVisible()]

    def test_a_slow_check_shows_a_note_and_gives_its_result(self):
        seen = []

        def slow():
            time.sleep(0.4)
            return True, ""

        real = self.gui.QApplication.processEvents

        def watch(*a):
            seen.extend(self._notes())
            return real(*a)

        with mock.patch.object(self.gui, "STARTING_NOTE_AFTER", 0.05), \
                mock.patch.object(self.gui.QApplication, "processEvents", watch):
            self.assertEqual(self.gui._while_starting(slow, self.db), (True, ""))
        self.assertTrue(seen)
        self.assertEqual(self._notes(), [])                  # gone once the check is done

    def test_a_quick_check_shows_nothing(self):
        with mock.patch.object(self.gui, "QWidget") as widget:
            self.assertEqual(self.gui._while_starting(lambda: (False, "bad"), self.db), (False, "bad"))
        widget.assert_not_called()

    def test_an_error_in_the_check_is_passed_on(self):
        def broken():
            raise OSError("disk gone")
        with self.assertRaises(OSError):
            self.gui._while_starting(broken, self.db)


if __name__ == "__main__":
    unittest.main()
