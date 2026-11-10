"""Coverdisks: recognised by checksum or by their file and folder names.

Run with:  ~/turbocat-env/bin/python -m unittest discover -s tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from turbocat import coverdisks     # noqa: E402

NAMES = [
    "Amiga Shopper #21 (1993)(Future Publishing)(GB)[Jan 1993][Shareware Collection Volume 01].adf",
    "Amiga Shopper #21 (1993)(Future Publishing)(GB)[m][o][Jan 1993][Shareware Collection Volume 01].adf",
    "Amiga Shopper #47 (1995)(Future Publishing)(GB)(Disk 1 of 3)[Mar 1995].adf",
    "Amiga Shopper #47 (1995)(Future Publishing)(GB)(Disk 2 of 3)[Mar 1995].adf",
    "Amiga Shopper #47 (1995)(Future Publishing)(GB)(Disk 3 of 3)[Mar 1995][Subscriber Disk].adf",
    "Amiga Shopper #64 (1996)(Future Publishing)(GB)(Disk 1 of 2)[Jul 1996].adf",
    "Amiga Shopper #64 (1996)(Future Publishing)(GB)(Disk 2 of 2)[Jul 1996][Subscriber Disk].adf",
    "One, The #66 - Amiga (1994-02)(EMAP Images)(GB)(Disk 1 of 2)[Mar 1994].adf",
    "Amiga Format #077 (1995-09-28)(Future Publishing)(GB)(Disk 1 of 3)[Nov 1995].adf",
]
ROOT = "/x/Amiga Shopper Coverdisks"


class CoverdiskTest(unittest.TestCase):
    def setUp(self):
        self.cat = coverdisks.Catalogue(NAMES)

    def test_tosec_names_are_read(self):
        cd = coverdisks.parse(NAMES[4])
        self.assertEqual((cd.magazine, cd.issue, cd.date, cd.disk, cd.of, cd.label),
                         ("Amiga Shopper", "47", "Mar 1995", "3", "3", "Subscriber Disk"))
        self.assertEqual(cd.title(), "Amiga Shopper #47 · Mar 1995 · Subscriber Disk · Disk 3 of 3")
        self.assertEqual(coverdisks.parse(NAMES[7]).magazine, "The One")
        self.assertEqual(coverdisks.parse(NAMES[1]).label, "Shareware Collection Volume 01")   # [m][o] dropped

    def guess(self, rel):
        return self.cat.guess(os.path.join(ROOT, rel))

    def test_recognised_by_name(self):
        cd = self.guess("Issue 47 March 1995/Amiga Shopper Issue 47 March 1995 Disk 2.adf")
        self.assertEqual((cd.how, cd.disk), ("name", "2"))
        cd = self.guess("Issue 47 March 1995/Amiga Shopper Issue 47 March 1995 Subscribers.adf")
        self.assertEqual(cd.label, "Subscriber Disk")
        cd = self.guess("Issue 64 July 1996/Amiga Shopper Issue 64 July 1996 Disk.adf")
        self.assertEqual(cd.disk, "1")                     # the other one is the subscriber disk
        cd = self.guess("Issue 21 January 1993/Amiga Shopper Issue 21 January 1993 Shareware Collection Vol 1.adf")
        self.assertNotIn("[o]", cd.tosec_name)             # two dumps of one disk: the plain one

    def test_made_from_and_unknown(self):
        cd = self.guess("Issue 47 March 1995/Created Disks/Created Disk 3.adf")
        self.assertEqual((cd.how, cd.issue, cd.label), ("made", "47", "Created Disk 3"))
        cd = self.guess("Amiga Shopper Demo Disk 1/Amiga Shopper Demo Disk 1.adf")
        self.assertEqual(cd.how, "folder")
        self.assertIsNone(self.cat.guess("/x/Games/Lemmings (1991)(Psygnosis).adf"))

    def test_by_checksum(self):
        cd = coverdisks.recognise("/x/disk1.adf", (NAMES[2], "TOSEC's Coverdisks list", "Coverdisks - [ADF]"))
        self.assertEqual((cd.how, cd.issue, cd.disk), ("checksum", "47", "1"))
        self.assertIsNone(coverdisks.recognise("/x/Amiga Shopper #47.adf", ("Lemmings.adf", "x", "Games - [ADF]")))


if __name__ == "__main__":
    unittest.main()
