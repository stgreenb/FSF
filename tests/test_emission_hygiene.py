"""Tests for group 0 emission hygiene (change fix-compendium-grant-reconciliation,
design D0): compendium index immutability across conversions and single-source
level detection."""
import copy
import hashlib
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from converter.loader import load_compendium_items
from converter.mapper import convert_character

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KETH = os.path.join(REPO, "Keth.ds-hero")
PYRE = os.path.join(REPO, "Pyre.ds-hero")
PACKS = os.path.join(REPO, "draw_steel_repo", "src", "packs")


def _index_hash(compendium):
    blob = json.dumps(compendium, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


class TestCompendiumImmutable(unittest.TestCase):
    """A loaded compendium dict must be pristine after any number of
    conversions (all output copies are deep)."""

    @classmethod
    def setUpClass(cls):
        cls.compendium = load_compendium_items(PACKS)
        cls.pristine = _index_hash(cls.compendium)
        heroes = []
        for path in (KETH, PYRE):
            with open(path, encoding="utf-8") as fh:
                heroes.append(json.load(fh))
        cls.heroes = heroes

    def test_two_conversions_do_not_mutate_index(self):
        for hero in self.heroes:
            convert_character(hero, self.compendium)
        self.assertEqual(_index_hash(self.compendium), self.pristine,
                         "compendium index mutated by conversion")

    def test_second_conversion_sees_pristine_items(self):
        # Deep-copy guard: converting twice must produce identical output
        # even when compendium items were handed out in the first pass.
        first = convert_character(self.heroes[0], self.compendium)
        for hero in self.heroes:
            convert_character(hero, self.compendium)
        second = convert_character(self.heroes[0], self.compendium)
        norm = lambda d: json.dumps(
            [{k: v for k, v in i.items() if k != "_id"} for i in d["items"]],
            sort_keys=True)
        self.assertEqual(norm(first), norm(second))

    def test_mutation_would_be_caught(self):
        # Guard-the-guard: mutate one index entry and confirm the hash moves.
        mutated = copy.deepcopy(self.compendium)
        victim = next(iter(mutated.values()))
        victim.setdefault("system", {})["poison"] = True
        self.assertNotEqual(_index_hash(mutated), self.pristine)


class TestLevelSourceOfTruth(unittest.TestCase):
    """LevelDetector is the fallback only when class data omits a level."""

    def test_class_level_used_when_present(self):
        with open(KETH, encoding="utf-8") as fh:
            hero = json.load(fh)
        doc = convert_character(hero, load_compendium_items(PACKS))
        cls_item = next(i for i in doc["items"] if i["type"] == "class")
        self.assertEqual(cls_item["system"]["level"], 2)

    def test_missing_class_level_falls_back_to_detector(self):
        with open(KETH, encoding="utf-8") as fh:
            hero = json.load(fh)
        # Strip every level the mapper's class-data path can read; the
        # detector must still find the level from remaining sources.
        hero_class = hero.get("class", {})
        had_level = "level" in hero_class or "level" in hero_class.get("data", {})
        hero_class.pop("level", None)
        hero_class.get("data", {}).pop("level", None)
        doc = convert_character(hero, load_compendium_items(PACKS))
        cls_item = next(i for i in doc["items"] if i["type"] == "class")
        # D0: the class item's level must equal whatever the detector decides
        # (single source of truth), not a stale default.
        from converter.level_detector import LevelDetector
        self.assertEqual(cls_item["system"].get("level"),
                         LevelDetector.detect_level(hero))


if __name__ == "__main__":
    unittest.main()
