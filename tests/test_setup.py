"""Check setup: commands and advice for each kind of computer, and the summary.

Run with:  ~/turbocat-env/bin/python -m unittest discover -s tests
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from turbocat import emulator, music, setup     # noqa: E402

NOTHING = dict(emulators={}, kickstarts={}, music_versions={"libopenmpt": None, "libxmp": None})


def checks(system):
    with mock.patch.object(setup, "system", return_value=system), \
            mock.patch("shutil.which", return_value=None):
        return {c.name: c for c in setup.run(**NOTHING)}


class SetupTest(unittest.TestCase):
    def test_linux_gets_package_commands(self):
        c = checks("linux-apt")
        self.assertEqual(c["libopenmpt"].command, "sudo apt install libopenmpt0")
        self.assertEqual(c["xdms"].command, "sudo apt install xdms")
        self.assertEqual(checks("linux-dnf")["libxmp"].command, "sudo dnf install libxmp")

    def test_mac_gets_homebrew_and_windows_gets_downloads(self):
        self.assertEqual(checks("mac")["libopenmpt"].command, "brew install libopenmpt")
        win = checks("windows")
        self.assertEqual(win["libopenmpt"].command, "")
        self.assertIn("libopenmpt.dll", win["libopenmpt"].advice)
        self.assertIn("WinUAE", win["Amiga emulator"].advice)

    def test_summary_counts_only_what_matters(self):
        c = checks("linux-apt")
        headline, important = setup.summary(list(c.values()))
        names = {x.name for x in important}
        self.assertIn("Amiga emulator", names)
        self.assertIn("Kickstart ROMs", names)
        self.assertNotIn("libxmp", names)                    # optional extras don't nag

    def test_everything_present(self):
        found = setup.run(emulators={"fs-uae": ["fs-uae"]},
                          kickstarts={"A500": "a", "A600": "b", "A1200": "c"},
                          music_versions={"libopenmpt": "0.7", "libxmp": "4.6"})
        important = [c for c in found if c.status != setup.OK and c.important]
        self.assertEqual(important, [])


if __name__ == "__main__":
    unittest.main()


class DisplayTest(unittest.TestCase):
    def test_screen_choices_for_each_emulator(self):
        self.assertEqual(emulator.display_args("amiberry", "window"), [])
        full = emulator.display_args("amiberry", "fullscreen")
        self.assertIn("gfx_fullscreen_amiga=fullwindow", full)
        self.assertIn("gfx_keep_aspect=true", full)
        self.assertIn("gfx_width_windowed=1920", emulator.display_args("amiberry", "1080p"))
        self.assertIn("--fullscreen=1", emulator.display_args("fs-uae", "fullscreen"))
        cmd = emulator.command("amiberry", ["amiberry"], "A500", None, ["/x/a.adf"], display="fullscreen")
        self.assertIn("gfx_fullscreen_amiga=fullwindow", cmd)
