"""The disk map (every block on a floppy, classified) and the collection stats (groups,
publishers, years from TOSEC names)."""
import unittest

from turbocat import diskmap, stats
from test_repair import make_adf, damage, TOOL


class DiskMapTest(unittest.TestCase):
    def test_a_dos_disk(self):
        m = diskmap.build(bytes(make_adf("Utils", {"c/Type": TOOL, "ReadMe": b"x" * 2000})))
        c = m.counts()
        self.assertTrue(m.dos)
        self.assertEqual((c["boot"], c["root"], c["bitmap"], c["dir"], c["header"]), (2, 1, 1, 1, 2))
        self.assertEqual(m.kind[880], "root")
        self.assertGreater(c["free"], 1500)
        self.assertEqual(c.get("bad", 0), 0)
        self.assertEqual(m.where(880), (40, 0, 0))
        self.assertIn("Root block", m.describe(880))

    def test_damage_shows(self):
        adf = bytes(damage(make_adf("Utils", {"c/Type": TOOL}), TOOL))
        m = diskmap.build(adf, ["c/Type"])
        c = m.counts()
        self.assertEqual(c.get("bad", 0), 1)                  # the spoilt OFS data block
        self.assertGreater(c.get("damaged", 0), 0)            # the rest of the damaged file

    def test_a_non_dos_disk(self):
        adf = b"\x01" * 1024 + bytes(901120 - 1024)
        m = diskmap.build(adf)
        self.assertFalse(m.dos)
        self.assertEqual(m.counts()["blank"], 1758)


class StatsTest(unittest.TestCase):
    def test_groups(self):
        self.assertEqual(stats.groups_in("Game (1991)(Psygnosis)[cr PDX - TRSI][t +2 Fairlight][f TurboCAT]"),
                         [("PDX", "cracked"), ("TRSI", "cracked"), ("Fairlight", "trained")])
        self.assertEqual(stats.groups_in("Disk (1990)(PD)[h startup-sequence]"), [])
        self.assertEqual(stats.full_name("SR"), "SR (Skid Row)")

    def test_collect(self):
        s = stats.collect(["A (1990)(Ocean)[cr SR]", "B (1991)(Ocean)[cr Sr][t +1 FLT]",
                           "C (199x)(PD)", "D.adf"])
        self.assertEqual(s["disks"], 4)
        self.assertEqual(dict(s["groups"]["SR"]), {"cracked": 2})          # same group, any case
        self.assertEqual(s["publishers"]["Ocean"], 2)
        self.assertEqual(dict(s["years"]), {"1990": 1, "1991": 1})
        self.assertEqual(stats.league(s["groups"])[0][0], "SR")


if __name__ == "__main__":
    unittest.main()
