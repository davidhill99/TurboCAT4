"""DMS disks are unpacked with xdms (TurboCAT's own copy in the Windows and macOS packages, the
system's on Linux). Packs a test disk as a real DMS and checks TurboCAT reads it back exactly."""
import unittest

from turbocat import readers, tools
from dmsfile import pack
from test_repair import make_adf


@unittest.skipUnless(tools.which("xdms"), "xdms isn't installed here")
class DmsTest(unittest.TestCase):
    def test_a_dms_disk_unpacks_exactly(self):
        adf = bytes(make_adf("DMSTest", {"c/Tool": bytes(range(256)) * 50, "ReadMe": b"hello\n" * 400}))
        res = readers.read_dms(pack(adf))
        self.assertEqual(res.problems, [])
        self.assertEqual(res.inner_image, adf)
        self.assertEqual(sorted(f.path for f in res.files), ["ReadMe", "c", "c/Tool"])

    def test_a_damaged_dms_is_reported(self):
        dms = bytearray(pack(bytes(make_adf("Bad", {"File": b"x" * 9000}))))
        dms[56 + 20 + 100] ^= 0xFF                 # spoil a byte of track 0's data: its CRC fails
        res = readers.read_dms(bytes(dms))
        self.assertTrue(res.problems)


if __name__ == "__main__":
    unittest.main()
