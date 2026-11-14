"""Look on Aminet for missing files: only an exact name-and-size match is downloaded, Commodore's
own files and too-plain names are never looked for, answers are cached, and a repair can use a
file found there. No network: Aminet is faked."""
import hashlib
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from turbocat import aminet, repair, scanner
from turbocat.catalogue import Catalogue
from test_repair import damage, make_adf

ZAPPER = bytes(range(256)) * 12           # 3,072 bytes

SEARCH = '''<table><tr><td><a href="/misc/fish/fish-0100.lha">fish-0100.lha</a></td></tr>
<tr><td><a href="/util/misc/Zapper.lha">Zapper.lha</a></td></tr></table>'''


def package_page(rows):
    lines = "\n".join(f"[generic]                 1000    {size:>5}  50.0% -lh5- 2a65 Dec 24  1988 {path}"
                      for path, size in rows)
    return (f"<b>Contents of x.lha</b></font></a>\n<pre> PERMSSN    UID  GID    PACKED    SIZE  RATIO "
            f"METHOD CRC     STAMP          NAME\n---------- ----\n{lines}\n</pre>")


class FakeAminet:
    def __init__(self):
        self.urls = []

    def get(self, url, limit=None):
        self.urls.append(url)
        if "/search?" in url:
            return SEARCH.encode()
        if url.endswith("/package/misc/fish/fish-0100"):
            return package_page([("Zapper/Zapper", 9999), ("Zapper/Zapper.doc", 400)]).encode()
        if url.endswith("/package/util/misc/Zapper"):
            return package_page([("Zapper/c/Zapper", len(ZAPPER))]).encode()
        if url.endswith("/util/misc/Zapper.lha"):
            return b"LHA archive"
        raise AssertionError(f"unexpected request {url}")


def unpacked(_blob):
    return SimpleNamespace(files=[SimpleNamespace(path="Zapper/c/Zapper", is_dir=False, read=lambda: ZAPPER)])


class AminetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = os.path.join(self.tmp.name, "aminet")
        self.patches = [mock.patch.object(aminet, "CACHE_DIR", d),
                        mock.patch.object(aminet, "LOOKUPS", os.path.join(d, "lookups.json")),
                        mock.patch.object(aminet, "FILES", os.path.join(d, "files")),
                        mock.patch("turbocat.readers.read_lha", side_effect=unpacked)]
        for p in self.patches:
            p.start()
        aminet._memo.update(stamp=None, data={})
        self.fake = FakeAminet()
        self.fetcher = aminet.Fetcher(get=self.fake.get, delay=0)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_what_is_never_looked_for(self):
        self.assertIn("Commodore", aminet.worth_looking("diskfont.library", 100))
        self.assertIn("Commodore", aminet.worth_looking("SetMap.info", 515))
        self.assertIn("Commodore", aminet.worth_looking("Disk-Validator", 1848))
        for plain in ("12", "d", ".fastdir", "- 1990 -"):
            self.assertIn("plain", aminet.worth_looking(plain, 100))
        self.assertEqual(aminet.worth_looking("VirusZ", 35452), "")
        self.assertEqual(aminet.look_up("icon.library", 5688, self.fetcher), [])
        self.assertEqual(self.fake.urls, [])           # not even asked

    def test_reads_the_contents_list(self):
        rows = aminet.parse_contents(package_page([("a/b/Zapper", 3072)]))
        self.assertEqual(rows, [("a/b/Zapper", 3072, "1988-12-24")])
        self.assertEqual(aminet.parse_results(SEARCH), ["misc/fish/fish-0100.lha", "util/misc/Zapper.lha"])

    def test_only_an_exact_match_is_downloaded_and_kept(self):
        hits = aminet.look_up("Zapper", len(ZAPPER), self.fetcher)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].package, "util/misc/Zapper.lha")
        self.assertEqual(hits[0].sha1, hashlib.sha1(ZAPPER).hexdigest())
        self.assertEqual(aminet.read_hit(hits[0]), ZAPPER)
        downloads = [u for u in self.fake.urls if u.endswith(".lha")]
        self.assertEqual(downloads, ["https://aminet.net/util/misc/Zapper.lha"])  # not the other size
        self.assertEqual(aminet.other_versions("Zapper", len(ZAPPER)),
                         [("misc/fish/fish-0100.lha", "Zapper/Zapper", 9999)])

    def test_each_file_is_looked_up_once(self):
        aminet.look_up("Zapper", 123, self.fetcher)      # no match: remembered too
        n = len(self.fake.urls)
        self.assertTrue(aminet.looked("Zapper", 123))
        self.assertEqual(aminet.look_up("Zapper", 123, self.fetcher), [])
        self.assertEqual(len(self.fake.urls), n)

    def test_a_repair_uses_a_file_found_on_aminet(self):
        disks = os.path.join(self.tmp.name, "disks")
        os.makedirs(disks)
        bad = damage(make_adf("Tools", {"c/Zapper": ZAPPER, "ReadMe": b"hi\n" * 300}), ZAPPER)
        with open(os.path.join(disks, "Tools (1988)(PD)[b].adf"), "wb") as f:
            f.write(bad)
        cat = Catalogue(os.path.join(self.tmp.name, "cat.db"))
        try:
            scanner.scan([disks], cat, progress=None)
            top = cat.db.execute("SELECT id FROM media WHERE parent_id IS NULL").fetchone()[0]
            p = repair.plan(cat, top)
            self.assertIsNone(p.lost[0].use)              # nowhere in the collection
            aminet.look_up("Zapper", len(ZAPPER), self.fetcher)
            p = repair.plan(cat, top)
            x = p.lost[0]
            self.assertEqual(x.use.online, "util/misc/Zapper.lha")
            self.assertEqual(x.confidence, "likely")
            self.assertTrue(p.complete())
            log = os.path.join(self.tmp.name, "repairs.csv")
            res = repair.build(cat, p, out_dir=os.path.join(self.tmp.name, "out"), log=log)
            self.assertFalse(res.missing)
            vol = repair._volume(open(res.path, "rb").read())
            self.assertEqual(bytes(repair._node(vol, "c/Zapper").get_file_data()), ZAPPER)
            marker = bytes(repair._node(vol, repair.MARKER).get_file_data()).decode("latin-1")
            self.assertIn("from Aminet util/misc/Zapper.lha", marker)
            self.assertIn("Aminet util/misc/Zapper.lha", open(log).read())
        finally:
            cat.db.close()


if __name__ == "__main__":
    unittest.main()
