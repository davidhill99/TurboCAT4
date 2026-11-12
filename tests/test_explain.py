"""Problems in plain English (turbocat/explain.py)."""
import unittest
from types import SimpleNamespace

from turbocat import explain


class ExplainTest(unittest.TestCase):
    MSGS = ["Disk.adf: file unreadable: GuruInfo/Guru.Info (Invalid FileData Block(6):node=ADFSFile:"
            "'GuruInfo/Guru.Info'(@1637),block=FileDataBlock:@177)",
            "Disk.adf: filesystem: @000177:ERROR:File data block #14 of 'Guru.Info' (@1637) is no data block"]

    def test_damaged_files_named(self):
        self.assertEqual(explain.damaged_paths(self.MSGS), ["GuruInfo/Guru.Info"])
        self.assertEqual(explain.damaged_paths(["file unreadable: A (b) (x (y))"]), ["A (b)"])

    def test_summary_counts_files(self):
        self.assertEqual(explain.summary(self.MSGS, 220), "1 of 220 files damaged — the other 219 read fine")
        self.assertEqual(explain.summary(self.MSGS, 2), "1 of 2 files damaged — the other one reads fine")

    def test_summary_without_damaged_files(self):
        self.assertEqual(explain.summary(["truncated image: 2 tracks short of a full disk"], 0),
                         "The disk image is cut short: part of the disk is missing")
        self.assertEqual(explain.summary(["x.lha: LHA archive unreadable: bad"], 0),
                         "An LHA archive on it can't be opened")
        self.assertEqual(explain.summary(["something new"], 5), "Something on this disk can't be read")

    def test_why_no_good_copy(self):
        me = SimpleNamespace(number=1, version_key="k", spare_of=0, status="error", files="9",
                             path="/d/Disk (PD).zip", tosec_name="", cover=None)
        bad = SimpleNamespace(**{**vars(me), "number": 2, "status": "ok", "files": "—",
                                 "path": "/d/Disk (PD)[b].zip"})
        other = SimpleNamespace(**{**vars(me), "number": 3, "version_key": "other"})
        self.assertEqual(explain.why_not_fixable(me, [me, bad, other]),
                         ["#0002 is another version of this disk, but TOSEC marks it as a bad dump [b], "
                          "and TurboCAT can't read its files either."])


if __name__ == "__main__":
    unittest.main()
