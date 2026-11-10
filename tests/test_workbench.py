"""Play with Workbench first, for disks that don't start by themselves."""
import unittest

from turbocat import emulator


class WorkbenchTest(unittest.TestCase):
    def test_versions(self):
        self.assertEqual(emulator.wb_version("Workbench3.1"), (3, "3.1"))
        self.assertEqual(emulator.wb_version("Workbench1.3"), (1, "1.3"))
        self.assertEqual(emulator.wb_version("Workbench"), (None, ""))

    def test_model_moves_up_for_newer_workbench(self):
        self.assertEqual(emulator.model_for_workbench(3, "A500"), "A1200")
        self.assertEqual(emulator.model_for_workbench(2, "A500"), "A600")
        self.assertEqual(emulator.model_for_workbench(1, "A500"), "A500")
        self.assertEqual(emulator.model_for_workbench(1, "A1200"), "A1200")

    def test_command_two_drives_and_fast_floppies(self):
        cmd = emulator.command("amiberry", ["amiberry"], "A1200", "kick.rom", ["wb.adf", "cover.adf"],
                               fast_floppy=True)
        self.assertEqual(cmd[cmd.index("-0") + 1], "wb.adf")
        self.assertEqual(cmd[cmd.index("-1") + 1], "cover.adf")
        self.assertIn("floppy1type=0", cmd)
        self.assertIn("floppy_speed=800", cmd)
        cmd = emulator.command("amiberry", ["amiberry"], "A500", None, ["game.adf"])
        self.assertNotIn("floppy_speed=800", cmd)                 # games keep real-speed drives
        cmd = emulator.command("fs-uae", ["fs-uae"], "A1200", None, ["wb.adf", "c.adf"], fast_floppy=True)
        self.assertIn("--floppy_drive_speed=0", cmd)


if __name__ == "__main__":
    unittest.main()
