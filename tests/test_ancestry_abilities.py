"""Unit tests for ancestry granted-ability conversion
(change fix-ancestry-granted-abilities: name normalization, type detection,
edge cases, multi-ancestry validation)."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from converter.ability_converter import AbilityConverter
from converter.loader import load_compendium_items
from converter.text_normalizer import TextNormalizer

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = os.path.join(REPO, "draw_steel_repo", "src", "packs")


def comp_item(name, itype="ability", dsid=None):
    return {"name": name, "type": itype,
            "system": {"_dsid": dsid or name.lower()}}


class TestNameNormalization(unittest.TestCase):
    """Tasks 4.5: name normalization strategies in _find_compendium_ability."""

    def test_exact_match_identical_names(self):
        items = {"x": comp_item("Psionic Bolt")}
        found = AbilityConverter._find_compendium_ability(
            "Psionic Bolt", 1, items)
        self.assertIsNotNone(found)
        self.assertEqual(found["name"], "Psionic Bolt")

    def test_normalized_match_with_space_differences(self):
        """Pack stores 'Psionic  Bolt' (double space); Forgesteel says
        'Psionic Bolt'. The sanitized display-name comparison must bridge it
        WITHOUT the known_mappings shortcut."""
        items = {"psionic-bolt": comp_item("Psionic  Bolt")}
        found = AbilityConverter._find_compendium_ability(
            "Psionic Bolt", 1, items)
        self.assertIsNotNone(found,
                             "space-drift display names must sanitize-match")
        self.assertEqual(found["name"], "Psionic  Bolt")

    def test_case_insensitive_matching(self):
        items = {"x": comp_item("PSIONIC BOLT")}
        found = AbilityConverter._find_compendium_ability(
            "psionic bolt", 1, items)
        self.assertIsNotNone(found)

    def test_unicode_normalization(self):
        """Curly apostrophe vs straight (classic FS/pack drift)."""
        items = {"x": comp_item("Mind\u2019wipe")}
        found = AbilityConverter._find_compendium_ability(
            "Mind'wipe", 1, items)
        self.assertIsNotNone(found,
                             "unicode variants must sanitize-match")

    def test_non_matching_returns_none(self):
        items = {"x": comp_item("Something Else")}
        self.assertIsNone(AbilityConverter._find_compendium_ability(
            "Psionic Bolt", 1, items))

    def test_non_ability_items_never_match(self):
        items = {"x": comp_item("Psionic Bolt", itype="feature")}
        self.assertIsNone(AbilityConverter._find_compendium_ability(
            "Psionic Bolt", 1, items))


class TestEdgeCases(unittest.TestCase):
    """Tasks 4.10-4.12: degenerate inputs must not raise."""

    def test_empty_name(self):
        items = {"x": comp_item("Psionic Bolt")}
        self.assertIsNone(
            AbilityConverter._find_compendium_ability("", 1, items))

    def test_very_long_name(self):
        long_name = "A" * 5000
        items = {"x": comp_item(long_name)}
        found = AbilityConverter._find_compendium_ability(
            long_name, 1, items)
        self.assertIsNotNone(found)

    def test_non_ascii_normalization_stable(self):
        # sanitize must be idempotent on accented input
        s1 = TextNormalizer.sanitize_for_compendium_lookup("Élan Attack")
        s2 = TextNormalizer.sanitize_for_compendium_lookup(s1)
        self.assertEqual(s1, s2)


class TestPackAncestryAbilities(unittest.TestCase):
    """Tasks 4.2/5.2/5.3: every ancestry granted ability in the origins
    packs resolves by name through the converter lookup."""

    @classmethod
    def setUpClass(cls):
        cls.compendium = load_compendium_items(PACKS)
        cls.granted = {}
        origins = os.path.join(PACKS, "origins")
        for root, dirs, files in os.walk(origins):
            if not files:
                continue
            for fname in files:
                if not fname.endswith(".json"):
                    continue
                with open(os.path.join(root, fname), encoding="utf-8") as fh:
                    try:
                        doc = json.load(fh)
                    except json.JSONDecodeError:
                        continue
                if doc.get("type") == "ability":
                    cls.granted[doc.get("name")] = doc

    def test_granted_abilities_present(self):
        self.assertGreaterEqual(len(self.granted), 15)

    def test_all_granted_abilities_resolvable(self):
        """Each pack ability must be findable from its own display name
        AND from the Forgesteel spelling (collapsed whitespace)."""
        import re
        unresolved = []
        for name in self.granted:
            fs_style = re.sub(r"\s+", " ", name).strip()
            found = AbilityConverter._find_compendium_ability(
                fs_style, 1, self.compendium)
            if found is None:
                unresolved.append(name)
        self.assertEqual(unresolved, [],
                         f"ancestry granted abilities unresolvable: "
                         f"{unresolved}")

    def test_psionic_bolt_end_to_end(self):
        """Quistis (Time Raider) must emit the pack-native ability item
        with its formula intact and type 'ability'."""
        from converter.mapper import convert_character
        with open(os.path.join(REPO, "Quistis.ds-hero"),
                  encoding="utf-8") as fh:
            hero = json.load(fh)
        doc = convert_character(hero, self.compendium)
        pb = [i for i in doc["items"]
              if (i.get("system") or {}).get("_dsid") == "psionic-bolt"]
        self.assertEqual(len(pb), 1)
        self.assertEqual(pb[0]["type"], "ability")
        power = (pb[0].get("system") or {}).get("power") or {}
        roll = power.get("roll") or {}
        self.assertEqual(roll.get("formula"), "@chr")
        self.assertIn("reason", roll.get("characteristics", []))


class TestTypeDetection(unittest.TestCase):
    """Task 4.6: ancestry Choice selections emit ability-type items when
    the option is an ability, and keep ancestryTrait for true traits."""

    @classmethod
    def setUpClass(cls):
        cls.compendium = load_compendium_items(PACKS)

    def test_choice_ability_option_emits_ability(self):
        """Psionic Gift (Time Raider ancestry Choice selecting Psionic
        Bolt) lands as type 'ability', not 'ancestryTrait'."""
        with open(os.path.join(REPO, "Quistis.ds-hero"),
                  encoding="utf-8") as fh:
            hero = json.load(fh)
        from converter.mapper import convert_character
        doc = convert_character(hero, self.compendium)
        items = {(i.get("system") or {}).get("_dsid"): i
                 for i in doc["items"]}
        self.assertIn("psionic-bolt", items)
        self.assertEqual(items["psionic-bolt"]["type"], "ability")

    def test_trait_options_still_ancestrytrait(self):
        """True traits (e.g. Dwarf trait picks) keep ancestryTrait type."""
        with open(os.path.join(REPO, "Keth.ds-hero"),
                  encoding="utf-8") as fh:
            hero = json.load(fh)
        from converter.mapper import convert_character
        doc = convert_character(hero, self.compendium)
        traits = [i for i in doc["items"] if i.get("type") == "ancestryTrait"]
        self.assertGreater(len(traits), 0)


if __name__ == "__main__":
    unittest.main()
