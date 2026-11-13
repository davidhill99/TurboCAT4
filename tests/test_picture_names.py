"""Matching disk names to the libretro-thumbnails picture list: exact first, then a looser match
that ignores small words, version numbers and edition words."""
import unittest

from turbocat import pictures as P


class LooseTest(unittest.TestCase):
    def test_names_that_differ_only_in_small_words_match(self):
        same = [("Dune II - The Battle for Arrakis", "Dune II - Battle for Arrakis"),
                ("Millennium", "Millennium 2.2"),
                ("Aladdin - HD Installer", "Aladdin"),
                ("Epic - Trainer +5", "Epic"),
                ("Chambers of Shaolin CD32", "Chambers of Shaolin"),
                ("Bump 'N' Burn", "Bump 'n' Burn")]
        for a, b in same:
            self.assertEqual(P.loose(a), P.loose(b), (a, b))

    def test_different_games_stay_different(self):
        for a, b in (("Lemmings", "Lemmings 2 - The Tribes"), ("Frogger", "Frogger 500"),
                     ("Tetris", "Tetriz"), ("Alien Breed", "Alien Breed II")):
            self.assertNotEqual(P.loose(a), P.loose(b), (a, b))

    def test_junk_prefixes_go(self):
        self.assertEqual(P.clean_title("ZZZ-UNK-Special Forces (1992)(MicroProse).adf"), "Special Forces")


if __name__ == "__main__":
    unittest.main()
