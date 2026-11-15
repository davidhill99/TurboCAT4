"""What is known about a game: matching disks to Wikidata's list of Amiga titles, fetching
Wikipedia's summary for each title found (no network here: both are faked), showing it in the
details, and background work waiting while the user is busy."""
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import qt_cleanup  # noqa: F401,E402  (deletes leftover windows before Qt shuts down)

from turbocat import background, gameinfo   # noqa: E402
from turbocat.catalogue import Catalogue    # noqa: E402

WIKIDATA = {"results": {"bindings": [
    {"x": {"value": "http://www.wikidata.org/entity/Q1114108"},
     "label": {"value": "Alien Breed II: The Horror Continues"},
     "year": {"value": "1993"}, "genres": {"value": "action game|science fiction video game"},
     "devs": {"value": "Team17"}, "pubs": {"value": "Team17"},
     "modes": {"value": "co-op mode|single-player video game"},
     "hol": {"value": "3233"}, "lemon": {"value": "2158"},
     "moby": {"value": "alien-breed-ii-the-horror-continues"},
     "wp": {"value": "Alien Breed II: The Horror Continues"}, "desc": {"value": "1993 video game"}},
    {"x": {"value": "http://www.wikidata.org/entity/Q1"}, "label": {"value": "Speedball"},
     "hol": {"value": "1"}},
    {"x": {"value": "http://www.wikidata.org/entity/Q2"}, "label": {"value": "Speedball"}},
    {"x": {"value": "http://www.wikidata.org/entity/Q3"}, "label": {"value": "Elite"}},
    {"x": {"value": "http://www.wikidata.org/entity/Q4"}, "label": {"value": "Elite"}},
    {"x": {"value": "http://www.wikidata.org/entity/Q5"}, "label": {"value": "Go"}},
]}}


class MatchTest(unittest.TestCase):
    def setUp(self):
        self.entries = gameinfo._compact(WIKIDATA["results"]["bindings"])
        self.idx = gameinfo.index(self.entries)

    def test_names_match_whatever_the_punctuation(self):
        self.assertEqual(gameinfo.match(["Alien Breed II - The Horror Continues"], self.idx), "Q1114108")
        self.assertEqual(gameinfo.match(["Disk1", "alien breed ii the horror continues"], self.idx),
                         "Q1114108")

    def test_a_name_two_titles_share(self):
        # two Speedballs, one on Hall of Light (the Amiga one); two Elites, neither: no guess
        self.assertEqual(gameinfo.match(["Speedball"], self.idx), "Q1")
        self.assertEqual(gameinfo.match(["Elite"], self.idx), "")

    def test_very_short_names_are_not_matched(self):
        self.assertEqual(gameinfo.match(["Go"], self.idx), "")


class LookupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.list_file = os.path.join(self.tmp.name, "wikidata-amiga.json")
        self.patches = [mock.patch.object(gameinfo, "LIST_FILE", self.list_file),
                        mock.patch.object(gameinfo, "CACHE", self.tmp.name),
                        mock.patch.object(gameinfo, "PAUSE", 0)]
        for p in self.patches:
            p.start()
        gameinfo._read_cached.cache_clear()
        self.cat = Catalogue(os.path.join(self.tmp.name, "cat.db"))
        for n, name in enumerate(["Alien Breed II - The Horror Continues (1993)(Team17)[cr].adf",
                                  "Mystery Disk.adf"], 1):
            self.cat.add_media({"source": f"/games/{name}", "kind": "adf", "status": "ok",
                                "sha1": f"{n:040x}", "files": []}, number=n)
        self.cat.db.commit()
        self.asked = []

    def tearDown(self):
        for p in self.patches:
            p.stop()
        gameinfo._read_cached.cache_clear()
        self.cat.db.close()
        self.tmp.cleanup()

    def fake_get(self, url, **kw):
        self.asked.append(url)
        if url.startswith(gameinfo.SPARQL):
            return json.dumps(WIKIDATA).encode()
        if url.startswith(gameinfo.SUMMARY):
            return json.dumps({"extract": "Alien Breed II is a top-down shooter by Team17."}).encode()
        raise AssertionError(url)

    def test_finds_the_game_and_its_summary_once(self):
        with mock.patch.object(gameinfo, "_get", self.fake_get):
            res = gameinfo.lookup(self.cat)
            self.assertEqual((res["matched"], res["texts"]), (1, 1))
            f = gameinfo.facts(self.cat, gameinfo.about_by_key(self.cat)[f"{1:040x}"])
            self.assertIn("top-down shooter", f["summary"])
            self.assertEqual(f["year"], 1993)
            self.assertEqual(f["players"], ["co-op", "1 player"])
            self.assertEqual([name for name, _ in f["links"]],
                             ["Hall of Light", "Lemon Amiga", "MobyGames", "Wikipedia", "Wikidata"])
            self.assertIn("https://amiga.abime.net/3233", dict(f["links"]).values())
            n = len(self.asked)
            res = gameinfo.lookup(self.cat)           # again: the list is kept, nothing new to fetch
            self.assertEqual(len(self.asked), n)
            self.assertEqual(res["texts"], 0)

    def test_offline_is_not_an_error_for_the_search(self):
        def offline(url, **kw):
            raise OSError("no network")
        with mock.patch.object(gameinfo, "_get", offline):
            res = gameinfo.lookup(self.cat)
        self.assertIn("no network", res["error"])

    def test_the_old_list_is_used_when_wikidata_cant_be_reached(self):
        with mock.patch.object(gameinfo, "_get", self.fake_get):
            gameinfo.fetch_list()
        os.utime(self.list_file, (0, 0))              # two months old and more

        def offline(url, **kw):
            raise OSError("no network")
        with mock.patch.object(gameinfo, "_get", offline):
            self.assertIn("Q1114108", gameinfo.fetch_list())


