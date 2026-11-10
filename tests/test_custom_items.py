"""Tests for carry-unknown-treasure-to-print: synthesized inventory entries,
custom projects, determinism, validator acceptance, and the forward trip."""
import copy
import json
import os
import subprocess
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from converter.reverse import ds_hero_schema
from converter.reverse.reverse_mapper import ReverseMapper

FIXTURE = os.path.join(REPO, "tests", "fixtures", "foundry",
                       "custom-weapon-export.json")


def _run_reverse(path, out_path):
    proc = subprocess.run(
        [sys.executable, os.path.join(REPO, "foundry_to_forgesteel.py"),
         path, out_path],
        capture_output=True, text=True, cwd=REPO)
    report = None
    if os.path.exists(out_path + ".report.json"):
        with open(out_path + ".report.json", encoding="utf-8") as fh:
            report = json.load(fh)
    return proc.returncode, report


class TestCustomItemSynthesis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = "/tmp/opencode/uat-cw.ds-hero"
        cls.rc, cls.report = _run_reverse(FIXTURE, cls.out)
        with open(cls.out, encoding="utf-8") as fh:
            cls.hero = json.load(fh)
        cls.inv = {i["name"]: i for i in cls.hero["state"]["inventory"]}

    def _loss(self, name):
        return [l for l in self.report["losses"] if l["item"] == name]

    def test_fixture_converts_clean(self):
        self.assertEqual(self.rc, 0)

    def test_custom_weapon_synthesized(self):
        # one entry from the clean fixture; same-name collision covered in
        # test_same_name_ids_differ with the duplicate-name fixture
        entries = [i for i in self.hero["state"]["inventory"]
                   if i["name"] == "Widow's Fang"]
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertTrue(entry["id"].startswith("custom-widows-fang"))
        self.assertEqual(entry["type"], "Leveled Weapon")  # keyword refinement
        self.assertEqual(entry["count"], 1)
        self.assertIn("*widow venom*", entry["description"])
        self.assertIn("- +1 damage vs poisoned targets", entry["description"])
        self.assertEqual(entry["featuresByLevel"], [])
        self.assertEqual(entry["imbuements"], [])
        self.assertEqual(entry["customizationsByLevel"], [])
        self.assertEqual(entry["crafting"]["isCustom"], True)
        self.assertEqual(entry["crafting"]["goal"], 100)
        # defaulted report, no payload-unavailable/unmappable for it
        losses = self._loss("Widow's Fang")
        self.assertEqual(len(losses), 1)  # one synthesized entry
        for loss in losses:
            self.assertEqual(loss["reason"], "defaulted")
        self.assertNotIn("payload-unavailable",
                         {l["reason"] for l in losses})

    def test_same_name_ids_differ(self):
        # duplicate-name fixture: same-name treasures get unique ids
        dup_fixture = os.path.join(
            os.path.dirname(FIXTURE), "custom-weapon-duplicate-name-export.json")
        rc, _ = _run_reverse(dup_fixture,
                             "/tmp/opencode/uat-cw-dup.ds-hero")
        self.assertEqual(rc, 0)
        with open("/tmp/opencode/uat-cw-dup.ds-hero", encoding="utf-8") as fh:
            hero2 = json.load(fh)
        entries = [i for i in hero2["state"]["inventory"]
                   if i["name"] == "Widow's Fang"]
        self.assertEqual(len(entries), 2)
        self.assertNotEqual(entries[0]["id"], entries[1]["id"])

    def test_string_quantity_tolerated(self):
        # second Widow's Fang in the dup fixture carries quantity "2" (string)
        dup_fixture = os.path.join(
            os.path.dirname(FIXTURE), "custom-weapon-duplicate-name-export.json")
        _run_reverse(dup_fixture, "/tmp/opencode/uat-cw-dup2.ds-hero")
        with open("/tmp/opencode/uat-cw-dup2.ds-hero", encoding="utf-8") as fh:
            hero2 = json.load(fh)
        entries = [i for i in hero2["state"]["inventory"]
                   if i["name"] == "Widow's Fang"]
        counts = sorted(e["count"] for e in entries)
        self.assertEqual(counts, [1, 2])

    def test_trinket_type_mapping(self):
        coin = self.inv["Lucky Coin"]
        self.assertEqual(coin["type"], "Trinket (1st echelon)")
        self.assertEqual(coin["count"], 2)

    def test_custom_project_from_project_item(self):
        projects = {p["name"]: p for p in self.hero["state"]["projects"]}
        self.assertIn("Craft Widow's Fang", projects)
        prj = projects["Craft Widow's Fang"]
        self.assertTrue(prj["isCustom"])
        self.assertEqual(prj["progress"]["points"], 25)
        self.assertEqual(prj["goal"], 100)
        # exactly one entry
        self.assertEqual(
            [p["name"] for p in self.hero["state"]["projects"]]
            .count("Craft Widow's Fang"), 1)

    def test_points_only_rule_block_makes_no_project(self):
        # Lucky Coin has a project block but no project item -> no entry
        names = [p["name"] for p in self.hero["state"]["projects"]]
        self.assertNotIn("Craft Lucky Coin", names)
        self.assertNotIn("Lucky Coin", names)

    def test_determinism_ids_stable_across_runs(self):
        rc2, _ = _run_reverse(FIXTURE, "/tmp/opencode/uat-cw2.ds-hero")
        self.assertEqual(rc2, 0)
        with open("/tmp/opencode/uat-cw2.ds-hero", encoding="utf-8") as fh:
            hero2 = json.load(fh)
        ids1 = sorted(i["id"] for i in self.hero["state"]["inventory"])
        ids2 = sorted(i["id"] for i in hero2["state"]["inventory"])
        self.assertEqual(ids1, ids2)

    def test_mechanical_effect_disclosed(self):
        # Widow's Fang carries a pure-mechanics effect (Venom Edge:
        # damage.bonuses.treasure +1, no text) -> loud, specific warning
        warns = [w for w in self.report["warnings"]
                 if w["code"] == "mechanical-effects-lost"]
        self.assertEqual(len(warns), 1)
        detail = warns[0]["detail"]
        self.assertIn("Widow's Fang", detail)
        self.assertIn("Venom Edge (1st level)", detail)
        self.assertIn("damage.bonuses.treasure", detail)
        self.assertIn("re-apply", detail)

    def test_validator_accepts_synthesized_shape(self):
        spec = ds_hero_schema.load_spec()
        violations = ds_hero_schema.validate_document(self.hero, spec)
        self.assertEqual(
            [v for v in violations if "inventory" in v], [],
            f"synthesized entries rejected: {violations}")


