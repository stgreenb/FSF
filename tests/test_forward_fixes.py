"""Regression tests for forward-converter fixes (titles, stamina dedup,
leveled treasure text) surfaced by the live Keth field test."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from converter.loader import load_compendium_items
from converter.mapper import convert_character
from converter.reverse.fs_data_cache import FsData

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KETH = os.path.join(REPO, "Keth.ds-hero")


class TestForwardFixes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(KETH, encoding="utf-8") as fh:
            cls.hero = json.load(fh)
        cls.compendium = load_compendium_items(
            os.path.join(REPO, "draw_steel_repo", "src", "packs"))
        cls.doc = convert_character(cls.hero, cls.compendium)

    def items(self, type_=None, name=None):
        return [i for i in self.doc["items"]
                if (type_ is None or i.get("type") == type_)
                and (name is None or i.get("name") == name)]

    # ---- titles (state.titles) ----
    def test_titles_emitted(self):
        self.assertTrue(self.items("title", "Angler"))
        self.assertTrue(self.items("title", "Brawler"))

    def test_title_granted_features_emitted(self):
        names = {i["name"] for i in self.doc["items"]}
        self.assertIn("Duck!", names)
        self.assertIn("Furniture Fighter", names)
        self.assertIn("If I Wanted You Dead, You’d Be Dead", names)

    def test_title_not_duplicated_as_feature(self):
        # Angler's roll-modifier feature shares the title's name; the title
        # item must appear exactly once and not again as a feature.
        self.assertEqual(len(self.items("title", "Angler")), 1)
        self.assertEqual(len(self.items("feature", "Angler")), 0)

    # ---- stamina bonus double-count (1.1 packs apply dwarf bonus natively) ----
    def test_no_duplicate_stamina_add(self):
        # Spark Off Your Skin carries system.stamina.bonuses.echelon natively;
        # the converter must not add a flat "Stamina Bonus" effect on top.
        for item in self.doc["items"]:
            for eff in item.get("effects", []) or []:
                if isinstance(eff, dict):
                    self.assertNotEqual(eff.get("name"), "Stamina Bonus",
                        "legacy flat stamina ADD double-counts a pack-native "
                        "stamina effect")

    def test_native_stamina_effect_preserved(self):
        spark = self.items(name="Spark Off Your Skin")
        self.assertTrue(spark)
        blob = json.dumps(spark[0])
        self.assertIn("stamina.bonuses.echelon", blob)

    # ---- leveled treasure text ----
    def test_treasure_leveled_text_in_description(self):
        blade = self.items(name="Executioner's Blade")
        self.assertTrue(blade)
        desc = blade[0]["system"]["description"]["value"]
        self.assertIn("extra 1 psychic damage", desc)

    # ---- singular/plural name drift (FS 'Mighty Leaps' vs pack 'Mighty Leap') ----
    def test_mighty_leaps_matches_pack_item(self):
        item = self.items(name="Mighty Leap")
        self.assertTrue(item, "hero-file name should map to the pack item")
        self.assertEqual(item[0]["system"]["_dsid"], "mighty-leap")


class TestPluralVariantLookup(unittest.TestCase):
    """Reverse name matching bridges singular/plural drift (native pack
    drags carry the pack's singular name with no FS id)."""

    @classmethod
    def setUpClass(cls):
        cls.fs = FsData(os.path.join(REPO, "fs_data"))

    def test_singular_name_finds_plural_feature(self):
        hit = self.fs.global_index.name_one("Mighty Leap")
        self.assertIsNotNone(hit)
        self.assertEqual(hit.get("id"), "fury-1-4")

    def test_exact_lookup_still_works(self):
        hit = self.fs.global_index.name_one("Mighty Leaps")
        self.assertIsNotNone(hit)
        self.assertEqual(hit.get("id"), "fury-1-4")


class TestProjectEmission(unittest.TestCase):
    """state.projects -> Foundry 'project' items (change
    add-project-and-inventory-conversion, task 1.4)."""

    @classmethod
    def setUpClass(cls):
        with open(KETH, encoding="utf-8") as fh:
            hero = json.load(fh)
        cls.compendium = load_compendium_items(
            os.path.join(REPO, "draw_steel_repo", "src", "packs"))
        cls.doc = convert_character(hero, cls.compendium)
        cls.hero = hero

    def _convert(self, mutate):
        hero = json.loads(json.dumps(self.hero))
        mutate(hero)
        return convert_character(hero, self.compendium)

    def test_project_item_emitted(self):
        items = [i for i in self.doc["items"] if i.get("type") == "project"]
        self.assertEqual(len(items), 1)
        system = items[0]["system"]
        self.assertEqual(system["_dsid"], "item-blade-of-quintessence-crafting")
        self.assertEqual(items[0]["name"], "Craft Blade of Quintessence")
        self.assertEqual(system["type"], "crafting")
        self.assertEqual(system["goal"], 450)
        self.assertEqual(system["points"], 11)
        self.assertEqual(system["rollCharacteristic"],
                         ["might", "reason", "intuition"])
        self.assertIn("ruby hardened", system["prerequisites"])
        self.assertEqual(system["projectSource"], "Texts or lore in Zaliac")

    def test_project_yield_links_pack_treasure(self):
        # Blade of Quintessence is not owned, so the link targets the pack.
        items = [i for i in self.doc["items"] if i.get("type") == "project"]
        doc_uuid = items[0]["system"]["yield"]["document"]
        self.assertTrue(doc_uuid.startswith("Compendium.draw-steel.rewards."))

    def test_owned_craft_target_links_actor_item(self):
        def mutate(hero):
            hero["state"]["projects"].append({
                "id": "item-executioners-blade-crafting",
                "name": "Craft Executioner's Blade",
                "description": "Craft an Executioner's Blade.",
                "itemPrerequisites": "The skull of a convicted criminal",
                "source": "Texts or lore in Caelian",
                "characteristic": ["Might", "Reason", "Intuition"],
                "goal": 450, "isCustom": False,
                "progress": {"prerequisites": True, "source": True,
                             "followerID": None, "points": 3},
            })
        doc = self._convert(mutate)
        actor_id = doc["_id"]
        blade = next(i for i in doc["items"]
                     if i.get("type") == "treasure"
                     and i["name"] == "Executioner's Blade")
        project = next(i for i in doc["items"]
                       if i.get("type") == "project"
                       and i["name"] == "Craft Executioner's Blade")
        self.assertEqual(
            project["system"]["yield"]["document"],
            f"Actor.{actor_id}.Item.{blade['_id']}")

    def test_empty_projects_emits_nothing(self):
        doc = self._convert(lambda hero: hero["state"].update(projects=[]))
        self.assertEqual([i for i in doc["items"]
                          if i.get("type") == "project"], [])

    def test_malformed_project_entry_skipped(self):
        def mutate(hero):
            hero["state"]["projects"] = ["nope", hero["state"]["projects"][0]]
        doc = self._convert(mutate)
        self.assertEqual(len([i for i in doc["items"]
                              if i.get("type") == "project"]), 1)

    # ---- inventory quantity / crafting text ----
    def test_treasure_quantity_from_count(self):
        def mutate(hero):
            for it in hero["state"]["inventory"]:
                if "Blade" in it["name"]:
                    it["count"] = 3
        doc = self._convert(mutate)
        blade = next(i for i in doc["items"]
                     if i.get("type") == "treasure"
                     and i["name"] == "Executioner's Blade")
        self.assertEqual(blade["system"]["quantity"], 3)

    def test_treasure_crafting_text_surface(self):
        blade = next(i for i in self.doc["items"]
                     if i.get("type") == "treasure"
                     and i["name"] == "Executioner's Blade")
        desc = blade["system"]["description"]["value"]
        self.assertIn("Crafting:", desc)
        self.assertIn("skull of a convicted criminal", desc)
        self.assertIn("goal 450", desc)


if __name__ == "__main__":
    unittest.main()
