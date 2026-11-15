"""Windows and macOS: TurboCAT's files in each system's normal place (Linux unchanged), finding
WinUAE and the macOS emulator apps, starting WinUAE, Gotek sticks from Qt's drive list, no console
windows, emulators that outlive TurboCAT, and folder names without regard to case on Windows.
These run on every system (GitHub runs them on real Windows and macOS too)."""
import os
import sys
import tempfile
import unittest
from unittest import mock

from turbocat import emulator, folders, gotek, paths


def as_system(name):
    return mock.patch.object(paths, "system", return_value=name)


class PathsTest(unittest.TestCase):
    def test_linux_keeps_its_places(self):
        with as_system("linux"):
            home = os.path.expanduser("~")
            self.assertEqual(paths.default_db(), os.path.join(home, "turbocat.db"))
            self.assertEqual(paths.data_dir(), os.path.join(home, ".local", "share", "turbocat"))
            self.assertEqual(paths.cache_dir(), os.path.join(home, ".cache", "turbocat"))

    def test_windows_uses_appdata(self):
        with as_system("windows"), mock.patch.dict(os.environ, {"APPDATA": "C:/U/AppData/Roaming",
                                                               "LOCALAPPDATA": "C:/U/AppData/Local"}):
            self.assertEqual(paths.data_dir(), os.path.join("C:/U/AppData/Roaming", "TurboCAT"))
            self.assertEqual(paths.cache_dir(), os.path.join("C:/U/AppData/Local", "TurboCAT", "Cache"))
            self.assertEqual(paths.default_db(), os.path.join(paths.data_dir(), "turbocat.db"))

    def test_mac_uses_library(self):
        with as_system("mac"):
            self.assertIn(os.path.join("Library", "Application Support", "TurboCAT"), paths.data_dir())
            self.assertIn(os.path.join("Library", "Caches", "TurboCAT"), paths.cache_dir())

    def test_no_console_windows_and_detached_emulators(self):
        with as_system("windows"):
            self.assertEqual(paths.no_window(), {"creationflags": 0x08000000})
            self.assertTrue(paths.detached()["creationflags"] & 0x8)
        with as_system("linux"):
            self.assertEqual(paths.no_window(), {})
            self.assertEqual(paths.detached(), {"start_new_session": True})


class FindEmulatorsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, *parts):
        p = os.path.join(self.tmp.name, *parts)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "wb").close()
        return p

    def test_windows_finds_winuae_and_fs_uae(self):
        winuae = self.make("Programs", "WinUAE", "winuae64.exe")
        fsuae = self.make("Programs", "FS-UAE", "Windows", "x86-64", "fs-uae.exe")
        env = {"ProgramFiles": os.path.join(self.tmp.name, "Programs")}
        with as_system("windows"), mock.patch.dict(os.environ, env), \
                mock.patch.object(emulator.shutil, "which", return_value=None):
            found = emulator.find_emulators()
        self.assertEqual(found, {"winuae": [winuae], "fs-uae": [fsuae]})

    def test_windows_finds_amiga_forevers_winuae(self):
        winuae = self.make("Programs", "Cloanto", "Amiga Forever", "WinUAE", "winuae.exe")
        with as_system("windows"), mock.patch.dict(os.environ, {"ProgramFiles": os.path.join(self.tmp.name, "Programs")}), \
                mock.patch.object(emulator.shutil, "which", return_value=None):
            self.assertEqual(emulator.find_emulators(), {"winuae": [winuae]})

    def test_mac_finds_the_apps(self):
        app = self.make("Applications", "FS-UAE.app", "Contents", "MacOS", "fs-uae")
        with as_system("mac"), mock.patch.object(emulator.os.path, "expanduser",
                                                 side_effect=lambda p: p.replace("~", self.tmp.name)), \
                mock.patch.object(emulator.shutil, "which", return_value=None):
            found = emulator.find_emulators()
        # (pretending to be a Mac on Windows mixes "/" and "\\" in the path: compare them as paths)
        self.assertEqual({k: [os.path.normpath(p) for p in v] for k, v in found.items()},
                         {"fs-uae": [os.path.normpath(app)]})

    def test_winuae_is_started_with_a_settings_file(self):
        with mock.patch.object(paths, "cache_dir", return_value=self.tmp.name):
            cmd = emulator.command("winuae", ["winuae64.exe"], "A1200", "kick31.rom", ["a.adf", "b.adf"],
                                   mounts=[("WORK", "D:/Amiga")], display="fullscreen")
        self.assertEqual(cmd[:2], ["winuae64.exe", "-f"])
        with open(cmd[2], encoding="utf-8") as f:
            cfg = dict(line.split("=", 1) for line in f.read().splitlines() if "=" in line and not line.startswith(";"))
        self.assertEqual(cfg["chipset"], "aga")
        self.assertEqual(cfg["kickstart_rom_file"], "kick31.rom")
        self.assertEqual((cfg["floppy0"], cfg["floppy1"], cfg["nr_floppies"]), ("a.adf", "b.adf", "2"))
        self.assertEqual(cfg["fastmem_size"], str(emulator.A1200_FAST_MB))
        self.assertEqual(cfg["filesystem2"], "rw,WORK:WORK:D:/Amiga,-128")
        self.assertEqual(cfg["use_gui"], "no")
        self.assertEqual(emulator.NAMES["winuae"], "WinUAE")


