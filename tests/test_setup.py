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


class FeatureTest(unittest.TestCase):
    """What works, feature by feature, and what that means for this collection."""

    def feats(self, missing=(), imp=None, roms=None):
        cs = [setup.Check(n, "", setup.MISSING if n in missing else setup.OK) for n in (
            "amitools", "lhafile", "lha (lhasa)", "xdms", "Qt Multimedia", "libopenmpt", "libxmp",
            "Amiga emulator", "Kickstart ROMs", "TurboView", "List of Amiga disks")]
        return {f.name: f for f in setup.features(cs, imp or {}, roms or {})}

    def test_everything_works(self):
        roms = {"A500": "a", "A600": "b", "A1200": "c"}
        f = self.feats(roms=roms)
        self.assertEqual({x.status for x in f.values()}, {setup.OK})
        self.assertEqual(setup.overall(list(f.values())), setup.OK)

    def test_a_missing_part_matters_only_if_the_collection_needs_it(self):
        f = self.feats(missing=("xdms",), imp={"dms": 0})
        self.assertEqual(f["DMS disk images"].status, setup.OK)          # no DMS images: not needed
        f = self.feats(missing=("xdms",), imp={"dms": 9})
        self.assertEqual(f["DMS disk images"].status, setup.MISSING)
        self.assertIn("9 DMS images", f["DMS disk images"].effect)
        self.assertEqual(f["Copying to a Gotek stick"].status, setup.PARTIAL)

    def test_kickstarts_say_how_many_disks_need_them(self):
        f = self.feats(imp={"A1200": 31, "A600": 0}, roms={"A500": "x"})
        e = f["Playing disks in an emulator"]
        self.assertEqual(e.status, setup.PARTIAL)
        self.assertIn("31 AGA disks in your collection need an A1200 Kickstart 3.x", e.detail)
        self.assertNotIn("ECS", e.detail)

    def test_no_emulator(self):
        f = self.feats(missing=("Amiga emulator",))
        self.assertEqual(f["Playing disks in an emulator"].status, setup.MISSING)
        self.assertEqual(f["TurboView"].status, setup.MISSING)
        self.assertEqual(setup.overall(list(f.values())), setup.MISSING)


class BundledToolTest(unittest.TestCase):
    """Windows and macOS packages carry their own lha and xdms in a bin folder, found first."""

    def test_bundled_copy_comes_first(self):
        import tempfile
        from turbocat import tools
        with tempfile.TemporaryDirectory() as d:
            exe = os.path.join(d, "xdms")
            with open(exe, "w") as f:
                f.write("#!/bin/sh\n")
            os.chmod(exe, 0o755)
            with mock.patch.object(tools, "bundled_dirs", return_value=[d]):
                self.assertEqual(tools.which("xdms"), exe)
            with mock.patch.object(tools, "bundled_dirs", return_value=[]), \
                    mock.patch("shutil.which", return_value="/usr/bin/xdms"):
                self.assertEqual(tools.which("xdms"), "/usr/bin/xdms")


if __name__ == "__main__":
    unittest.main()
