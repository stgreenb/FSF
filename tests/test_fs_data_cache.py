"""Tests for the fs_data cache, sample cache, and payload provider (1.2-1.5)."""

import json
import os
import shutil
import tempfile
import unittest

from converter.reverse.fs_data_cache import (
    FsData, cache_path_for, check_freshness, current_repo_sha, find_cache,
    install_dump, norm_key,
)
from converter.reverse.loss_report import LossReport
from converter.reverse.payload_provider import (
    PayloadProvider, SOURCE_DUMP, SOURCE_SAMPLE,
)
from converter.reverse.sample_cache import SampleCache

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DUMP_DIR = os.path.join(REPO, "fs_data")
CORPUS = os.path.join(REPO, "*.ds-hero")


def _dump_available():
    return os.path.isfile(os.path.join(DUMP_DIR, "classes.json"))


@unittest.skipUnless(_dump_available(), "fs_data dump not built")
class TestFsDataCache(unittest.TestCase):
    """Cache hit, miss-with-source, corrupt-cache recovery (task 1.2)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="fsf-cache-test-", dir="/tmp/opencode")
        # isolated cache root: never write into the real ~/.cache tree
        self.root = os.path.join(self.tmp, "fs_data")
        os.makedirs(self.root)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_install_then_cache_hit(self):
        dest = install_dump(DUMP_DIR, "deadbeef", cache_root=self.root)
        self.assertEqual(dest, cache_path_for("deadbeef", self.root))
        found = find_cache("deadbeef", cache_root=self.root)
        self.assertEqual(found, dest)
        fs = FsData(found)
        self.assertEqual(fs.sha, "deadbeef")
        self.assertIsNotNone(fs.get_payload("class-elementalist"))

    def test_find_cache_most_recent_without_sha(self):
        install_dump(DUMP_DIR, "aaaa1111", cache_root=self.root)
        dest_b = install_dump(DUMP_DIR, "bbbb2222", cache_root=self.root)
        self.assertEqual(find_cache(cache_root=self.root), dest_b)

    def test_corrupt_cache_recovers_by_reinstall(self):
        dest = install_dump(DUMP_DIR, "corrupt1", cache_root=self.root)
        with open(os.path.join(dest, "classes.json"), "w") as fh:
            fh.write("{broken")
        with self.assertRaises(ValueError):
            FsData(dest)
        # A fresh dump install overwrites the corrupt files and works again.
        install_dump(DUMP_DIR, "corrupt1", cache_root=self.root)
        fs = FsData(find_cache("corrupt1", cache_root=self.root))
        self.assertIsNotNone(fs.get_payload("class-elementalist"))

    def test_freshness_check(self):
        sha = current_repo_sha(os.path.join(REPO, "forgesteel_repo"))
        if sha is None:
            self.skipTest("forgesteel_repo git HEAD unavailable")
        self.assertTrue(check_freshness(os.path.join(REPO, "forgesteel_repo"), sha))
        self.assertFalse(check_freshness(os.path.join(REPO, "forgesteel_repo"),
                                         "stale123"))


@unittest.skipUnless(_dump_available(), "fs_data dump not built")
class TestResolution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fs = FsData(DUMP_DIR)

    def test_id_drift_rules(self):
        # culture suffix strip: memonek-culture -> culture-memonek
        self.assertEqual(
            self.fs.resolve_kind("culture", "memonek-culture", "")["id"],
            "culture-memonek")
        # complication prefix: fire-and-chaos -> comp-fire-and-chaos
        self.assertEqual(
            self.fs.resolve_kind("complication", "fire-and-chaos", "")["id"],
            "comp-fire-and-chaos")
        # perk alias drift: traveling-artisan -> perk-travelling-artisan
        self.assertEqual(
            self.fs.resolve_kind("perk", "traveling-artisan", "")["id"],
            "perk-travelling-artisan")
        # kit prefix: raider -> kit-raider
        self.assertEqual(
            self.fs.resolve_kind("kit", "raider", "")["id"], "kit-raider")

    def test_name_drift_quote_unification(self):
        hit = self.fs.resolve_feature("strike-now", '"Strike Now!"',
                                      self.fs.data["classes"]["class-tactician"],
                                      prefer="ability")
        self.assertIsNotNone(hit)
        self.assertIn("strike now", norm_key(hit["name"]))

    def test_type_aware_disambiguation(self):
        tac = self.fs.data["classes"]["class-tactician"]
        as_ability = self.fs.resolve_feature("mark", "Mark", tac, prefer="ability")
        as_feature = self.fs.resolve_feature("mark", "Mark", tac, prefer="feature")
        self.assertIsNotNone(as_ability)
        self.assertIsNotNone(as_feature)
        self.assertEqual(as_ability["type"], "Ability")
        self.assertNotEqual(as_ability["id"], as_feature["id"])

    def test_trait_prefers_toplevel_fixed_feature(self):
        devil = self.fs.data["ancestries"]["ancestry-devil"]
        hit = self.fs.resolve_trait(devil, "silver-tongue", "Silver Tongue")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["id"], "devil-feature-1")

    def test_subclass_resolution(self):
        el = self.fs.data["classes"]["class-elementalist"]
        hit = self.fs.resolve_subclass(el, "fire", "Fire")
        self.assertEqual(hit["id"], "elementalist-sub-2")

    def test_settings_membership(self):
        settings, uncertain = self.fs.settings_for(
            ["ancestry-time-raider", "class-elementalist", "not-a-real-id"])
        self.assertEqual(settings, ["core", "orden"])
        self.assertEqual(uncertain, ["not-a-real-id"])


class TestSampleCache(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.samples = SampleCache(CORPUS)

    def test_known_sample_dsid_resolves(self):
        payload = self.samples.get_payload("memonek-feature-1")
        self.assertIsNotNone(payload)
        self.assertEqual(payload["name"], "Fall Lightly")

    def test_unknown_dsid_misses(self):
        self.assertIsNone(self.samples.get_payload("no-such-thing-xyz"))


@unittest.skipUnless(_dump_available(), "fs_data dump not built")
class TestPayloadProvider(unittest.TestCase):
    def setUp(self):
        self.dump_dir = DUMP_DIR
        self.samples = SampleCache(CORPUS)

    def _provider(self, report=None):
        return PayloadProvider(FsData(self.dump_dir), self.samples, report)

    def test_dump_hit(self):
        obj, src = self._provider().get("class-elementalist")
        self.assertIsNotNone(obj)
        self.assertEqual(src, SOURCE_DUMP)

    def test_sample_fallback(self):
        # A dsid present in samples but absent from the dump dicts.
        provider = self._provider()
        dsid = next(iter(provider.samples.index.by_id))
        if provider.fs_data.get_payload(dsid) is not None:
            self.skipTest("no sample-only dsid available in this corpus")
        obj, src = provider.get(dsid)
        self.assertEqual(src, SOURCE_SAMPLE)
        self.assertIsNotNone(obj)

    def test_divergence_dump_wins_and_warns(self):
        report = LossReport()
        provider = self._provider(report)
        # Inject a divergent sample payload for a dsid that IS in the dump.
        dsid = "kit-raider"
        provider.samples.index.by_id[dsid] = {"id": dsid, "name": "Raider",
                                              "type": "Kit", "tampered": True}
        obj, src = provider.get(dsid)
        self.assertEqual(src, SOURCE_DUMP)
        self.assertNotIn("tampered", json.dumps(obj))
        self.assertTrue(any(w["code"] == "payload-divergence" for w in report.warnings))

    def test_miss_returns_none(self):
        obj, src = self._provider().get("definitely-not-here-9999")
        self.assertEqual((obj, src), (None, None))


if __name__ == "__main__":
    unittest.main()
