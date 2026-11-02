"""Unit tests for the grant reconciliation post-pass
(change fix-compendium-grant-reconciliation, design D2/D2a)."""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from converter.grant_reconcile import (
    SelectionContext, build_selection_context, reconcile)


def item(name, type_, dsid=None, advancements=None):
    it = {"name": name, "type": type_, "system": {}}
    if dsid:
        it["system"]["_dsid"] = dsid
    if advancements:
        it["system"]["advancements"] = advancements
    return it


def comp(name, type_, id_, **extra):
    d = {"name": name, "type": type_, "_id": id_, "system": {}}
    d.update(extra)
    return d


class TestDedupe(unittest.TestCase):
    def test_exact_duplicate_collapses(self):
        char = {"items": [item("Prayer of Steel", "feature"),
                          item("Prayer of Steel", "feature")]}
        out = reconcile(char, {}, SelectionContext(hero_level=1))
        self.assertEqual(
            sum(1 for i in out["items"] if i["name"] == "Prayer of Steel"), 1)

    def test_case_sensitive(self):
        char = {"items": [item("alpha", "feature"), item("Alpha", "feature")]}
        out = reconcile(char, {}, SelectionContext(hero_level=1))
        self.assertEqual(len(out["items"]), 2)

    def test_activate_pair_survives(self):
        char = {"items": [item("Repulsive Ward", "ability", dsid="rw"),
                          item("Repulsive Ward", "ability",
                               dsid="rw-activate")]}
        out = reconcile(char, {}, SelectionContext(hero_level=1))
        self.assertEqual(len(out["items"]), 2)

    def test_same_dsid_ability_collapses(self):
        char = {"items": [item("Same", "ability", dsid="x"),
                          item("Same", "ability", dsid="x")]}
        out = reconcile(char, {}, SelectionContext(hero_level=1))
        self.assertEqual(len(out["items"]), 1)


class TestTrim(unittest.TestCase):
    HERO = {
        "level": 1,
        "subclass": {"featuresByLevel": [
            {"level": 1, "features": [
                {"name": "Core Gift", "type": "Feature"}]},
            {"level": 4, "features": [
                {"name": "Blessed Domain", "type": "Feature"}]},
        ]},
    }

    def test_above_level_dropped(self):
        ctx = build_selection_context(self.HERO, 1)
        char = {"items": [item("Core Gift", "feature"),
                          item("Blessed Domain", "feature")]}
        out = reconcile(char, {}, ctx)
        names = [i["name"] for i in out["items"]]
        self.assertIn("Core Gift", names)
        self.assertNotIn("Blessed Domain", names)

    def test_keep_if_any_grant(self):
        hero = copy.deepcopy(self.HERO)
        hero["subclass"]["featuresByLevel"][0]["features"].append(
            {"name": "Blessed Domain", "type": "Feature"})  # also at lvl 1
        ctx = build_selection_context(hero, 1)
        char = {"items": [item("Blessed Domain", "feature")]}
        out = reconcile(char, {}, ctx)
        self.assertIn("Blessed Domain", [i["name"] for i in out["items"]])

    def test_no_evidence_never_trimmed(self):
        ctx = build_selection_context(self.HERO, 1)
        char = {"items": [item("Homebrew Wonder", "feature")]}
        out = reconcile(char, {}, ctx)
        self.assertIn("Homebrew Wonder", [i["name"] for i in out["items"]])

    def test_container_cascade(self):
        hero = {"level": 1, "class": {"featuresByLevel": [
            {"level": 5, "features": [{
                "name": "Grand Container", "type": "Multiple Features",
                "data": {"features": [
                    {"name": "Child Feature", "type": "Feature"}]}},
                # child also referenced only above level -> drops with parent
            ]},
        ]}}
        ctx = build_selection_context(hero, 1)
        char = {"items": [item("Grand Container", "feature"),
                          item("Child Feature", "feature")]}
        out = reconcile(char, {}, ctx)
        names = [i["name"] for i in out["items"]]
        self.assertNotIn("Grand Container", names)
        self.assertNotIn("Child Feature", names)

    def test_no_level_skips_trim(self):
        ctx = build_selection_context(self.HERO, None)
        char = {"items": [item("Blessed Domain", "feature")]}
        out = reconcile(char, {}, ctx)
        self.assertIn("Blessed Domain", [i["name"] for i in out["items"]])


