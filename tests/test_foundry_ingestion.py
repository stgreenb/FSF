"""Tests for the Foundry actor ingestion boundary (tasks 2.2-2.4)."""

import json
import os
import unittest

from converter.reverse.ingestion import (
    ConversionInputError, PackIndex, load_actor, extract_selections,
)
from converter.reverse.loss_report import LossReport

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = os.path.join(REPO, "draw_steel_repo", "src", "packs")
PYRE_EXPORT = os.path.join(REPO, "fvtt-Actor-pyre-E5XwHW1ZJGBb1hAI.json")
SWAMI_EXPORT = os.path.join(REPO, "fvtt-Actor-swami-native-WtgbYZL7JqKb9H07.json")


class TestActorLoading(unittest.TestCase):
    def test_valid_export_classifies_without_losses(self):
        report = LossReport()
        actor = load_actor(PYRE_EXPORT, report=report)
        self.assertEqual(actor.name, "Pyre")
        self.assertGreater(len(actor.items), 30)
        self.assertEqual(report.losses, [])
        self.assertIsNotNone(actor.first_of_type("class"))
        self.assertEqual(actor.first_of_type("class").dsid, "elementalist")
        self.assertEqual(actor.first_of_type("class").level, 2)

    def test_all_native_export_items_resolve_dsid(self):
        for export in (PYRE_EXPORT, SWAMI_EXPORT):
            report = LossReport()
            load_actor(export, report=report)
            provenance_losses = [
                l for l in report.losses if l["reason"] in ("unmappable",)
            ]
            self.assertEqual(provenance_losses, [], export)

    def test_ds_hero_fed_to_wrong_direction_rejected(self):
        with self.assertRaises(ConversionInputError) as ctx:
            load_actor(os.path.join(REPO, "Calder Sendric.ds-hero"))
        self.assertIn("not a Foundry actor export", str(ctx.exception))

    def test_broken_json_rejected(self):
        path = "/tmp/opencode/fsf-test-broken.json"
        os.makedirs("/tmp/opencode", exist_ok=True)
        with open(path, "w") as fh:
            fh.write("{broken")
        with self.assertRaises(ConversionInputError):
            load_actor(path)

    def test_missing_class_aborts(self):
        path = "/tmp/opencode/fsf-test-noclass.json"
        with open(path, "w") as fh:
            json.dump({"name": "X", "system": {}, "items": []}, fh)
        with self.assertRaises(ConversionInputError) as ctx:
            load_actor(path)
        self.assertIn("no class item", str(ctx.exception))

    def test_malformed_items_isolated_and_survives(self):
        report = LossReport()
        with open(PYRE_EXPORT) as fh:
            doc = json.load(fh)
        doc["items"].append(42)
        doc["items"].append(None)
        doc["items"].append({"name": "NoType"})
        path = "/tmp/opencode/fsf-test-malformed.json"
        with open(path, "w") as fh:
            json.dump(doc, fh)
        actor = load_actor(path, report=report)
        self.assertEqual(actor.malformed_count, 3)
        malformed = [l for l in report.losses
                     if "malformed items[] entry" in l["detail"]]
        self.assertEqual(len(malformed), 3)
        self.assertTrue(all(l["reason"] == "unsupported-construct"
                            and l["action"] == "dropped" for l in malformed))
        self.assertGreater(len(actor.items), 30)  # iteration survived

    def test_unknown_item_type_reported(self):
        report = LossReport()
        with open(PYRE_EXPORT) as fh:
            doc = json.load(fh)
        doc["items"].append({
            "name": "Cart", "type": "vehicle", "system": {"_dsid": "cart"},
        })
        path = "/tmp/opencode/fsf-test-unknown.json"
        with open(path, "w") as fh:
            json.dump(doc, fh)
        actor = load_actor(path, report=report)
        unknown = [l for l in report.losses if l["item"] == "Cart"]
        self.assertEqual(len(unknown), 1)
        self.assertEqual(unknown[0]["reason"], "unsupported-construct")


class TestPackIndex(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = PackIndex.from_pack_directory(PACKS)

    def test_index_populated(self):
        self.assertGreater(len(self.index.by_dsid), 1000)
        self.assertEqual(self.index.by_dsid["memonek"]["type"], "ancestry")

    def test_homebrew_unmappable(self):
        report = LossReport()
        path = "/tmp/opencode/fsf-test-homebrew.json"
        with open(PYRE_EXPORT) as fh:
            doc = json.load(fh)
        doc["items"].append({
            "name": "Custom Party Trick", "type": "feature",
            "system": {"description": {"value": "x"}},  # no _dsid
        })
        with open(path, "w") as fh:
            json.dump(doc, fh)
        load_actor(path, pack_index=self.index, report=report)
        homebrew = [l for l in report.losses
                    if l["item"] == "Custom Party Trick"]
        self.assertEqual(len(homebrew), 1)
        self.assertEqual(homebrew[0]["reason"], "unmappable")
        self.assertEqual(homebrew[0]["action"], "dropped")

    def test_name_only_item_recovered(self):
        report = LossReport()
        path = "/tmp/opencode/fsf-test-nameonly.json"
        with open(PYRE_EXPORT) as fh:
            doc = json.load(fh)
        doc["items"].append({"name": "Catch Breath", "type": "ability",
                             "system": {}})  # missing _dsid, name matches pack
        with open(path, "w") as fh:
            json.dump(doc, fh)
        load_actor(path, pack_index=self.index, report=report)
        recovered = [l for l in report.losses
                     if l["item"] == "Catch Breath"]
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0]["action"], "recovered-by-name")
        self.assertEqual(recovered[0]["dsid"], "catch-breath")


class TestSelections(unittest.TestCase):
    def test_culture_language_selection_recovered(self):
        actor = load_actor(PYRE_EXPORT)
        culture = actor.first_of_type("culture")
        selections = culture.selections()
        langs = [s for s in selections if s.kind == "language"]
        self.assertTrue(any("axiomatic" in s.selected for s in langs))
        skills = [s for s in selections if s.kind == "skill"]
        self.assertTrue(skills)
        self.assertTrue(all(s.level is None or isinstance(s.level, int)
                            for s in selections))

    def test_flagless_item_yields_empty_selections(self):
        actor = load_actor(PYRE_EXPORT)
        ability = actor.by_type("ability")[0]
        self.assertEqual(ability.selections(), [])

    def test_null_flag_selections_tolerated(self):
        actor = load_actor(PYRE_EXPORT)
        klass = actor.first_of_type("class")
        # Export has class defs with null flag entries -> only populated ones
        selections = klass.selections()
        self.assertTrue(all(s.selected for s in selections))
        self.assertEqual(extract_selections(actor.first_of_type("complication")), [])


if __name__ == "__main__":
    unittest.main()
