"""Names that aren't valid UTF-8 (an Amiga file called "Français" in Latin-1, unpacked by lha) are
stored as proper text instead of stopping the scan."""
import os
import tempfile
import unittest

from turbocat import readers
from turbocat.catalogue import Catalogue

LATIN1 = b"Fran\xe7ais.txt".decode("utf-8", "surrogateescape")     # as os.walk gives it


class OddNamesTest(unittest.TestCase):
    def test_latin1_name_becomes_text(self):
        self.assertEqual(readers.amiga_text(LATIN1), "Français.txt")
        self.assertEqual(readers.amiga_text("Plain.txt"), "Plain.txt")
        self.assertEqual(readers.amiga_text(42), 42)

    def test_catalogue_stores_it(self):
        with tempfile.TemporaryDirectory() as t:
            cat = Catalogue(os.path.join(t, "c.db"))
            mid = cat.add_media({"source": "/x/Disk.lha", "kind": "lha", "status": "ok",
                                 "inner_path": LATIN1,
                                 "files": [{"path": "docs/" + LATIN1, "size": 3, "date": None,
                                            "comment": LATIN1, "protect": "", "sha1": None,
                                            "is_dir": False}]})
            cat.commit()
            row = cat.db.execute("SELECT path, comment FROM files WHERE media_id=?", (mid,)).fetchone()
            self.assertEqual(tuple(row), ("docs/Français.txt", "Français.txt"))
            cat.db.close()


if __name__ == "__main__":
    unittest.main()
