"""Issue-scenario integration tests for the grant reconciliation post-pass
(change fix-compendium-grant-reconciliation, spec UAT blocks).

Fixtures are the synthetic level-1 heroes under tests/fixtures/heroes/
(Null/Metakinetic, Conduit with domains + prayer, Summoner/Demon, Dwarf
rune 'Light', Revenant) generated from real class data shapes.
"""
import copy
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from converter.loader import load_compendium_items
from converter.mapper import convert_character

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = os.path.join(REPO, "draw_steel_repo", "src", "packs")
FIXTURES = os.path.join(REPO, "tests", "fixtures", "heroes")


def load_fixture(name):
    with open(os.path.join(FIXTURES, name + ".ds-hero"), encoding="utf-8") as fh:
        return json.load(fh)


class FixtureCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compendium = load_compendium_items(PACKS)

    @classmethod
    def convert(cls, name):
        return convert_character(load_fixture(name), cls.compendium)


class TestNullScenarios(FixtureCase):
    """Issue #3.1/.2/.3: Null grant pools completed, no level leak,
    no duplicate items."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.doc = cls.convert("null-metakinetic-lvl1")
        cls.names = [i.get("name") for i in cls.doc["items"]]

    def test_grant_all_pools_completed(self):
        from converter.grant_reconcile import (build_selection_context,
                                               hero_above_level_names)
        hero = load_fixture("null-metakinetic-lvl1")
        above = hero_above_level_names(build_selection_context(hero, 1))
        class_item = next(i for i in self.doc["items"]
                          if i.get("type") == "class")
        advs = (class_item.get("system") or {}).get("advancements", {})
        for adv in advs.values():
            if not isinstance(adv, dict) or adv.get("type") != "itemGrant":
                continue
            if adv.get("chooseN"):
                continue
            lvl = adv.get("level")
            if isinstance(lvl, int) and lvl > 1:
                continue
            for pool_item in adv.get("pool", []):
                target = pool_item.get("uuid", "").split(".")[-1]
                comp = next((c for c in self.compendium.values()
                             if c.get("_id") == target), None)
                if comp is None:
                    continue  # pinned packs lack the document
                if comp.get("name") in above:
                    continue  # hero only gains this name above level 1
                self.assertIn(
                    comp.get("name"), self.names,
                    f"grant-all member {comp.get('name')!r} missing")

    def test_no_unbracketed_duplicates(self):
        triples = [(i.get("name"), i.get("type"),
                    (i.get("system") or {}).get("_dsid"))
                   for i in self.doc["items"]]
        dupes = {t for t in triples if triples.count(t) > 1}
        self.assertEqual(dupes, set())

    def test_hero_not_mutated(self):
        hero = load_fixture("null-metakinetic-lvl1")
        snapshot = copy.deepcopy(hero)
        convert_character(hero, self.compendium)
        self.assertEqual(hero, snapshot)


class TestConduitScenarios(FixtureCase):
    """Issue #2 follow-up / #3.4/.5: domains emitted, prayer single."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.doc = cls.convert("conduit-domains-lvl1")

    def test_chosen_domains_present_as_subclass_items(self):
        subs = sorted(i.get("name") for i in self.doc["items"]
                      if i.get("type") == "subclass")
        self.assertIn("Death", subs)
        self.assertIn("War", subs)
        self.assertNotIn("Life", subs)

    def test_prayer_of_steal_single_instance(self):
        for name in ("Prayer of Steel", "Warrior's Prayer"):
            count = sum(1 for i in self.doc["items"] if i.get("name") == name)
            self.assertLessEqual(count, 1, f"{name} emitted {count}x")

    def test_no_above_level_items(self):
        # level-1 hero must carry no feature whose hero grant is level > 1
        # (Blessed Domain is the issue's named example)
        self.assertNotIn("Blessed Domain",
                         [i.get("name") for i in self.doc["items"]])


class TestRuneLightScenario(FixtureCase):
    """Issue #2.2: 'Light' rune must not fuzzy-match Lightning Nimbleness."""

    def test_no_lightning_nimbleness(self):
        doc = self.convert("dwarf-rune-light-lvl1")
        names = [i.get("name") for i in doc["items"]]
        self.assertNotIn("Lightning Nimbleness", names)


class TestRevenantScenario(FixtureCase):
    """Issue #3.7: no featureless Damage Modifier placeholder."""

    def test_no_damage_modifier_placeholder(self):
        doc = self.convert("revenant-talent-lvl1")
        placeholders = [i for i in doc["items"]
                        if i.get("name") == "Damage Modifier"]
        self.assertEqual(placeholders, [])


class TestSummonerScenario(FixtureCase):
    """Issue #3.6: summon picks never fabricated against pinned packs
    without a summons pack; no featureless placeholder items."""

    def test_conversion_clean(self):
        doc = self.convert("summoner-demon-lvl1")
        self.assertGreater(len(doc["items"]), 10)
        flags_blobs = json.dumps(
            [i.get("flags") for i in doc["items"]])
        # no invented summon uuids may appear
        self.assertNotIn("summon-test", flags_blobs)


class TestRoundTripStillGreen(FixtureCase):
    """Task 4.3: forward changes keep the reverse converter compatible —
    post-fix forward output must not contain colliding items the reverse
    mapper would have to guess about."""

    def test_keth_post_fix_output_wellformed(self):
        forward = convert_character(
            json.load(open(os.path.join(REPO, "Keth.ds-hero"),
                           encoding="utf-8")),
            self.compendium)
        items = forward.get("items", [])
        non_ability = [(i.get("name"), i.get("type")) for i in items
                       if i.get("type") != "ability"]
        self.assertEqual(len(non_ability), len(set(non_ability)),
                         "duplicate non-ability items confuse reverse")
        ability_keys = [(i.get("name"), i.get("type"),
                         (i.get("system") or {}).get("_dsid"))
                        for i in items if i.get("type") == "ability"]
        self.assertEqual(len(ability_keys), len(set(ability_keys)))


if __name__ == "__main__":
    unittest.main()
