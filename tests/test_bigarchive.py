"""A big archive of archives shows progress while it is read, and stopping part way through
leaves it out of the catalogue so the next scan reads it again."""
import io
import os
import tempfile
import unittest
import zipfile

from turbocat.catalogue import Catalogue
from turbocat import scanner


def adf(fill):
    return bytes([fill]) * 901120


def zip_of(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


class BigArchiveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        inner = {f"Disk {n}.zip": zip_of({f"Disk {n}.adf": adf(n)}) for n in range(1, 9)}
        self.path = os.path.join(self.tmp.name, "collection.zip")
        with open(self.path, "wb") as f:
            f.write(zip_of(inner))
        self.cat = Catalogue(os.path.join(self.tmp.name, "cat.db"))
        self.old_wait = scanner.time.monotonic

    def tearDown(self):
        self.cat.db.close()
        self.tmp.cleanup()

    def test_progress_inside(self):
        seen = []
        clock = iter(range(0, 10000))
        scanner.time.monotonic = lambda: next(clock)      # every call is "a while later"
        try:
            scanner.scan([self.path], self.cat, progress=None,
                         step=lambda *a: seen.append((a[3], a[5], a[0])))
        finally:
            scanner.time.monotonic = self.old_wait
        inside = [p for _b, p, ph in seen if " › " in p]
        self.assertTrue(all(ph.startswith("inside") for _b, p, ph in seen if " › " in p))
        self.assertTrue(any(p.endswith("Disk 5.zip") for p in inside), inside)
        self.assertTrue(any("Disk 3.zip › Disk 3.adf" in p for p in inside), inside)
        done = [b for b, p, _ph in seen if " › " in p]
        self.assertEqual(done, sorted(done))               # the bar only moves forward
        self.assertEqual(self.cat.db.execute("SELECT COUNT(*) FROM media").fetchone()[0], 17)

    def test_stop_part_way(self):
        class Stop(Exception):
            pass

        def step(*a):
            if "Disk 4.zip" in a[5]:
                raise Stop()
        scanner.time.monotonic = iter(range(0, 10000)).__next__
        try:
            with self.assertRaises(Stop):
                scanner.scan([self.path], self.cat, progress=None, step=step)
        finally:
            scanner.time.monotonic = self.old_wait
        self.cat.commit()
        self.assertEqual(self.cat.db.execute("SELECT COUNT(*) FROM media").fetchone()[0], 0)
        st = os.stat(self.path)
        self.assertFalse(self.cat.known_unchanged(self.path, st.st_size, st.st_mtime))

    def test_big_archives_asked_first(self):
        asked = []
        old = scanner.BIG_ARCHIVE
        scanner.BIG_ARCHIVE = 1000            # the test archive counts as big
        try:
            s = scanner.scan([self.tmp.name], self.cat, progress=None,
                             confirm_big=lambda big, rate: asked.append((big, rate)) or [])
        finally:
            scanner.BIG_ARCHIVE = old
        self.assertEqual([p for p, _k, _s in asked[0][0]], [self.path])
        self.assertGreater(asked[0][1], 0)
        self.assertEqual(s["held_back"], [self.path])
        self.assertEqual(self.cat.db.execute("SELECT COUNT(*) FROM media").fetchone()[0], 0)
        # said yes: it is read, and the reading speed is not remembered for a quick file
        scanner.BIG_ARCHIVE = 1000
        try:
            s = scanner.scan([self.tmp.name], self.cat, progress=None,
                             confirm_big=lambda big, rate: [p for p, _k, _s in big])
        finally:
            scanner.BIG_ARCHIVE = old
        self.assertNotIn("held_back", s)
        self.assertEqual(s["scanned"], 1)

    def test_picture_search_reads_the_file_once(self):
        from turbocat import pictures
        scanner.scan([self.path], self.cat, progress=None)
        top = self.cat.db.execute("SELECT * FROM media WHERE parent_id IS NULL").fetchone()
        reads, seen = [], []
        real = pictures._container_data
        pictures._container_data = lambda cat, chain: reads.append(chain) or real(cat, chain)
        try:
            pictures.find_on_item(self.cat, top, lambda d, n, name: seen.append((d, n)))
        finally:
            pictures._container_data = real
        self.assertEqual(len(reads), 1)                    # the archive itself, once
        self.assertEqual(seen[-1], (16, 16))              # 8 zips and the 8 disks in them

    def test_picture_search_stops_part_way(self):
        from turbocat import pictures
        scanner.scan([self.path], self.cat, progress=None)
        calls = [0]

        def stop():
            calls[0] += 1
            return calls[0] > 3
        res = pictures.build(self.cat, stop=stop)
        self.assertTrue(res["stopped"])
        self.assertEqual(res["looked"], 0)
        self.assertEqual(self.cat.db.execute(
            "SELECT COUNT(*) FROM thumbs WHERE icon_from IS NOT NULL").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
