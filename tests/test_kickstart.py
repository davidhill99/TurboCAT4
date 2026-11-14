"""Kickstart ROMs: recognised by a scan, named by version, given their own chip.

Run with:  ~/turbocat-env/bin/python -m unittest discover -s tests
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from turbocat import emulator, readers      # noqa: E402
from turbocat.catalogue import Catalogue    # noqa: E402
from turbocat.scanner import scan           # noqa: E402


def fake_rom(major, minor, size=524288):
    data = bytearray(size)
    data[:2] = b"\x11\x14" if size == 524288 else b"\x11\x11"
    data[12:14] = major.to_bytes(2, "big")
    data[14:16] = minor.to_bytes(2, "big")
    base = 0x1000000 - size              # where the ROM sits in the Amiga's memory
    tag = 0x100
    data[tag:tag + 2] = b"\x4a\xfc"                         # exec.library's ROM tag
    data[tag + 2:tag + 6] = (base + tag).to_bytes(4, "big")
    data[tag + 14:tag + 18] = (base + 0x200).to_bytes(4, "big")
    data[tag + 18:tag + 22] = (base + 0x220).to_bytes(4, "big")
    data[0x200:0x20d] = b"exec.library\0"
    ident = f"exec {major}.{minor} (1.1.93)".encode() + b"\0"
    data[0x220:0x220 + len(ident)] = ident
    return bytes(data)


class KickstartTest(unittest.TestCase):
    def test_names(self):
        self.assertEqual(emulator.kickstart_name(34, 5), "Kickstart 1.3")
        self.assertEqual(emulator.kickstart_name(37, 350), "Kickstart 2.05")
        self.assertEqual(emulator.kickstart_name(40, 68), "Kickstart 3.1")
        self.assertEqual(emulator.kickstart_name(99, 1), "Kickstart (version 99.1)")
        self.assertEqual(emulator.models_for(40, 68), ["A1200"])
        self.assertEqual(emulator.models_for(34, 5), ["A500"])

    def test_recognised(self):
        rom = fake_rom(40, 68)
        self.assertTrue(emulator.looks_like_rom(rom[:2048], len(rom)))
        self.assertFalse(emulator.looks_like_rom(bytes(2048), 524288))
        res = readers.read_kickstart(rom)
        self.assertEqual(res.volume, "Kickstart 3.1")
        self.assertEqual(res.info["kickstart"], "40.68")
        self.assertEqual(res.info["models"], ["A1200"])
        # without exec.library it is some other ROM, not a Kickstart Play could use
        bare = bytearray(rom)
        bare[0x200:0x20d] = bytes(13)
        res = readers.read_kickstart(bytes(bare))
        self.assertEqual(res.info["models"], [])
        self.assertNotEqual(res.info["format"], "Kickstart ROM")

    def test_machine_specific_roms_are_not_offered_to_play(self):
        self.assertEqual(emulator.models_for(40, 68, "efb239cc"), [])        # A3000 3.1
        self.assertEqual(emulator.models_for(40, 68, "1483a091"), ["A1200"])
        self.assertEqual(emulator.kickstart_name(40, 68, "efb239cc"), "Kickstart 3.1 (A3000)")

    def test_encrypted_with_and_without_key(self):
        rom, key = fake_rom(34, 5, 262144), bytes(range(1, 200))
        pad = (key * (len(rom) // len(key) + 1))[:len(rom)]
        enc = emulator.AF_HEADER + bytes(a ^ b for a, b in zip(rom, pad))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "amiga-os-130.rom")
            self.assertEqual(readers.read_kickstart(enc, path).warnings[:1] and "rom.key", "rom.key")
            with open(os.path.join(d, "rom.key"), "wb") as f:
                f.write(key)
            self.assertEqual(readers.read_kickstart(enc, path).volume, "Kickstart 1.3")

    def test_scan_finds_roms(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "kick31.rom"), "wb") as f:
                f.write(fake_rom(40, 68))
            cat = Catalogue(os.path.join(d, "t.db"))
            scan([d], cat, progress=lambda *_: None)
            row = cat.db.execute("SELECT kind, volume FROM media").fetchone()
            self.assertEqual((row["kind"], row["volume"]), ("kickstart", "Kickstart 3.1"))
            self.assertEqual(emulator.catalogued_rom_dirs(cat), [d])
            cat.db.close()                  # before the folder goes: Windows won't delete an open file


if __name__ == "__main__":
    unittest.main()
