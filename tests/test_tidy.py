"""A tidied copy: a disk whose files all read but whose index (directory) has errors is rebuilt
with the same files in a fresh, correct index. The original is never changed."""
import hashlib
import os
import struct
import tempfile
import unittest

from turbocat import readers, repair, scanner
from turbocat.catalogue import Catalogue
from test_repair import make_adf


def break_parent(adf, name):
    """Point a file's header block at the wrong parent, as a decayed disk might (checksum fixed,
    so the block itself still reads)."""
    for blk in range(2, len(adf) // 512):
        b = adf[blk * 512:(blk + 1) * 512]
        if struct.unpack(">I", b[0:4])[0] == 2 and struct.unpack(">i", b[508:512])[0] == -3 \
                and b[433:433 + b[432]] == name.encode():
            b = bytearray(b)
            b[500:504] = struct.pack(">I", 3)                    # a block that isn't its folder
            b[20:24] = b"\0\0\0\0"
            total = sum(struct.unpack(">128I", bytes(b))) & 0xFFFFFFFF
            b[20:24] = struct.pack(">I", (-total) & 0xFFFFFFFF)
            adf[blk * 512:(blk + 1) * 512] = b
            return adf
    raise AssertionError(name + " not found")


class TidyTest(unittest.TestCase):
    def test_a_tidied_copy_has_a_correct_index_and_the_same_files(self):
        with tempfile.TemporaryDirectory() as t:
            files = {"ReadMe": b"Hello\n" * 100, "c/Tool": bytes(range(256)) * 8}
            adf = break_parent(make_adf("Tools", files), "ReadMe")
            src = os.path.join(t, "Tools (1990)(PD).adf")
            with open(src, "wb") as f:
                f.write(adf)
            before = hashlib.sha1(adf).hexdigest()
            cat = Catalogue(os.path.join(t, "c.db"))
            scanner.scan([src], cat, progress=None)
            top = cat.db.execute("SELECT id FROM media WHERE parent_id IS NULL").fetchone()[0]
            p = repair.tidy_plan(cat, top)
            self.assertIsNotNone(p)                              # the scan found the index error
            self.assertIsNone(repair.plan(cat, top))             # but no damaged files
            log = os.path.join(t, "log.csv")
            res = repair.build(cat, p, out_dir=os.path.join(t, "out"), log=log)
            new = readers.read_adf(open(res.path, "rb").read())
            self.assertEqual((new.problems, new.fs_issues), ([], []))
            got = {e.path: e.read() for e in new.files if not e.is_dir and e.read}
            for path, data in files.items():
                self.assertEqual(got[path], data)
            self.assertIn(b"tidied by TurboCAT", got[repair.MARKER])
            self.assertEqual(repair.log_for(res.sha1, log), [("(the disk's index)", repair.TIDIED)])
            self.assertEqual(hashlib.sha1(open(src, "rb").read()).hexdigest(), before)   # untouched
            cat.db.close()


if __name__ == "__main__":
    unittest.main()
