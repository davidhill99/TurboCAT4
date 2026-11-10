"""Disk > Recheck: just the chosen items and the folder they are in, not every folder."""
import os
import tempfile
import unittest

from turbocat.catalogue import Catalogue
from turbocat import scanner


def adf(fill):
    return bytes([fill]) * 901120


class RecheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.game = os.path.join(self.root, "Superfrog")
        self.other = os.path.join(self.root, "Other")
        os.makedirs(self.game)
        os.makedirs(self.other)
        for n in (1, 2, 3):
            self._write(self.game, f"Superfrog Disk {n}.adf", adf(n))
        self._write(self.other, "Other.adf", adf(9))
        self.cat = Catalogue(os.path.join(self.root, "cat.db"))
        scanner.scan([self.root], self.cat, progress=None)

    def tearDown(self):
        self.cat.db.close()
        self.tmp.cleanup()

    def _write(self, folder, name, data):
        path = os.path.join(folder, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def _sha(self, path):
        r = self.cat.db.execute("SELECT sha1 FROM media WHERE source=? AND parent_id IS NULL",
                                (path,)).fetchone()
        return r and r[0]

    def test_recheck_one_set(self):
        disk2 = os.path.join(self.game, "Superfrog Disk 2.adf")
        old = self._sha(disk2)
        st = os.stat(disk2)
        self._write(self.game, "Superfrog Disk 2.adf", adf(22))          # replaced...
        os.utime(disk2, (st.st_atime, st.st_mtime))                       # ...keeping its date
        os.remove(os.path.join(self.game, "Superfrog Disk 3.adf"))        # deleted
        disk4 = self._write(self.game, "Superfrog Disk 4.adf", adf(4))    # added
        os.makedirs(os.path.join(self.game, "Extras"))
        extra = self._write(os.path.join(self.game, "Extras"), "Extra.adf", adf(5))
        other = self._write(self.other, "Other 2.adf", adf(10))           # another folder
        roots = self.cat.scan_roots()

        s = scanner.recheck([os.path.join(self.game, "Superfrog Disk 1.adf"), disk2], self.cat,
                            progress=None)
        self.cat.commit()
        self.assertNotEqual(self._sha(disk2), old)          # read again though its date is the same
        self.assertIsNotNone(self._sha(disk4))              # the new disk beside it
        self.assertEqual(len(s["removed"]), 1)              # the deleted one
        self.assertIsNone(self._sha(extra))                 # not the folders inside
        self.assertIsNone(self._sha(other))                 # nor other folders
        self.assertEqual(s["scanned"], 3)                   # disks 1, 2 and 4
        self.assertEqual(self.cat.scan_roots(), roots)      # Rescan's folders unchanged


if __name__ == "__main__":
    unittest.main()
