"""Reverse mapper: ingested Foundry actor -> ForgeSteel .ds-hero document.

Recovers build *choices* (design: choices, not derived values). The document
blocks start from deep copies of the raw ForgeSteel pseudo-data (dump via
PayloadProvider) and only selection state is written into them, so every
derived number (stamina, resistances, ...) is recomputed by the app itself.
"""

import copy
import json
import logging
import random
import re
import string
from typing import Any, Dict, List, Optional

from . import foundry_format as ff
from .fs_data_cache import FsData, norm_key
from .ingestion import (ConversionInputError, IngestedActor, IngestedItem,
                        PackIndex, load_actor)
from .loss_report import LossReport
from .payload_provider import PayloadProvider, _canonical

logger = logging.getLogger(__name__)

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

#: vocabulary (FS display names) harvested from the sample corpus for
#: Foundry-key -> FS-name conversion validation.
_VOCAB_CACHE: Dict[tuple, set] = {}


def _corpus_vocab(kind: str, corpus_glob: str = "*.ds-hero") -> set:
    """Skill or Language display names observed in app-exported files."""
    key = (kind, corpus_glob)
    if key in _VOCAB_CACHE:
        return _VOCAB_CACHE[key]
    import glob
    names: set = set()
    for path in glob.glob(corpus_glob):
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            continue
        stack = [doc]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                ftype = node.get("type")
                data = node.get("data")
                if ftype in ("Skill Choice", "Language Choice") and isinstance(data, dict):
                    for value in data.get("selected", []) or []:
                        if isinstance(value, str):
                            names.add(value)
                    for opt in data.get("options", []) or []:
                        if isinstance(opt, str):
                            names.add(opt)
                stack.extend(node.values())
    _VOCAB_CACHE[key] = names
    return names


def foundry_key_to_fs_name(key: str, vocab: set) -> Optional[str]:
    """'readPerson' -> 'Read Person'; 'theFirstLanguage' -> 'The First Language'.

    Returns None when no vocabulary word can be formed (caller reports).
    """
    words = _CAMEL_BOUNDARY.split(key)
    for joiner in (" ", "-"):
        candidate = joiner.join(w[:1].upper() + w[1:] for w in words)
        if candidate in vocab:
            return candidate
    # Fall back to space-joined title case only when it is a known term.
    spaced = " ".join(w[:1].upper() + w[1:] for w in words)
    return spaced if spaced in vocab else None


def _walk_nodes(node: Any):
    """Yield every dict in a nested structure (for id bookkeeping)."""
    stack = [node]
    while stack:
        cur = stack.pop()
        if isinstance(cur, list):
            stack.extend(cur)
        elif isinstance(cur, dict):
            yield cur
            stack.extend(cur.values())


def fresh_hero_id(rng: Optional[random.Random] = None) -> str:
    rng = rng or random
    alphabet = string.ascii_letters + string.digits
    return "".join(rng.choice(alphabet) for _ in range(16))


def _feature_pool(features: List[dict], type_name: str):
    for f in features:
        if isinstance(f, dict) and f.get("type") == type_name:
            yield f