class SticksTest(unittest.TestCase):
    VOLUMES = [("C:/", "System", "NTFS", True, False, 10**10),
               ("E:/", "GOTEK", "FAT32", True, False, 2 * 10**9),
               ("F:/", "Locked", "FAT32", True, True, 10**9),
               ("G:/", "Backup", "NTFS", True, False, 10**11),
               ("/Volumes/GOTEK", "GOTEK", "msdos", True, False, 10**9),
               ("/", "Macintosh HD", "apfs", True, False, 10**11)]

    def test_windows_offers_writable_fat_drives_only(self):
        with mock.patch.dict(os.environ, {"SystemDrive": "C:"}):
            sticks = gotek._sticks_from(self.VOLUMES[:4], "windows")
        self.assertEqual(sticks, [("E:/", "GOTEK", 2 * 10**9)])

    def test_mac_offers_sticks_in_volumes(self):
        self.assertEqual(gotek._sticks_from(self.VOLUMES[4:], "mac"), [("/Volumes/GOTEK", "GOTEK", 10**9)])


class DatesTest(unittest.TestCase):
    def test_dates_are_written_without_unix_only_codes(self):
        # strftime's %-d (day without a leading 0) is Linux and macOS only: on Windows it raised
        # ValueError, and the details panel failed for every scanned disk
        import re
        import time
        here = os.path.join(os.path.dirname(__file__), "..", "turbocat")
        for name in os.listdir(here):
            if name.endswith(".py"):
                with open(os.path.join(here, name), encoding="utf-8") as f:
                    for n, line in enumerate(f, 1):
                        if "strftime" in line:
                            self.assertNotRegex(line, r"%[-#]", f"{name}:{n}")
        from turbocat.gui import when
        t = time.mktime((2026, 11, 5, 14, 3, 0, 0, 0, -1))
        self.assertEqual(re.sub(r"[A-Za-z]+", "Mon", when(t)), "5 Mon 2026, 14:03")


class FolderCaseTest(unittest.TestCase):
    @unittest.skipUnless(sys.platform.startswith("win"), "Windows ignores case in folder names")
    def test_windows_ignores_case(self):
        self.assertTrue(folders.within(r"D:\Amiga\Games\x.adf", r"d:\AMIGA"))
        self.assertFalse(folders.inside(r"D:\Amiga", r"d:\amiga"))

    def test_others_mind_case(self):
        if sys.platform.startswith("win"):
            self.skipTest("Windows ignores case")
        self.assertFalse(folders.within("/home/me/Amiga/x.adf", "/home/me/AMIGA"))


if __name__ == "__main__":
    unittest.main()