class TestCompletion(unittest.TestCase):
    def test_grant_all_adds_missing(self):
        pool_uuid = "Compendium.draw-steel.classes.Item.aaaaaaaaaaaaaaag"
        granting = item("Metakinetic Mastery", "feature", advancements={
            "a1": {"type": "itemGrant", "level": 1,
                   "pool": [{"uuid": pool_uuid}]}})
        compendium = {"metaki-hit": comp("Metakinetic Strike", "ability",
                                         "aaaaaaaaaaaaaaag")}
        ctx = SelectionContext(hero_level=1)
        out = reconcile({"items": [granting]}, compendium, ctx)
        self.assertIn("Metakinetic Strike",
                      [i["name"] for i in out["items"]])
        self.assertNotIn("_id", out["items"][1])  # junk stripped

    def test_choose_n_only_selected_emitted(self):
        uuid_a = "Compendium.draw-steel.classes.Item.aaaaaaaaaaaaaaab"
        uuid_b = "Compendium.draw-steel.classes.Item.aaaaaaaaaaaaaaac"
        granting = item("Domain Pool", "subclass", advancements={
            "d1": {"type": "itemGrant", "chooseN": 1,
                   "pool": [{"uuid": uuid_a}, {"uuid": uuid_b}]}})
        compendium = {"a": comp("Fire Domain", "subclass",
                                "aaaaaaaaaaaaaaab"),
                      "b": comp("Ice Domain", "subclass",
                                "aaaaaaaaaaaaaaac")}
        ctx = SelectionContext(hero_level=1,
                               choices={"Domain Pool": ["Fire Domain"]})
        out = reconcile({"items": [granting]}, compendium, ctx)
        names = [i["name"] for i in out["items"]]
        self.assertIn("Fire Domain", names)
        self.assertNotIn("Ice Domain", names)

    def test_cross_pool_single_copy(self):
        # 3.1b: same item in a grant-all pool AND a choose-N pick -> one copy
        uuid_x = "Compendium.draw-steel.classes.Item.aaaaaaaaaaaaaaad"
        grant_all = item("Container A", "feature", advancements={
            "g": {"type": "itemGrant", "level": 1,
                  "pool": [{"uuid": uuid_x}]}})
        chooser = item("Container B", "feature", advancements={
            "c": {"type": "itemGrant", "chooseN": 1,
                  "pool": [{"uuid": uuid_x}]}})
        compendium = {"x": comp("Shared Item", "feature", "aaaaaaaaaaaaaaad")}
        ctx = SelectionContext(hero_level=1,
                               choices={"Container B": ["Shared Item"]})
        out = reconcile({"items": [grant_all, chooser]}, compendium, ctx)
        self.assertEqual(
            sum(1 for i in out["items"] if i["name"] == "Shared Item"), 1)


class TestSkillsAndSummons(unittest.TestCase):
    def test_skill_harvest(self):
        granting = item("Warden Gift", "feature", advancements={
            "s": {"type": "skill", "chooseN": 1}})
        ctx = SelectionContext(hero_level=1,
                               choices={"Warden Gift": ["Navigate"]})
        char = {"items": [granting],
                "system": {"hero": {"hero": {"skills": ["Endurance"]}}}}
        out = reconcile(char, {}, ctx)
        self.assertEqual(out["system"]["hero"]["hero"]["skills"],
                         ["Endurance", "Navigate"])

    def test_summon_flags_all_or_nothing(self):
        summoner = item("Summon Beast", "feature", advancements={
            "m": {"type": "summon", "chooseN": 1}})
        ctx = SelectionContext(hero_level=1,
                               choices={"Summon Beast": ["Apex Husk"]})

        class FakeIndex(dict):
            def resolve_by_name(self, name):
                if name == "Apex Husk":
                    return ({"name": name}, "Compendium.draw-steel."
                            "monsters.Actor.abcdef")
                return None

        out = reconcile({"items": [copy.deepcopy(summoner)]},
                        FakeIndex(), ctx)
        flags = out["items"][0]["flags"]["draw-steel"]["advancement"]["m"]
        self.assertEqual(flags["selected"],
                         ["Compendium.draw-steel.monsters.Actor.abcdef"])
        # unresolved pick -> no partial flags
        ctx2 = SelectionContext(hero_level=1,
                                choices={"Summon Beast": ["Nowhere Fiend"]})
        out2 = reconcile({"items": [copy.deepcopy(summoner)]},
                         FakeIndex(), ctx2)
        self.assertNotIn("flags", out2["items"][0])


class TestFailureSemantics(unittest.TestCase):
    def test_exception_returns_original(self):
        char = {"items": [item("A", "feature", advancements={
            "g": {"type": "itemGrant", "pool": [{"uuid": "x.y"}]}})]}

        class Boom(dict):
            def values(self):  # explode inside grant-all step
                raise RuntimeError("boom")

        snapshot = copy.deepcopy(char)
        out = reconcile(char, Boom(), SelectionContext(hero_level=1))
        self.assertEqual(out, snapshot)
        self.assertIs(out, char)  # original returned unchanged

    def test_input_never_mutated(self):
        char = {"items": [item("Dup", "feature"), item("Dup", "feature")]}
        snapshot = copy.deepcopy(char)
        reconcile(char, {}, SelectionContext(hero_level=1))
        self.assertEqual(char, snapshot)


if __name__ == "__main__":
    unittest.main()
