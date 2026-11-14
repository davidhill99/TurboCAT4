"""TurboView opens a 1280x512 screen in Amiberry, but a 640x512 one in FS-UAE, which shows only
part of a super-hires screen."""
import os
import tempfile
import unittest

from turbocat import emulator, turboview


class TurboViewScreenTest(unittest.TestCase):
    def test_install_writes_the_screen_mode(self):
        with tempfile.TemporaryDirectory() as t:
            for screen in ("HIGH", "SUPER"):
                turboview.install(t, screen)
                with open(os.path.join(t, "S", "Startup-Sequence")) as f:
                    self.assertIn(f"SCREEN={screen}", f.read())

    def test_fs_uae_isnt_asked_for_super_hires(self):
        cmd = emulator.turboview_command("fs-uae", ["fs-uae"], None, "/tmp", [], "window")
        self.assertFalse(any("superhires" in c for c in cmd))
        cmd = emulator.turboview_command("amiberry", ["amiberry"], None, "/tmp", [], "window")
        self.assertIn("gfx_resolution=superhires", cmd)


if __name__ == "__main__":
    unittest.main()
