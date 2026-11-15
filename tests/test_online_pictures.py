"""Pictures from the libretro-thumbnails collection online (no network here: the list and the
download are faked). A picture found goes to the disk it was found for, a disk that found nothing
is marked as looked up (so the next start doesn't look it up again), and Look online again… looks
up that one item only."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import qt_cleanup  # noqa: F401,E402  (deletes leftover windows before Qt shuts down)

from turbocat import pictures                # noqa: E402
from turbocat.catalogue import Catalogue     # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
INDEX = {pictures.normal("Dark Seed"): {"Named_Titles": "Named_Titles/Darkseed.png"},
         pictures.normal("Darkseed"): {"Named_Titles": "Named_Titles/Darkseed.png"}}


class _Reply:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.data


class OnlinePicturesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [mock.patch.object(pictures, "PIC_DIR", os.path.join(self.tmp.name, "pics")),
                        mock.patch.object(pictures, "online_index", lambda stop=None: INDEX),
                        mock.patch.object(pictures.urllib.request, "urlopen", self.fake_open)]
        for p in self.patches:
            p.start()
        self.opened = []
        self.cat = Catalogue(os.path.join(self.tmp.name, "cat.db"))
        for n, name in enumerate(["Dark Seed (1993)(Cyberdreams)[cr].adf", "Mystery Disk.adf",
                                  "Something Else.adf"], 1):
            self.cat.add_media({"source": f"/games/{name}", "kind": "adf", "status": "ok",
                                "sha1": f"{n:040x}", "files": []}, number=n)
        self.cat.db.commit()
        pictures.ensure_schema(self.cat)
        for n in (1, 2, 3):              # the search on the disks went first and found nothing
            self.cat.db.execute("INSERT INTO thumbs (key, made_at) VALUES (?, 0)", (f"{n:040x}",))
        self.cat.db.commit()
        self.ids = [r[0] for r in self.cat.db.execute("SELECT id FROM media ORDER BY number")]

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.cat.db.close()
        self.tmp.cleanup()

    def fake_open(self, req, timeout=None):
        self.opened.append(req.full_url)
        return _Reply(PNG)

    def thumb(self, n):
        return self.cat.db.execute("SELECT * FROM thumbs WHERE key=?", (f"{n:040x}",)).fetchone()

    def test_the_picture_goes_to_the_disk_and_every_disk_is_marked_looked_up(self):
        res = pictures.lookup_online(self.cat)
        self.assertEqual((res["looked"], res["found"]), (3, 1))
        t = self.thumb(1)
        self.assertTrue(t["pic"])                         # on the disk itself, not under "darkseed"
        self.assertEqual(t["origin"], "online")
        self.assertEqual(self.thumb(2)["online"], 1)      # nothing found, but looked up
        keys = {r[0] for r in self.cat.db.execute("SELECT key FROM thumbs")}
        self.assertEqual(keys, {f"{n:040x}" for n in (1, 2, 3)})
        res = pictures.lookup_online(self.cat)            # the next start: nothing to do again
        self.assertEqual(res["looked"], 0)

    def test_pictures_saved_under_a_name_are_cleared_once(self):
        # what versions up to beta 2 did: the picture under the name it matched
        self.cat.db.execute("INSERT INTO thumbs (key, pic, origin, online, made_at) "
                            "VALUES ('darkseed', 'x.png', 'online', 1, 0)")
        self.cat.db.commit()
        pictures.lookup_online(self.cat)
        self.assertIsNone(self.cat.db.execute("SELECT 1 FROM thumbs WHERE key='darkseed'").fetchone())
        self.assertTrue(self.thumb(1)["pic"])

    def test_look_online_again_looks_at_that_item_only(self):
        pictures.lookup_online(self.cat)
        self.opened.clear()
        res = pictures.lookup_online(self.cat, only=[self.ids[0]])
        self.assertEqual(res["looked"], 1)                # not the whole catalogue
        self.assertEqual(len(self.opened), 1)             # looked up again, though found before
        res = pictures.lookup_online(self.cat, only=[self.ids[1]])
        self.assertEqual((res["looked"], res["found"]), (1, 0))

    def test_a_picture_from_the_disk_itself_is_kept(self):
        self.cat.db.execute("UPDATE thumbs SET pic='own.png', origin='disk' WHERE key=?", (f"{1:040x}",))
        self.cat.db.commit()
        res = pictures.lookup_online(self.cat, only=[self.ids[0]])
        self.assertEqual(res["looked"], 0)
        self.assertEqual(self.thumb(1)["pic"], "own.png")


if __name__ == "__main__":
    unittest.main()