class PaceTest(unittest.TestCase):
    def test_waits_while_the_user_is_busy(self):
        background.user_did_something()
        t = time.monotonic()
        with mock.patch.object(background, "QUIET_FOR", 0.4):
            background.pace()
        self.assertGreaterEqual(time.monotonic() - t, 0.3)

    def test_goes_straight_on_otherwise(self):
        with mock.patch.object(background, "_last_input", 0.0):
            t = time.monotonic()
            background.pace()
        self.assertLess(time.monotonic() - t, 0.1)

    def test_stop_ends_the_wait(self):
        background.user_did_something()
        t = time.monotonic()
        background.pace(lambda: True)
        self.assertLess(time.monotonic() - t, 0.1)


class DetailsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        from turbocat import gui
        cls.app = QApplication.instance() or QApplication([])
        gui._pick_theme()
        cls.gui = gui

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cat = Catalogue(os.path.join(self.tmp.name, "cat.db"))
        self.cat.add_media({"source": "/games/Alien Breed II.adf", "kind": "adf", "status": "ok",
                            "sha1": "a" * 40, "files": []}, number=1)
        self.cat.db.commit()
        self.panel = self.gui.DetailsPanel(self.cat, lambda n: None)
        self.item = next(i for i in self.gui.load_items(self.cat))

    def tearDown(self):
        self.panel.deleteLater()
        self.app.processEvents()
        self.cat.db.close()
        self.tmp.cleanup()

    def test_shows_what_is_known(self):
        facts = {"title": "Alien Breed II: The Horror Continues", "summary": "A top-down shooter.",
                 "what": "", "genres": ["action game"], "developers": ["Team17"], "publishers": [],
                 "year": 1993, "players": ["1 player"], "links": [("Hall of Light", "https://x/1")]}
        self.item.about = "Q1114108"
        with mock.patch.object(self.gui.gameinfo, "facts", return_value=facts):
            self.panel.show_item(self.item)
        text = self.panel.about_text.text()
        self.assertFalse(self.panel.about_box.isHidden())
        for bit in ("A top-down shooter.", "Team17", "1993", "Hall of Light", "CC BY-SA"):
            self.assertIn(bit, text)

    def test_links_in_the_details_can_be_clicked(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        flags = self.panel.about_text.textInteractionFlags()
        self.assertTrue(flags & Qt.TextInteractionFlag.LinksAccessibleByMouse)
        lab = self.gui._wrap_label("", self.gui.ui_font(13))      # the same kind of label, clicked
        lab.setTextFormat(Qt.TextFormat.RichText)
        clicked = []
        lab.linkActivated.connect(clicked.append)
        lab.setText("<a href='#info'>Find out about this game online…</a> more words")
        lab.resize(400, 60)
        lab.show()
        self.app.processEvents()
        QTest.mouseClick(lab, Qt.MouseButton.LeftButton, pos=QPoint(20, 8))
        self.assertEqual(clicked, ["#info"])
        lab.deleteLater()

    def test_offers_to_look_before_the_user_has_agreed(self):
        self.panel.on_info = lambda: None
        self.item.game = "in a folder called Games"
        self.panel.show_item(self.item)
        self.assertIn("Find out about this game online", self.panel.about_text.text())
        self.cat.set_meta(gameinfo.CONSENT, True)
        self.panel.show_item(self.item)              # agreed, not found (yet): nothing shown
        self.assertTrue(self.panel.about_box.isHidden())


if __name__ == "__main__":
    unittest.main()
