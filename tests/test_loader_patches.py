"""Tests for change fix-compendium-grant-reconciliation, group 1:
CompendiumIndex (name/uuid resolution, folder skip, canonical UUIDs) and
PACK_PATCHES (upstream typo corrections)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from converter.loader import CompendiumIndex, load_compendium_items

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = os.path.join(REPO, "draw_steel_repo", "src", "packs")


class TestCompendiumIndex(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = load_compendium_items(PACKS)

    def test_returns_index_subclass(self):
        self.assertIsInstance(self.index, CompendiumIndex)
        # dict behavior preserved
        self.assertGreater(len(dict(self.index)), 1000)

    def test_folder_documents_excluded(self):
        # Folder_*.json files carry no _id/name and are skipped; only real
        # documents get indexed — with canonical Actor UUIDs for npc docs.
        doc, uuid = self.index.resolve_by_name("Ajax the Invincible")
        self.assertIsNotNone(doc)
        self.assertTrue(uuid.startswith("Compendium.draw-steel.monsters.Actor."))
        # every indexed doc has an _id (folders never indexed)
        for entries in self.index.by_name.values():
            for d, _ in entries:
                self.assertIn("_id", d)

    def test_actor_docs_indexed_by_name_with_actor_uuid(self):
        # real actor document in the monsters pack
        doc, uuid = self.index.resolve_by_name("Apex Husk") or (None, None)
        if doc is None:
            # any npc_ doc works for the uuid-shape assertion
            names = [n for n, m in self.index.by_name.items()
                     if m and m[0][1] and ".Actor." in m[0][1]]
            self.assertTrue(names, "expected at least one Actor doc indexed")
            doc, uuid = self.index.by_name[names[0]][0]
        self.assertTrue(uuid.startswith("Compendium.draw-steel.monsters.Actor."),
                        uuid)

    def test_item_uuid_canonical_form(self):
        doc, uuid = self.index.resolve_by_name("Executioner's Blade")
        self.assertIsNotNone(doc)
        self.assertEqual(
            uuid,
            f"Compendium.draw-steel.rewards.Item.{doc['_id']}")

    def test_resolve_by_uuid_roundtrip(self):
        doc, _uuid = self.index.resolve_by_name("Executioner's Blade")
        self.assertIs(self.index.resolve_by_uuid(doc["_id"]), doc)

    def test_pack_patches(self):
        from converter.loader import _apply_patches
        doc = {"name": "Null Field",
               "effects": [{"changes": [
                   {"key": "system.characteristics.might.intuition",
                    "value": 1},
                   {"key": "system.stamina.max", "value": 2},
               ]}]}
        self.assertEqual(_apply_patches(doc), 1)
        keys = [c["key"] for e in doc["effects"] for c in e["changes"]]
        self.assertIn("system.characteristics.intuition.resist", keys)
        self.assertIn("system.stamina.max", keys)  # untouched

    def test_pack_patches_no_false_positive(self):
        from converter.loader import _apply_patches
        doc = {"name": "Something Else",
               "effects": [{"changes": [
                   {"key": "system.characteristics.might.intuition"}]}]}
        self.assertEqual(_apply_patches(doc), 0)
        self.assertEqual(
            doc["effects"][0]["changes"][0]["key"],
            "system.characteristics.might.intuition")

    def test_pack_patches_summoner_strike(self):
        from converter.loader import _apply_patches
        doc = {"name": "Summoner Strike",
               "system": {"effects": [
                   {"changes": [{"key": "flags-draw-steel"
                                 ".summoner-strike-range", "value": 5}]}]}}
        self.assertEqual(_apply_patches(doc), 1)
        self.assertEqual(
            doc["system"]["effects"][0]["changes"][0]["key"],
            "flags.draw-steel.summoner-strike-range")

    def test_unknown_uuid_returns_none(self):
        self.assertIsNone(self.index.resolve_by_uuid("doesNotExist1234"))

    def test_plain_dict_callers_still_work(self):
        # duck-typed resolve: plain dicts have no resolver; consumers guard
        plain = dict(self.index)
        self.assertIsNone(getattr(plain, "resolve_by_uuid", None))

    def test_duplicate_names_tolerated(self):
        # duplicates append, never raise
        idx = CompendiumIndex()
        d1 = {"_id": "a" * 16, "name": "Duplicat"}
        d2 = {"_id": "b" * 16, "name": "Duplicat"}
        idx.index_document(d1, "rewards", "Item")
        idx.index_document(d2, "rewards", "Item")
        doc, uuid = idx.resolve_by_name("Duplicat")
        self.assertIs(doc, d1)
        self.assertTrue(any("matches 2" in w for w in idx.index_warnings))


if __name__ == "__main__":
    unittest.main()
