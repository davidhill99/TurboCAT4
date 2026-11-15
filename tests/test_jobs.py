"""Background work runs in processes of its own (so it can't slow the window down), reports back
as signals in the window, and stops when asked. Run for real here, on an empty catalogue (nothing
to fetch: no online look-ups are switched on)."""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import qt_cleanup  # noqa: F401,E402  (deletes leftover windows before Qt shuts down)

from turbocat.catalogue import Catalogue   # noqa: E402


class JobsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "cat.db")
        Catalogue(self.db).db.close()

    def tearDown(self):
        self.tmp.cleanup()

    def run_worker(self, w, limit=90):
        got = {"progress": [], "done": [], "failed": []}
        w.progress.connect(lambda *a: got["progress"].append(a))
        w.done.connect(got["done"].append)
        w.failed.connect(got["failed"].append)
        w.start()
        end = time.monotonic() + limit
        while not w.isFinished() and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.05)
        w.wait(5000)
        self.app.processEvents()
        return got

    def test_the_picture_search_runs_in_its_own_process(self):
        from turbocat.jobs import PictureWorker
        w = PictureWorker(self.db)
        got = self.run_worker(w)
        self.assertEqual(got["failed"], [])
        self.assertEqual(len(got["done"]), 1)
        res = got["done"][0]
        self.assertEqual(res["items"], [])              # the list, read for the window
        self.assertIn(("reading", 0, 0, ""), got["progress"])
        self.assertEqual(w.exit_code, 0)

    def test_flags_can_change_while_it_runs(self):
        from turbocat.jobs import PictureWorker
        w = PictureWorker(self.db)
        self.assertFalse(w.online)
        w.online = True                                  # Tools > Find pictures online, meanwhile
        self.assertTrue(w.online)

    def test_stopped_before_it_starts_work(self):
        from turbocat.jobs import PictureWorker
        w = PictureWorker(self.db)
        w.stop_wanted = True
        got = self.run_worker(w)
        self.assertEqual(got["failed"], [])
        self.assertNotIn("items", got["done"][0] if got["done"] else {})


if __name__ == "__main__":
    unittest.main()
