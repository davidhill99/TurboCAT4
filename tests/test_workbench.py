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

    def test_a_set_of_three_goes_in_three_drives(self):
        """Worms - The Director's Cut asks for disk 3: it has to be in a drive, not only the swapper."""
        disks = ["d1.adf", "d2.adf", "d3.adf"]
        cmd = emulator.command("amiberry", ["amiberry"], "A1200", None, disks)
        self.assertEqual([cmd[cmd.index(f"-{i}") + 1] for i in range(3)], disks)
        self.assertIn("floppy2type=0", cmd)
        self.assertNotIn("-3", cmd)
        cmd = emulator.command("fs-uae", ["fs-uae"], "A1200", None, disks)
        self.assertIn("--floppy_drive_count=3", cmd)
        self.assertIn("--floppy_drive_2=d3.adf", cmd)

    def test_an_a1200_has_fast_ram(self):
        """Worms - The Director's Cut crashes with Software Failure on a plain 2 MB A1200."""
        cmd = emulator.command("amiberry", ["amiberry"], "A1200", None, ["d1.adf"])
        self.assertIn("fastmem_size=8", cmd)
        self.assertIn("--fast_memory=8192", emulator.command("fs-uae", ["fs-uae"], "A1200", None, ["d1.adf"]))
        self.assertNotIn("fastmem_size=8", emulator.command("amiberry", ["amiberry"], "A500", None, ["d.adf"]))

    def test_more_than_four_disks_fill_four_drives_and_the_swapper(self):
        disks = [f"d{n}.adf" for n in range(1, 7)]
        cmd = emulator.command("amiberry", ["amiberry"], "A500", None, disks)
        self.assertEqual(cmd[cmd.index("-3") + 1], "d4.adf")
        self.assertNotIn("-4", cmd)
        self.assertTrue(any(c.startswith("-diskswapper=") and "d6.adf" in c for c in cmd))


if __name__ == "__main__":
    unittest.main()
