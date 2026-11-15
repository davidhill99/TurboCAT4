"""Make repaired copy (R4): a damaged disk is rebuilt as a new image, with its damaged file put
back from another disk. The original is never changed."""
import hashlib
import io
import os
import tempfile
import unittest
import unittest.mock

from amitools.fs.ADFSVolume import ADFSVolume
from amitools.fs.FSString import FSString
from amitools.fs.blkdev.ADFBlockDevice import ADFBlockDevice

from turbocat import readers, repair, scanner
from turbocat.catalogue import Catalogue

TOOL = bytes(range(256)) * 12            # 3,072 bytes: a "C: command" on both disks
OTHER = b"Hello from the other file\n" * 40


def make_adf(volume, files):
    fobj = io.BytesIO()
    dev = ADFBlockDevice(None, fobj=fobj)
    dev.create()
    vol = ADFSVolume(dev)
    vol.create(FSString(volume))
    root = vol.get_root_dir()
    dirs = {}
    for path, data in files.items():
        parent = root
        if "/" in path:
            d, name = path.split("/")
            if d not in dirs:
                dirs[d] = root.create_dir(FSString(d))
            parent = dirs[d]
        else:
            name = path
        parent.create_file(FSString(name), data)
    vol.close()
    dev.flush()
    return bytearray(fobj.getvalue())


def damage(adf, data):
    """Spoil one data block of a file (OFS keeps 488 bytes of data per block, after a 24-byte
    header), so its checksum fails, as on a decayed floppy."""
    at = bytes(adf).find(data[600:640])
    assert at > 0
    adf[at:at + 8] = b"\xde\xad\xbe\xef" * 2
    return adf


class RepairTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.disks = os.path.join(t, "disks")
        os.makedirs(self.disks)
        bad = damage(make_adf("Utils", {"c/Type": TOOL, "ReadMe": OTHER}), TOOL)
        self.bad_path = os.path.join(self.disks, "Utils (1990)(PD)[b].adf")
        with open(self.bad_path, "wb") as f:
            f.write(bad)
        self.bad_sha = hashlib.sha1(bad).hexdigest()
        with open(os.path.join(self.disks, "Workbench.adf"), "wb") as f:
            f.write(make_adf("WB", {"c/Type": TOOL}))
        self.cat = Catalogue(os.path.join(t, "cat.db"))
        scanner.scan([self.disks], self.cat, progress=None)
        self.out = os.path.join(t, "Repaired")
        self.log = os.path.join(t, "repairs.csv")

    def tearDown(self):
        self.cat.db.close()
        self.tmp.cleanup()

    def top(self, name):
        return self.cat.db.execute("SELECT id FROM media WHERE source LIKE ? AND parent_id IS NULL",
                                   (f"%{name}",)).fetchone()[0]

    def test_plan_finds_the_damaged_file_elsewhere(self):
        p = repair.plan(self.cat, self.top("[b].adf"))
        self.assertEqual([x.path for x in p.lost], ["c/Type"])
        self.assertEqual(p.lost[0].confidence, "strong")      # one other disk, same file date
        self.assertTrue(p.complete())
        self.assertEqual(p.out_name(), "Utils (1990)(PD)[f TurboCAT].adf")
        self.assertIsNone(repair.plan(self.cat, self.top("Workbench.adf")))   # nothing damaged

    def test_build_makes_a_marked_new_copy_and_leaves_the_original(self):
        p = repair.plan(self.cat, self.top("[b].adf"))
        res = repair.build(self.cat, p, out_dir=self.out, log=self.log)
        with open(self.bad_path, "rb") as f:
            self.assertEqual(hashlib.sha1(f.read()).hexdigest(), self.bad_sha)   # untouched
        with open(res.path, "rb") as f:
            new = f.read()
        r = readers.read_adf(new)
        self.assertEqual(r.problems, [])
        files = {e.path: e for e in r.files if not e.is_dir}
        self.assertEqual(files["c/Type"].read(), TOOL)
        self.assertEqual(files["ReadMe"].read(), OTHER)
        self.assertIn("Restored by TurboCAT", files["c/Type"].comment)
        self.assertIn(b"NOT an original dump", files[repair.MARKER].read())
        self.assertEqual(r.volume, "Utils")
        self.assertIn(res.sha1, repair.repaired_sha1s(self.log))
        self.assertEqual([f for f, _ in repair.log_for(res.sha1, self.log)], ["c/Type"])

    def test_without_marking_the_disk_only_the_name_and_log_say_so(self):
        p = repair.plan(self.cat, self.top("[b].adf"))
        res = repair.build(self.cat, p, out_dir=self.out, log=self.log, mark=False)
        r = readers.read_adf(open(res.path, "rb").read())
        self.assertNotIn(repair.MARKER, [e.path for e in r.files])
        self.assertTrue(res.path.endswith("[f TurboCAT].adf"))

    def test_never_overwrites(self):
        p = repair.plan(self.cat, self.top("[b].adf"))
        a = repair.build(self.cat, p, out_dir=self.out, log=self.log)
        b = repair.build(self.cat, p, out_dir=self.out, log=self.log)
        self.assertNotEqual(a.path, b.path)

    def test_plan_all_and_the_log_link_copies_to_originals(self):
        plans = repair.plan_all(self.cat)
        self.assertEqual([p.source_file for p in plans.values()], ["Utils (1990)(PD)[b].adf"])
        res = repair.build(self.cat, next(iter(plans.values())), out_dir=self.out, log=self.log)
        self.assertEqual(repair.copies_of(self.log), {"Utils (1990)(PD)[b].adf": [res.sha1]})

    def test_plan_all_while_a_scan_adds_a_damaged_disk(self):
        """Issue #1: a scan running alongside added a damaged disk after the item tree was read,
        and planning stopped with a KeyError. The new disk now waits for the next reload."""
        real_index = repair.Index
        late = os.path.join(self.disks, "Late (1991)(PD)[b].adf")

        def index_then_scan(cat):
            ix = real_index(cat)
            with open(late, "wb") as f:
                f.write(damage(make_adf("Late", {"c/Type": TOOL}), TOOL))
            scanner.scan([self.disks], self.cat, progress=None)
            return ix

        with unittest.mock.patch.object(repair, "Index", index_then_scan):
            plans = repair._plan_all(self.cat)
        self.assertEqual([p.source_file for p in plans.values()], ["Utils (1990)(PD)[b].adf"])
        names = sorted(p.source_file for p in repair._plan_all(self.cat).values())
        self.assertEqual(names, ["Late (1991)(PD)[b].adf", "Utils (1990)(PD)[b].adf"])

    def test_a_common_file_keeps_only_a_few_copies(self):
        """A big collection had 4,000 damaged disks whose lost files (devs/system-configuration)
        were on 35,000 other disks: listing every copy took over a gigabyte, and TurboCAT ran out
        of memory. Every copy is counted, but only a few are kept to read from."""
        for i in range(12):
            with open(os.path.join(self.disks, f"Copy {i:02d}.adf"), "wb") as f:
                f.write(make_adf(f"C{i}", {"c/Type": TOOL}))
        with open(os.path.join(self.disks, "Odd.adf"), "wb") as f:     # another version
            f.write(make_adf("Odd", {"c/Type": bytes(reversed(TOOL))}))
        scanner.scan([self.disks], self.cat, progress=None)
        with unittest.mock.patch.object(repair, "KEEP_COPIES", 4):
            plans = repair._plan_all(self.cat)
        x = next(iter(plans.values())).lost[0]
        self.assertEqual(x.versions, 2)
        self.assertEqual(x.disks, 14)                   # Workbench, 12 copies and Odd
        self.assertEqual(len(x.sources), 4)             # only the version picked, a few copies
        self.assertTrue(all(s.sha1 == x.use.sha1 for s in x.sources))
        self.assertEqual(x.use.sha1, hashlib.sha1(TOOL).hexdigest())     # the one found most often

    def test_an_unreadable_source_falls_back_to_another_copy(self):
        with open(os.path.join(self.disks, "Extras.adf"), "wb") as f:
            f.write(make_adf("Extras", {"c/Type": TOOL}))
        scanner.scan([self.disks], self.cat, progress=None)
        p = repair.plan(self.cat, self.top("[b].adf"))
        first = p.lost[0].use
        real = repair.read_source
        repair.read_source = lambda cat, s: (_ for _ in ()).throw(ValueError("gone")) \
            if s is first else real(cat, s)
        try:
            res = repair.build(self.cat, p, out_dir=self.out, log=self.log)
        finally:
            repair.read_source = real
        self.assertEqual(res.missing, [])
        self.assertNotEqual(res.restored[0].use.media_id, first.media_id)

    def test_a_source_disk_inside_a_zip(self):
        import zipfile
        os.remove(os.path.join(self.disks, "Workbench.adf"))
        with zipfile.ZipFile(os.path.join(self.disks, "Workbench.zip"), "w") as z:
            z.writestr("Workbench.adf", bytes(make_adf("WB", {"c/Type": TOOL})))
        scanner.scan([self.disks], self.cat, progress=None)
        p = repair.plan(self.cat, self.top("[b].adf"))
        src = next(s for s in p.lost[0].sources if s.name == "Workbench.zip")
        self.assertEqual(repair.read_source(self.cat, src), TOOL)

    def test_an_overdump_is_read_at_its_normal_size(self):
        adf = bytes(make_adf("Over", {"x": OTHER})) + bytes(11 * 512 * 2)    # 2 extra tracks
        vol = repair._volume(adf)
        self.assertEqual(vol.get_volume_name().get_unicode(), "Over")

    def test_a_partial_repair_logs_what_is_still_missing(self):
        only = b"Only on this one disk\n" * 60
        bad = damage(damage(make_adf("Two", {"c/Type": TOOL, "Notes": only}), TOOL), only)
        with open(os.path.join(self.disks, "Two (PD)[b].adf"), "wb") as f:
            f.write(bad)
        scanner.scan([self.disks], self.cat, progress=None)
        p = repair.plan(self.cat, self.top("Two (PD)[b].adf"))
        self.assertFalse(p.complete())                     # Notes isn't on any other disk
        res = repair.build(self.cat, p, out_dir=self.out, log=self.log)
        self.assertEqual([x.path for x in res.missing], ["Notes"])
        self.assertTrue(res.path.endswith("[b][f TurboCAT].adf"))
        self.assertEqual(sorted(repair.log_for(res.sha1, self.log)),
                         [("Notes", ""), ("c/Type", f"#{p.lost[0].use.number:04d} Workbench.adf")])

    def test_names(self):
        self.assertEqual(repair.repaired_name("Disk (1991)(PD)[v Saddam][b virus damage].zip", True),
                         "Disk (1991)(PD)[f TurboCAT].adf")
        self.assertEqual(repair.repaired_name("Disk (1991)(PD)[h ALE][b].adf", False),
                         "Disk (1991)(PD)[h ALE][b][f TurboCAT].adf")


if __name__ == "__main__":
    unittest.main()
