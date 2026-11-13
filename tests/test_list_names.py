"""The list shows each disk's name made readable: the title big, and the year, publisher and
TOSEC tags in plain words underneath."""
import unittest

from turbocat.gui import name_parts


class NamePartsTest(unittest.TestCase):
    def test_tosec_names(self):
        self.assertEqual(name_parts("3615 Load (1991)(JMD Communication)(FR)[b virus damage].zip"),
                         ("3615 Load", ["1991", "JMD Communication", "France",
                                        "bad dump (damaged): virus damage"]))
        self.assertEqual(name_parts("Dune (1992)(Virgin)(Disk 2 of 3)[cr Fairlight].adf"),
                         ("Dune · Disk 2 of 3", ["1992", "Virgin", "cracked by Fairlight"]))
        self.assertEqual(name_parts("Utils (1990)(PD)[b][f TurboCAT].adf"),
                         ("Utils", ["1990", "PD", "bad dump (damaged)", "repaired by TurboCAT"]))

    def test_unknown_fields_are_left_out(self):
        self.assertEqual(name_parts("A-Term (19xx)(-)[cr Bandit].zip"), ("A-Term", ["cracked by Bandit"]))

    def test_plain_names(self):
        self.assertEqual(name_parts("g-loc - game complete.mod"), ("g-loc - game complete", []))
        self.assertEqual(name_parts("MOD.Turrigol"), ("MOD.Turrigol", []))
        self.assertEqual(name_parts("/x/Workbench 3.1/"), ("Workbench 3.1", []))


if __name__ == "__main__":
    unittest.main()