class ReverseMapper:
    def __init__(self, actor: IngestedActor, fs_data: FsData,
                 provider: PayloadProvider, report: LossReport,
                 rng: Optional[random.Random] = None,
                 skill_groups: Optional[Dict[str, str]] = None,
                 picture: Optional[str] = None) -> None:
        self.actor = actor
        self.fs = fs_data
        self.provider = provider
        self.report = report
        self.rng = rng
        self.picture = picture
        self.skill_groups = {k.lower(): v for k, v in
                             (skill_groups or ff.DEFAULT_SKILL_GROUPS).items()}
        self.skills_vocab = _corpus_vocab("skill")
        self.langs_vocab = _corpus_vocab("language")
        self._used_ids: List[str] = []
        self._selected_sub: Optional[dict] = None
        self._class_level: Optional[int] = None
        self._pending_perks: List[tuple] = []
        self._ancestry_ids: set = set()
        self._kit_ids: set = set()

    # ------------------------------------------------------------------ build
    def build(self) -> Dict[str, Any]:
        actor = self.actor
        class_item = actor.first_of_type(ff.TYPE_CLASS)
        if class_item is None:  # ingestion aborts before this point normally
            raise ConversionInputError("no class item in actor export")
        class_obj = self.fs.resolve_kind("class", class_item.dsid, class_item.name)
        if class_obj is None:
            raise ValueError(
                f"class dsid {class_item.dsid!r} not found in pinned ForgeSteel data")
        level = class_item.level or 1
        self._level = level

        ancestry_block = self._build_ancestry()
        culture_block = self._build_culture()
        career_block = self._build_career()
        complication_block = self._build_complication()
        class_block = self._build_class(class_item, level)
        self._distribute_skills(culture_block, career_block, class_block, level)
        self._audit_unmade_choices(class_block, level)

        doc = {
            "id": fresh_hero_id(self.rng),
            "name": ff.actor_name(actor.doc),
            "picture": self.picture,
            "folder": "",
            "settingIDs": self._build_setting_ids(),
            "ancestry": ancestry_block,
            "culture": culture_block,
            "class": class_block,
            "career": career_block,
            "complication": complication_block,
            "features": [self._default_language_feature()],
            "state": self._build_state(),
            "abilityCustomizations": [],
        }
        img = ff.actor_img(actor.doc)
        if img and "mystery-man" not in img and not self.picture:
            self.report.warning(
                "unrepresentable-picture",
                f"actor portrait ({img}) is a Foundry asset path; .ds-hero "
                "carries no picture — pass --picture <file> to embed one")
        return doc

    # -------------------------------------------------------------- origins
    def _resolve_origin(self, itype: str):
        item = self.actor.first_of_type(itype)
        if item is None:
            return None, None
        obj = self.fs.resolve_kind(itype, item.dsid, item.name)
        if obj is None:
            self.report.loss(item.name, itype, item.dsid,
                             reason="payload-unavailable", action="dropped",
                             detail=f"no ForgeSteel data for {itype}")
            return None, None
        self.report.count(itype, converted=1)
        self._used_ids.append(obj["id"])
        block = copy.deepcopy(obj)
        self._reset_baked_selections([block])
        return item, block

    def _build_ancestry(self) -> Optional[Dict[str, Any]]:
        item, block = self._resolve_origin(ff.TYPE_ANCESTRY)
        if block is None:
            return None
        trait_items = self.actor.by_type(ff.TYPE_ANCESTRY_TRAIT)
        top_ids = {f.get("id") for f in block.get("features", [])}
        choices = [f for f in _feature_pool(block.get("features", []), "Choice")
                   if isinstance(f.get("data"), dict)]
        for trait in trait_items:
            resolved = self.fs.resolve_trait(block, trait.dsid, trait.name)
            if resolved is None and trait.dsid:
                # App-synthesized choice options (e.g. the dwarf 'Runic
                # Carving' rune picked from a Text feature's markdown) have
                # ids that never reach the static dump; the sample corpus
                # carries the full payload for ids the forward converter
                # preserved verbatim (design D3 sample fallback).
                candidate = self.provider.get(trait.dsid)[0]
                if (isinstance(candidate, dict) and candidate.get("id")
                        and candidate.get("name")):
                    resolved = candidate
            if resolved is None:
                self.report.loss(trait.name, trait.itype, trait.dsid,
                                 reason="payload-unavailable", action="dropped",
                                 detail="ancestry trait not found in ancestry data")
                continue
            self.report.count(ff.TYPE_ANCESTRY_TRAIT, converted=1)
            trait_copy = copy.deepcopy(resolved)
            # every id inside the trait payload belongs to the ancestry's setting
            for node in _walk_nodes(trait_copy):
                if isinstance(node.get("id"), str):
                    self._ancestry_ids.add(node["id"])
            if resolved.get("id") in top_ids:
                continue  # fixed trait already present in the data copy
            target = None
            for choice in choices:
                option_ids = {o.get("feature", {}).get("id")
                              for o in choice["data"].get("options", [])
                              if isinstance(o, dict)}
                if resolved.get("id") in option_ids:
                    target = choice
                    break
            if target is not None:
                selected = target["data"].setdefault("selected", [])
                if not any(s.get("id") == resolved.get("id") for s in selected
                           if isinstance(s, dict)):
                    selected.append(trait_copy)
            else:
                block["features"].append(trait_copy)
                self.report.loss(trait.name, trait.itype, resolved.get("id"),
                                 reason="defaulted", action="defaulted",
                                 detail="trait attached outside its choice feature")
        return block

    def _build_culture(self) -> Optional[Dict[str, Any]]:
        item, block = self._resolve_origin(ff.TYPE_CULTURE)
        if block is None:
            return None
        if item is None:
            return block
        selections = item.selections()
        # Language selections -> language feature. (Skill slots are filled by
        # _distribute_skills from hero.skills, which preserves the original
        # assignment order; flag selections are union dumps and slot-ambiguous.)
        lang_feature = block.get("language")
        picked: List[str] = []
        for sel in selections:
            if sel.kind == "language":
                for key in sel.selected:
                    name = foundry_key_to_fs_name(key, self.langs_vocab)
                    if name:
                        picked.append(name)
                    else:
                        self.report.loss(key, ff.TYPE_CULTURE, None,
                                         reason="defaulted", action="defaulted",
                                         detail="language key not convertible")
        if isinstance(lang_feature, dict) and picked:
            data = lang_feature.setdefault("data", {})
            count = data.get("count") or 1
            data["selected"] = picked[:count]
            if len(picked) > count:
                self.report.loss("culture language", ff.TYPE_CULTURE, None,
                                 reason="defaulted", action="defaulted",
                                 detail=f"export carried {len(picked)} language "
                                        f"picks; ForgeSteel culture slot holds "
                                        f"{count}")
        return block

    @staticmethod
    def _def_groups(item: IngestedItem, selection) -> List[str]:
        defs = ff.get_advancement_defs(item.raw)
        defn = defs.get(selection.adv_id, {})
        skills = defn.get("skills") or {}
        groups = skills.get("groups") or []
        return [g.lower() for g in groups if isinstance(g, str)]

    def _build_career(self) -> Optional[Dict[str, Any]]:
        item, block = self._resolve_origin(ff.TYPE_CAREER)
        if block is None:
            return None
        features = block.get("features", [])
        if item is not None:
            selections = item.selections()
            lang_sels = [s for s in selections if s.kind == "language"]
            lang_i = 0
            for feature in _feature_pool(features, "Language Choice"):
                data = feature.get("data")
                if not isinstance(data, dict) or lang_i >= len(lang_sels):
                    continue
                count = data.get("count") or 1
                names = [foundry_key_to_fs_name(k, self.langs_vocab)
                         for k in lang_sels[lang_i].selected]
                names = [n for n in names if n]
                if names:
                    data["selected"] = names[:count]
                lang_i += 1
        # Perk items -> career Perk feature.
        perk_items = self.actor.by_type(ff.TYPE_PERK)
        career_perk_features = list(_feature_pool(features, "Perk"))
        for perk_item in perk_items:
            resolved = self.fs.resolve_kind(ff.TYPE_PERK, perk_item.dsid,
                                            perk_item.name)
            if resolved is None:
                self.report.loss(perk_item.name, ff.TYPE_PERK, perk_item.dsid,
                                 reason="payload-unavailable", action="dropped",
                                 detail="perk not in ForgeSteel data")
                continue
            self._used_ids.append(resolved["id"])
            target = None
            for feature in career_perk_features:
                data = feature.get("data")
                if not isinstance(data, dict):
                    continue
                selected = data.get("selected") or []
                if len(selected) >= (data.get("count") or 1):
                    continue
                lists = {l.lower() for l in data.get("lists", []) if isinstance(l, str)}
                if resolved.get("list", "").lower() in lists or not lists:
                    target = feature
                    break
            if target is None:
                self._pending_perks.append((perk_item, resolved))
                continue
            target["data"].setdefault("selected", []).append(copy.deepcopy(resolved))
            self.report.count(ff.TYPE_PERK, converted=1)
        # Inciting incident: not recorded in Foundry exports (design D7).
        incidents = block.get("incitingIncidents")
        if isinstance(incidents, dict) and incidents.get("options") \
                and not incidents.get("selected"):
            incidents["selected"] = copy.deepcopy(incidents["options"][0])
            self.report.loss(block.get("name", "career"), ff.TYPE_CAREER,
                             block.get("id"), reason="defaulted", action="defaulted",
                             detail="inciting incident not recorded by Foundry; "
                                    "first option preselected — player should "
                                    "re-choose in ForgeSteel")
        return block

    def _build_complication(self) -> Optional[Dict[str, Any]]:
        _item, block = self._resolve_origin(ff.TYPE_COMPPLICATION)
        return block

    # ------------------------------------------------------------------ class
    def _build_class(self, class_item: IngestedItem, level: int) -> Dict[str, Any]:
        resolved = self.fs.resolve_kind("class", class_item.dsid,
                                        class_item.name)
        if resolved is None:
            self.report.loss(class_item.name, ff.TYPE_CLASS, class_item.dsid,
                             reason="payload-unavailable", action="dropped",
                             detail="no ForgeSteel class data; conversion aborted")
            raise ConversionInputError(
                f"cannot resolve class '{class_item.name}' "
                f"({class_item.dsid}) in ForgeSteel data")
        block = copy.deepcopy(resolved)
        self._reset_baked_selections([block])
        block["level"] = level
        # characteristics: final actor values (static class data ships none;
        # the app derives them, so build the list from the export).
        actor_chars = ff.actor_characteristics(self.actor.doc)
        if not actor_chars:
            self.report.warning("state-reset", "actor carries no characteristic "
                                "values; class-data defaults retained")
        entries = block.get("characteristics") or []
        if entries:
            for entry in entries:
                key = str(entry.get("characteristic", "")).casefold()
                if key in actor_chars:
                    entry["value"] = actor_chars[key]
        else:
            order = ("Might", "Agility", "Reason", "Intuition", "Presence")
            block["characteristics"] = [
                {"characteristic": name, "value": actor_chars[name.casefold()]}
                for name in order if name.casefold() in actor_chars]
        # subclass selection
        subclass_item = self.actor.first_of_type(ff.TYPE_SUBCLASS)
        selected_sub = None
        if subclass_item is not None:
            selected_sub = self.fs.resolve_subclass(block, subclass_item.dsid,
                                                    subclass_item.name)
            if selected_sub is None:
                self.report.loss(subclass_item.name, ff.TYPE_SUBCLASS,
                                 subclass_item.dsid, reason="payload-unavailable",
                                 action="dropped",
                                 detail="subclass unresolved; left unselected")
        for sub in block.get("subclasses", []):
            sub["selected"] = bool(selected_sub and sub.get("id") == selected_sub.get("id"))
        self._selected_sub = selected_sub
        self._class_level = level

        self._attribute_items(block, level, selected_sub)
        # class-level perks that were deferred by career processing (class perks)
        for perk_item, resolved in self._pending_perks:
            target = self._find_perk_slot(block, level, resolved)
            if target is not None:
                target["data"].setdefault("selected", []).append(
                    copy.deepcopy(resolved))
                self.report.count(ff.TYPE_PERK, converted=1)
            else:
                self.report.loss(perk_item.name, ff.TYPE_PERK, resolved.get("id"),
                                 reason="defaulted", action="defaulted",
                                 detail="no free perk slot at or below level")
        self._pending_perks = []
        self._used_ids.append(block["id"])
        for node in _walk_nodes(block):
            if isinstance(node.get("id"), str):
                self._used_ids.append(node["id"])
        return block

    def _audit_unmade_choices(self, block: Dict[str, Any], level: int) -> None:
        """Report choice slots at/below level that no export evidence filled.

        A gap either means the export never recorded the pick (forward or
        module limitation, e.g. the Elementalist Enchantment) or the player
        genuinely has not made it. Either way ForgeSteel must re-present it.
        """
        scopes: List[tuple] = []
        for entry in block.get("featuresByLevel", []):
            if entry.get("level", 99) <= level:
                scopes.append((entry.get("level"), entry.get("features", [])))
        if self._selected_sub:
            for entry in self._selected_sub.get("featuresByLevel", []):
                if entry.get("level", 99) <= level:
                    scopes.append((entry.get("level"), entry.get("features", [])))
        for _lvl, features in scopes:
            for feature in features:
                ftype = feature.get("type")
                if ftype not in ("Choice", "Perk", "Class Ability", "Kit",
                                 "Skill Choice"):
                    continue
                data = feature.get("data")
                if not isinstance(data, dict):
                    continue
                key = "selectedIDs" if ftype == "Class Ability" else "selected"
                if data.get(key):
                    continue
                if ftype in ("Perk", "Skill Choice") and \
                        not self._has_slot_options(feature):
                    continue
                self.report.loss(feature.get("name", feature.get("id")),
                                 "feature", feature.get("id"),
                                 reason="defaulted", action="defaulted",
                                 detail=f"{ftype} at level {_lvl} had no choice "
                                        "evidence in the export; re-select in "
                                        "ForgeSteel")

    @staticmethod
    def _has_slot_options(feature: dict) -> bool:
        data = feature.get("data") or {}
        return bool(data.get("options") or data.get("lists")
                    or data.get("listOptions"))

    def _fill_choice_slot(self, block: Dict[str, Any], level: int,
                          resolved: dict) -> bool:
        """Attach an option payload to the free Choice feature offering it.

        Handles Foundry itemGrant choices whose picked option is itself an
        item (e.g. 'Ward of Delightful Consequences' for the level-1 ward
        choice). Returns True when a slot accepted the option.
        """
        rid = resolved.get("id")
        if rid is None:
            return False
        scopes: List[List[dict]] = [
            [f for e in block.get("featuresByLevel", [])
             if e.get("level", 99) <= level for f in e.get("features", [])],
        ]
        if self._selected_sub:
            scopes.append([f for e in self._selected_sub.get("featuresByLevel", [])
                           if e.get("level", 99) <= level
                           for f in e.get("features", [])])
        for scope in scopes:
            for feature in scope:
                if feature.get("type") != "Choice":
                    continue
                data = feature.get("data")
                if not isinstance(data, dict):
                    continue
                if data.get("selected"):
                    continue
                option_ids = {o.get("feature", {}).get("id")
                              for o in data.get("options", [])
                              if isinstance(o, dict)}
                if rid in option_ids:
                    data["selected"] = [copy.deepcopy(resolved)]
                    return True
        return False

    def _attribute_items(self, block: Dict[str, Any], level: int,
                         selected_sub: Optional[dict]) -> None:
        """Route every non-origin export item into the class structure."""
        class_fbl_ids = set()      # top-level fbl feature ids (canonical items)
        class_fbl_deep = set()     # every id inside those payloads (choices, embedded abilities)
        for entry in block.get("featuresByLevel", []):
            for feature in entry.get("features", []):
                if isinstance(feature.get("id"), str):
                    class_fbl_ids.add(feature["id"])
                for node in _walk_nodes(feature):
                    if isinstance(node.get("id"), str):
                        class_fbl_deep.add(node["id"])
        sub_fbl_ids: set = set()
        sub_fbl_deep: set = set()
        if selected_sub:
            for entry in selected_sub.get("featuresByLevel", []):
                for feature in entry.get("features", []):
                    if isinstance(feature.get("id"), str):
                        sub_fbl_ids.add(feature["id"])
                    for node in _walk_nodes(feature):
                        if isinstance(node.get("id"), str):
                            sub_fbl_deep.add(node["id"])
        for kit_item in self.actor.by_type(ff.TYPE_KIT):
            kit_obj = self.fs.resolve_kind(ff.TYPE_KIT, kit_item.dsid,
                                           kit_item.name)
            if kit_obj is not None:
                for node in _walk_nodes(kit_obj):
                    if isinstance(node.get("id"), str):
                        self._kit_ids.add(node["id"])
        origin_types = {ff.TYPE_ANCESTRY, ff.TYPE_ANCESTRY_TRAIT, ff.TYPE_CULTURE,
                        ff.TYPE_CLASS, ff.TYPE_SUBCLASS, ff.TYPE_CAREER,
                        ff.TYPE_COMPPLICATION}
        items = self.actor.items
        dsids_present = {i.dsid for i in items}
        ability_candidates: List[dict] = []

        for item in items:
            if item.itype in origin_types:
                continue
            if item.itype in (ff.TYPE_TREASURE, ff.TYPE_PROJECT):
                self.report.loss(item.name, item.itype, item.dsid,
                                 reason="unsupported-construct",
                                 action="dropped",
                                 detail="loot/projects not represented "
                                        "in .ds-hero")
                continue
            # paired canonical activate abilities fold into their feature
            if item.itype == ff.TYPE_ABILITY and item.dsid \
                    and item.dsid.endswith("-activate"):
                parent = item.dsid[: -len("-activate")]
                if parent in dsids_present:
                    self.report.count(ff.TYPE_ABILITY, converted=1)
                    continue
            if item.itype == ff.TYPE_ABILITY and item.dsid in ff.BASIC_ABILITY_DSIDS:
                continue
            if item.itype == ff.TYPE_KIT:
                self._attach_kit(block, level, selected_sub, item)
                continue
            if item.itype == ff.TYPE_PERK:
                continue  # handled in career/perk pipeline
            if item.itype == ff.TYPE_TITLE:
                continue  # handled in _collect_titles
            prefer = "ability" if item.itype == ff.TYPE_ABILITY else "feature"
            resolved = self.fs.resolve_feature(item.dsid, item.name, block,
                                               prefer=prefer)
            if resolved is None:
                self.report.loss(item.name, item.itype, item.dsid,
                                 reason="payload-unavailable", action="dropped",
                                 detail="no ForgeSteel feature/ability data")
                continue
            rid = resolved.get("id")
            if item.itype == ff.TYPE_ABILITY:
                if isinstance(rid, str) and rid.startswith("title-"):
                    self.report.count(ff.TYPE_ABILITY, converted=1)
                    continue  # rides along inside state.titles
                if rid in self._used_ids:
                    # companion ability of content already placed elsewhere
                    # (e.g. a perk's embedded ability shipped as its own item)
                    self.report.count(ff.TYPE_ABILITY, converted=1)
                    continue
                if rid in self._ancestry_ids or rid in self._kit_ids:
                    self.report.count(ff.TYPE_ABILITY, converted=1)
                    continue
                if rid in class_fbl_deep or rid in sub_fbl_deep:
                    # canonical class/subclass ability: already in the copy
                    self.report.count(ff.TYPE_ABILITY, converted=1)
                    continue
                if rid not in self._used_ids:
                    self._used_ids.append(rid)
                ability_candidates.append(resolved)
            else:
                for node in _walk_nodes(resolved):
                    if isinstance(node.get("id"), str):
                        self._used_ids.append(node["id"])
                # title-granted features ride along inside state.titles
                if isinstance(rid, str) and rid.startswith("title-"):
                    self.report.count(item.itype, converted=1)
                    continue
                # feature items: canonical features already exist in the copy
                if rid in class_fbl_ids or rid in sub_fbl_ids:
                    self.report.count(ff.TYPE_FEATURE, converted=1)
                elif self._fill_choice_slot(block, level, resolved):
                    self.report.count(ff.TYPE_FEATURE, converted=1)
                else:
                    self.report.count(ff.TYPE_FEATURE, dropped=1)
                    self.report.loss(item.name, item.itype, rid,
                                     reason="defaulted", action="dropped",
                                     detail="feature resolved but not attributable "
                                            "to a class level; re-add in app")
        # picked abilities -> Class Ability slots by cost
        self._fill_class_ability_slots(block, level, ability_candidates)

    def _attach_kit(self, block: Dict[str, Any], level: int,
                    selected_sub: Optional[dict], item: IngestedItem) -> None:
        kit_obj = self.fs.resolve_kind(ff.TYPE_KIT, item.dsid, item.name)
        if kit_obj is None:
            self.report.loss(item.name, ff.TYPE_KIT, item.dsid,
                             reason="payload-unavailable", action="dropped",
                             detail="kit not in ForgeSteel data")
            return
        self._used_ids.append(kit_obj["id"])
        grants = self.fs.kit_grants.get(kit_obj["id"], [])
        class_id = block.get("id")
        sub_id = (selected_sub or {}).get("id")
        candidates = [g for g in grants
                      if g.get("containerId") == class_id
                      and (g.get("subclassId") in (None, sub_id))
                      and (g.get("level") is None or g.get("level") <= level)]
        target_feature = None
        for grant in candidates:
            feature = self._find_feature(block, grant["featureId"], grant.get("subclassId"))
            if feature is not None and isinstance(feature.get("data"), dict):
                target_feature = feature
                break
        if target_feature is None:
            self.report.loss(item.name, ff.TYPE_KIT, kit_obj["id"],
                             reason="defaulted", action="defaulted",
                             detail="kit grant feature not found; re-select kit in app")
            return
        selected = target_feature["data"].setdefault("selected", [])
        if not any(k.get("id") == kit_obj["id"] for k in selected if isinstance(k, dict)):
            selected.append(copy.deepcopy(kit_obj))
        for node in _walk_nodes(kit_obj):
            if isinstance(node.get("id"), str):
                self._used_ids.append(node["id"])
        self.report.count(ff.TYPE_KIT, converted=1)

    def _find_feature(self, block: Dict[str, Any], feature_id: str,
                      subclass_id: Optional[str]) -> Optional[dict]:
        scope: List[dict] = []
        if subclass_id:
            for sub in block.get("subclasses", []):
                if sub.get("id") == subclass_id:
                    for entry in sub.get("featuresByLevel", []):
                        scope.extend(entry.get("features", []))
        else:
            for entry in block.get("featuresByLevel", []):
                scope.extend(entry.get("features", []))
        for feature in scope:
            if feature.get("id") == feature_id:
                return feature
        return None

    def _fill_class_ability_slots(self, block: Dict[str, Any], level: int,
                                  abilities: List[dict]) -> None:
        slots: List[dict] = []
        scopes: List[List[dict]] = [
            [f for e in block.get("featuresByLevel", []) if e.get("level", 99) <= level
             for f in e.get("features", [])],
        ]
        if self._selected_sub:
            scopes.append([f for e in self._selected_sub.get("featuresByLevel", [])
                           if e.get("level", 99) <= level for f in e.get("features", [])])
        for scope in scopes:
            for feature in scope:
                if feature.get("type") == "Class Ability" \
                        and isinstance(feature.get("data"), dict):
                    feature["data"].setdefault("selectedIDs", [])
                    slots.append(feature)
        for ability in abilities:
            cost = ability.get("cost")
            match = None
            for slot in slots:
                data = slot["data"]
                if data.get("cost") != cost:
                    continue
                if len(data.get("selectedIDs", [])) >= (data.get("count") or 1):
                    continue
                match = slot
                break
            if match is None:
                self.report.loss(ability.get("name", ability.get("id")),
                                 ff.TYPE_ABILITY, ability.get("id"),
                                 reason="defaulted", action="defaulted",
                                 detail="no free Class Ability slot for cost "
                                        f"{cost!r}; re-select in app")
                continue
            match["data"]["selectedIDs"].append(ability["id"])
            self.report.count(ff.TYPE_ABILITY, converted=1)

    def _find_perk_slot(self, block: Dict[str, Any], level: int,
                        perk_obj: dict) -> Optional[dict]:
        lists = {perk_obj.get("list", "").lower()}
        scopes: List[List[dict]] = [
            [f for e in block.get("featuresByLevel", []) if e.get("level", 99) <= level
             for f in e.get("features", [])],
        ]
        if self._selected_sub:
            scopes.append([f for e in self._selected_sub.get("featuresByLevel", [])
                           if e.get("level", 99) <= level for f in e.get("features", [])])
        for scope in scopes:
            for feature in scope:
                if feature.get("type") != "Perk" or not isinstance(feature.get("data"), dict):
                    continue
                data = feature["data"]
                selected = data.get("selected") or []
                if len(selected) >= (data.get("count") or 1):
                    continue
                allowed = {l.lower() for l in data.get("lists", []) if isinstance(l, str)}
                if not allowed or allowed & lists:
                    return feature
        return None

    # ------------------------------------------------------ state & settings
    def _build_state(self) -> Dict[str, Any]:
        doc = self.actor.doc
        # hero block is the authoritative currency/xp source; career item
        # counters are career rank bookkeeping, not player wealth.
        xp = ff.actor_hero_int(doc, "xp")
        surges = ff.actor_hero_int(doc, "surges")
        victories = ff.actor_hero_int(doc, "victories")
        renown = ff.actor_hero_int(doc, "renown")
        wealth = ff.actor_hero_int(doc, "wealth")
        project_points = ff.actor_hero_int(doc, "projectPoints")
        # transient state: rested defaults (design D5); warn when the export
        # actually carried non-default transient values.
        stamina_temp = 0
        stamina_block = ff.actor_system(doc).get("stamina")
        if isinstance(stamina_block, dict) and isinstance(stamina_block.get("temporary"), int):
            stamina_temp = stamina_block.get("temporary") or 0
        statuses = ff.actor_system(doc).get("statuses")
        active_statuses = False
        if isinstance(statuses, dict):
            active_statuses = any(statuses.get(k) for k in statuses)
        elif isinstance(statuses, list):
            active_statuses = bool(statuses)
        if stamina_temp or active_statuses:
            self.report.warning(
                "state-reset",
                "transient combat state (stamina temp/statuses) found in export; "
                "reset to rested defaults per design D5")
        state = {
            "staminaDamage": 0,
            "staminaTemp": 0,
            "recoveriesUsed": 0,
            "surges": surges,
            "victories": victories,
            "xp": xp,
            "heroTokens": ff.actor_hero_int(doc, "heroTokens"),
            "renown": renown,
            "wealth": wealth,
            "projectPoints": project_points,
            "conditions": [],
            "inventory": [],
            "projects": [],
            "controlledSlots": [],
            "notes": "",
            "encounterState": "ready",
            "hidden": False,
            "defeated": False,
            "titles": self._collect_titles(),
        }
        return state

    def _collect_titles(self) -> List[Dict[str, Any]]:
        """Recover state.titles from title items (forward emits the pack
        'title' item per earned title; the dump carries the full title
        object in hero-file shape)."""
        titles: List[Dict[str, Any]] = []
        for item in self.actor.by_type(ff.TYPE_TITLE):
            resolved = self.fs.resolve_kind(ff.TYPE_TITLE, item.dsid, item.name)
            if resolved is None:
                self.report.loss(item.name, ff.TYPE_TITLE, item.dsid,
                                 reason="payload-unavailable", action="dropped",
                                 detail="title not in ForgeSteel data")
                continue
            titles.append(copy.deepcopy(resolved))
            self.report.count(ff.TYPE_TITLE, converted=1)
        return titles

    _CHOICE_TYPES = ("Skill Choice", "Choice", "Perk", "Class Ability", "Kit",
                     "Ancestry Feature Choice", "Item Choice")

    def _reset_baked_selections(self, blocks: List[Optional[Dict[str, Any]]]) -> None:
        """Clear choice state baked into the static pseudo-data.

        Raw FS data ships illustrative ``selected`` values (e.g. elementalist
        '5pt Ability' presets, career Skill (Magic)). Those are inputs to the
        app's choice UI, not evidence for this actor — every genuine choice
        has an export-side source and is re-applied by the mapper. Language
        choices are rules (culture's language IS the pick) and are preserved.
        """
        for block in blocks:
            if not isinstance(block, dict):
                continue
            for node in _walk_nodes(block):
                if node.get("type") in self._CHOICE_TYPES:
                    data = node.get("data")
                    if isinstance(data, dict):
                        if "selected" in data:
                            data["selected"] = []
                        if "selectedIDs" in data:
                            data["selectedIDs"] = []

    def _distribute_skills(self, culture_block: Optional[Dict[str, Any]],
                           career_block: Optional[Dict[str, Any]],
                           class_block: Dict[str, Any], level: int) -> None:
        """Fill Skill Choice slots from actor hero.skills in order.

        The forward converter (and native module ordering) lists the actor's
        granted skills in the order they were chosen: culture env/org/up,
        career features in order, then class/subclass features by level.
        Each slot consumes the next unconsumed skills whose group appears in
        its listOptions until its count is met.
        """
        keys = ff.actor_hero_skills(self.actor.doc)
        entries = [(k, foundry_key_to_fs_name(k, self.skills_vocab)) for k in keys]
        slots: List[tuple] = []
        if isinstance(culture_block, dict):
            for slot_key in ("environment", "organization", "upbringing"):
                feature = culture_block.get(slot_key)
                if isinstance(feature, dict) and isinstance(feature.get("data"), dict):
                    slots.append(self._skill_slot(feature))
        if isinstance(career_block, dict):
            for feature in _feature_pool(career_block.get("features", []),
                                         "Skill Choice"):
                slot = self._skill_slot(feature)
                if slot is not None:
                    slots.append(slot)
        scopes: List[List[dict]] = [
            [f for e in class_block.get("featuresByLevel", [])
             if e.get("level", 99) <= level for f in e.get("features", [])],
        ]
        if self._selected_sub:
            scopes.append([f for e in self._selected_sub.get("featuresByLevel", [])
                           if e.get("level", 99) <= level
                           for f in e.get("features", [])])
        for scope in scopes:
            for feature in scope:
                if feature.get("type") == "Skill Choice":
                    slot = self._skill_slot(feature)
                    if slot is not None:
                        slots.append(slot)
        slots = [s for s in slots if s is not None and not s[1].get("selected")]

        filled = self._match_flag_selections(slots)
        self._assign_unambiguous_flag_picks(slots)
        remaining = [s for s in slots if not s[1].get("selected")]

        consumed: set = set()
        for groups, data, count, _options in remaining:
            picked: List[str] = []
            for idx, (key, name) in enumerate(entries):
                if len(picked) >= count:
                    break
                if idx in consumed or name is None:
                    continue
                group = self.skill_groups.get(key.lower(), "")
                if groups and group and group not in groups:
                    continue
                picked.append(name)
                consumed.add(idx)
            if picked:
                data["selected"] = picked
        if filled and remaining:
            logger.debug("skill slots: %d from flags, %d from hero.skills order",
                         filled, sum(1 for s in remaining if s[1].get("selected")))

    def _match_flag_selections(self, slots: List[tuple]) -> int:
        """Fill slots from advancement flags when a def matches one slot.

        Native Foundry actors record per-definition selections precisely. A
        def matches a slot when its level requirement is met and either:
        (a) its group set equals the slot listOptions with chooseN == count, or
        (b) it has explicit skill choices covering the picks and the slot's
            option list is empty (group-governed slot) or intersects them,
            with chooseN == count.
        Ambiguous matches (2+ slots) are left to the hero.skills distributor.
        Returns the number of slots filled.
        """
        candidates: List[tuple] = []
        for itype in (ff.TYPE_CULTURE, ff.TYPE_CAREER, ff.TYPE_CLASS,
                      ff.TYPE_SUBCLASS):
            for item in self.actor.by_type(itype):
                defs = ff.get_advancement_defs(item.raw)
                for sel in item.selections():
                    if sel.kind != "skill" or not sel.selected:
                        continue
                    defn = defs.get(sel.adv_id, {})
                    skills = defn.get("skills") or {}
                    groups = frozenset(g.lower()
                                       for g in (skills.get("groups") or [])
                                       if isinstance(g, str))
                    choices = frozenset(c.lower()
                                        for c in (skills.get("choices") or [])
                                        if isinstance(c, str))
                    candidates.append((sel, groups, choices))
        filled = 0
        for sel, groups, choices in candidates:
            if sel.level is not None and (self._class_level or 0) < sel.level:
                continue
            picks_lower = {s.lower() for s in sel.selected}
            fits: List[tuple] = []
            for slot in slots:
                slot_groups, data, count, slot_options = slot
                if data.get("selected"):
                    continue
                if sel.choose_n is not None and sel.choose_n != count:
                    continue
                if len(sel.selected) > count:
                    continue
                if choices:
                    if not picks_lower <= choices:
                        continue
                    if slot_options and not (slot_options & choices
                                             or picks_lower <= slot_options):
                        continue
                    if not slot_options and groups:
                        # group-governed slot: require group fit for picks
                        if not all(self.skill_groups.get(s, "") in groups
                                   for s in picks_lower):
                            continue
                    fits.append(slot)
                else:
                    if groups != slot_groups:
                        continue
                    if slot_options and not picks_lower <= slot_options:
                        continue
                    fits.append(slot)
            if len(fits) == 1:
                _g, data, count, _opts = fits[0]
                names = [foundry_key_to_fs_name(k, self.skills_vocab)
                         for k in sel.selected[:count]]
                names = [n for n in names if n]
                if names:
                    data["selected"] = names
                    filled += 1
        return filled

    def _assign_unambiguous_flag_picks(self, slots: List[tuple]) -> None:
        """Last resort: a single unconsumed flag pick, a single empty slot.

        When every remaining slot wants exactly one skill and the union of
        remaining flag selections holds exactly that many convertible skills,
        assign in slot order (order is deterministic though not guaranteed).
        """
        empty = [s for s in slots if not s[1].get("selected")]
        if not empty or any(s[2] != 1 for s in empty):
            return
        picks: List[str] = []
        seen: set = set()
        for itype in (ff.TYPE_CULTURE, ff.TYPE_CAREER, ff.TYPE_CLASS,
                      ff.TYPE_SUBCLASS):
            for item in self.actor.by_type(itype):
                for sel in item.selections():
                    if sel.kind != "skill" or sel.level is not None and \
                            (self._class_level or 0) < sel.level:
                        continue
                    for key in sel.selected:
                        name = foundry_key_to_fs_name(key, self.skills_vocab)
                        if name and name not in seen:
                            seen.add(name)
                            picks.append(name)
        already_used = {n for s in slots if s[1].get("selected")
                        for n in s[1]["selected"]}
        picks = [p for p in picks if p not in already_used]
        if len(picks) != len(empty):
            return
        for (groups, data, count, options), name in zip(
                sorted(empty, key=lambda s: len(s[0])), picks):
            data["selected"] = [name]

    @staticmethod
    def _skill_slot(feature: dict) -> Optional[tuple]:
        data = feature.get("data")
        if not isinstance(data, dict):
            return None
        groups = frozenset(g.lower() for g in data.get("listOptions", [])
                           if isinstance(g, str))
        options = frozenset(str(o).casefold() for o in data.get("options", [])
                            if isinstance(o, str))
        count = data.get("count") or 1
        return (groups, data, count, options)

    def _default_language_feature(self) -> Dict[str, Any]:
        # ForgeSteel grants the campaign default language implicitly; every
        # corpus sample carries exactly this feature.
        return {
            "id": "default-language",
            "name": "Default Language",
            "description": "",
            "type": "Language Choice",
            "data": {"options": [], "count": 1, "selected": ["Caelian"]},
        }

    def _build_setting_ids(self) -> List[str]:
        if self.fs is None:
            return ["core"]
        # Only top-level dump entries have setting membership; nested ids
        # (features/abilities inside a class tree) inherit their container's.
        top_level = set()
        for entries in self.fs.data.values():
            top_level.update(entries.keys())
        used_top = [i for i in dict.fromkeys(self._used_ids) if i in top_level]
        settings, uncertain = self.fs.settings_for(used_top)
        for oid in uncertain:
            self.report.warning("setting-uncertain",
                                f"{oid}: setting membership unknown; 'core' assumed")
        return settings