class TestSynthesisEdgeCases(unittest.TestCase):
    """Unit-level edge cases on the synthesis entry point."""

    @classmethod
    def setUpClass(cls):
        cls.base = json.load(open(FIXTURE, encoding="utf-8"))

    def _reverse_with(self, mutate):
        actor = copy.deepcopy(self.base)
        mutate(actor)
        path = "/tmp/opencode/uat-cw-edge.json"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(actor, fh)
        rc, report = _run_reverse(path, "/tmp/opencode/uat-cw-edge.ds-hero")
        hero = None
        if os.path.exists("/tmp/opencode/uat-cw-edge.ds-hero"):
            with open("/tmp/opencode/uat-cw-edge.ds-hero",
                      encoding="utf-8") as fh:
                hero = json.load(fh)
        return rc, report, hero

    def test_blank_name_no_fabrication(self):
        def drop_name(actor):
            next(i for i in actor["items"] if i["name"] == "Lucky Coin")["name"] = ""
        rc, report, hero = self._reverse_with(drop_name)
        self.assertEqual(rc, 0)
        self.assertEqual(
            [i for i in hero["state"]["inventory"] if not i["name"]], [])
        self.assertIn("unmappable",
                      {l["reason"] for l in report["losses"]
                       if l["item"] in ("", "?") or l["reason"] == "unmappable"})

    def test_known_item_never_reconstructed(self):
        # Snapdragon in a treasure -> dump hydration, no defaulted entry
        def add_known(actor):
            actor["items"].append({
                "_id": "KnownSnap0000001", "name": "Snapdragon",
                "type": "treasure",
                "system": {"_dsid": "snapdragon", "quantity": 1,
                           "category": "consumable", "keywords": [],
                           "description": {"value": "<p>Boom.</p>"}}})
        rc, report, hero = self._reverse_with(add_known)
        self.assertEqual(rc, 0)
        snap = [i for i in hero["state"]["inventory"]
                if i["name"] == "Snapdragon"]
        self.assertEqual(len(snap), 1)
        self.assertTrue(snap[0]["id"].startswith("item-"))
        self.assertEqual(
            [l for l in report["losses"]
             if l["item"] == "Snapdragon" and l["reason"] == "defaulted"], [])


class TestForwardTrip(unittest.TestCase):
    """Synthesized customs ride forward back to Foundry treasures."""

    def test_forward_emits_customs(self):
        TestCustomItemSynthesis.setUpClass()
        entry = next(i for i in TestCustomItemSynthesis.hero["state"]["inventory"]
                     if i["name"] == "Widow's Fang")
        hero = TestCustomItemSynthesis.hero
        hero["state"]["inventory"] = [entry]
        path = "/tmp/opencode/uat-cw-fwd.ds-hero"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(hero, fh)
        out = "/tmp/opencode/uat-cw-fwd.json"
        proc = subprocess.run(
            [sys.executable, os.path.join(REPO, "forgesteel_converter.py"),
             path, out], capture_output=True, text=True, cwd=REPO)
        self.assertEqual(proc.returncode, 0)
        doc = json.load(open(out, encoding="utf-8"))
        treasure = next(i for i in doc["items"]
                        if i.get("name") == "Widow's Fang")
        self.assertEqual(treasure["type"], "treasure")
        self.assertEqual(treasure["system"]["quantity"], 1)
        desc = treasure["system"]["description"]["value"]
        self.assertIn("widow venom", desc)
        self.assertIn("smithing tools", desc)  # crafting text surfaced


if __name__ == "__main__":
    unittest.main()
