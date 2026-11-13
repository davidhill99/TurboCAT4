"""Play never hands the emulator an original disk image: a game saving to its disk changes a copy.
FS-UAE keeps its own files in TurboCAT's folder, not in ~/Documents/FS-UAE."""
import hashlib
import os
import tempfile
import unittest

from turbocat import emulator, scanner
from turbocat.catalogue import Catalogue
from test_repair import make_adf


class PlayCopyTest(unittest.TestCase):
    def test_the_emulator_gets_a_copy(self):
        with tempfile.TemporaryDirectory() as t:
            old = emulator.PLAY_DIR
            emulator.PLAY_DIR = os.path.join(t, "play")
            try:
                src = os.path.join(t, "Game.adf")
                with open(src, "wb") as f:
                    f.write(make_adf("Game", {"Data": b"x" * 2000}))
                cat = Catalogue(os.path.join(t, "c.db"))
                scanner.scan([src], cat, progress=None)
                top = cat.db.execute("SELECT id FROM media WHERE parent_id IS NULL").fetchone()[0]
                files, _, _, _ = emulator.disk_files(cat, [top])
                self.assertEqual(len(files), 1)
                self.assertNotEqual(files[0], src)
                self.assertTrue(files[0].startswith(emulator.PLAY_DIR))
                same = lambda p: hashlib.sha1(open(p, "rb").read()).hexdigest()
                self.assertEqual(same(files[0]), same(src))
                cat.db.close()
            finally:
                emulator.PLAY_DIR = old

    def test_fs_uae_uses_turbocats_folder(self):
        cmd = emulator.command("fs-uae", ["fs-uae"], "A500", None, ["d.adf"])
        self.assertIn(f"--base_dir={emulator.FSUAE_DIR}", cmd)
        self.assertNotIn("Documents", emulator.FSUAE_DIR)


if __name__ == "__main__":
    unittest.main()
