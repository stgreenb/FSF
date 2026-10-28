"""Tests for the .ds-hero structural schema boundary (tasks 3.1-3.2)."""

import copy
import glob
import json
import os
import unittest

from converter.reverse.ds_hero_schema import (
    SPEC_PATH, derive_invariants, load_spec, refresh_spec, validate_document,
)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS = os.path.join(REPO, "*.ds-hero")


class TestCorpusPasses(unittest.TestCase):
    def test_every_sample_passes_validation(self):
        paths = sorted(glob.glob(CORPUS))
        self.assertGreater(len(paths), 10)
        spec = load_spec()
        for path in paths:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
            violations = validate_document(doc, spec)
            self.assertEqual(violations, [], f"{os.path.basename(path)}: {violations}")


class TestViolationsDetected(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = load_spec()
        with open(sorted(glob.glob(CORPUS))[0], encoding="utf-8") as fh:
            cls.doc = json.load(fh)

    def test_missing_state_key_detected(self):
        doc = copy.deepcopy(self.doc)
        del doc["state"]["encounterState"]
        violations = validate_document(doc, self.spec)
        self.assertTrue(any(v.startswith("$/state/encounterState")
                            for v in violations), violations)

    def test_feature_missing_data_key_detected(self):
        doc = copy.deepcopy(self.doc)
        feature = doc["career"]["features"][0]
        del feature["data"]
        violations = validate_document(doc, self.spec)
        self.assertTrue(any(f"required key 'data' missing" in v
                            for v in violations), violations)

    def test_state_type_mismatch_detected(self):
        doc = copy.deepcopy(self.doc)
        doc["state"]["xp"] = "lots"
        violations = validate_document(doc, self.spec)
        self.assertTrue(any(v.startswith("$/state/xp") and "integer" in v
                            for v in violations), violations)

    def test_bad_class_level_detected(self):
        doc = copy.deepcopy(self.doc)
        doc["class"]["level"] = 42
        violations = validate_document(doc, self.spec)
        self.assertTrue(any(v.startswith("$/class/level")
                            for v in violations), violations)


class TestRefresh(unittest.TestCase):
    def test_refresh_is_idempotent(self):
        out_a = "/tmp/opencode/fsf-spec-a.json"
        out_b = "/tmp/opencode/fsf-spec-b.json"
        os.makedirs("/tmp/opencode", exist_ok=True)
        refresh_spec(CORPUS, out_a)
        refresh_spec(CORPUS, out_b)
        with open(out_a) as fh_a, open(out_b) as fh_b:
            self.assertEqual(fh_a.read(), fh_b.read())

    def test_generated_spec_matches_committed_spec(self):
        out = "/tmp/opencode/fsf-spec-c.json"
        refresh_spec(CORPUS, out)
        with open(out) as fh:
            generated = json.load(fh)
        self.assertEqual(generated, load_spec(SPEC_PATH))


if __name__ == "__main__":
    unittest.main()
