"""Favourites: starring items and tunes, and TurboView's catalogue carrying them.

Run with:  ~/turbocat-env/bin/python -m unittest discover -s tests
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from turbocat import favourites    # noqa: E402
from turbocat.catalogue import Catalogue  # noqa: E402


class FavouritesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cat = Catalogue(os.path.join(self.tmp.name, "t.db"))

    def tearDown(self):
        self.cat.db.close()
        self.tmp.cleanup()

    def test_star_and_unstar(self):
        a, b = favourites.item_key("sha-a"), favourites.item_key("sha-b")
        favourites.set_favourite(self.cat, {a, b}, True)
        self.assertEqual(favourites.load(self.cat), {a, b})
        favourites.set_favourite(self.cat, {a}, False)
        self.assertEqual(favourites.load(self.cat), {b})

    def test_a_tune_is_known_by_its_item_file_and_place(self):
        row = {"key": "sha-a", "file": "mods/mod.tune", "offset": 0}
        inside = {"key": "sha-a", "file": "intro", "offset": 1234}
        self.assertNotEqual(favourites.tune_key(row), favourites.tune_key(inside))
        favourites.set_favourite(self.cat, {favourites.tune_key(row)}, True)
        self.assertIn(favourites.tune_key(dict(row)), favourites.load(self.cat))

    def test_starring_twice_is_harmless(self):
        k = favourites.item_key("x")
        favourites.set_favourite(self.cat, {k}, True)
        favourites.set_favourite(self.cat, {k}, True)
        self.assertEqual(len(favourites.load(self.cat)), 1)


if __name__ == "__main__":
    unittest.main()
