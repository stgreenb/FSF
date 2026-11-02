"""Grant reconciliation post-pass (change fix-compendium-grant-reconciliation).

Reconciles a converted Foundry actor against the compendium advancement
definitions and the hero's own recorded selections. Runs as the final step
of ``converter.mapper.convert_character``.

Entry point (stable signature — the seam a contributed reconciliation PR
must land on, design D1)::

    reconcile(character: dict, compendium: dict, ctx: SelectionContext) -> dict

Semantics (design D2):
- The pass mutates a private deepcopy; on any exception the ORIGINAL
  unreconciled character is returned (log-and-keep-original — never a
  partially reconciled dict).
- Step order is a fixed invariant: dedupe -> above-level trim -> grant-all
  completion -> choose-N emission -> skill harvest -> summon flags -> final
  dedupe sweep.
"""
from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

_ITEM_JUNK = ("_id", "_key", "folder")

_CHOICE_TYPES = ("Choice", "Domain", "Domain Feature", "Perk",
                 "Tagged Feature Choice", "Ancestry Feature Choice",
                 "Summon Choice")

_HERO_SECTIONS = ("ancestry", "culture", "career", "complication",
                  "subclass", "class")


@dataclass
class SelectionContext:
    """Explicit hero-selection evidence collected from the FORGESTEEL hero
    document (design D2a). Built at a single construction site in
    convert_character; reconcile() reads it and never re-derives picks."""

    hero_level: Optional[int] = None
    #: parent feature name -> selected option names
    choices: Dict[str, List[str]] = field(default_factory=dict)
    #: container (name, type) -> (name, type) pairs it is responsible for
    parentage: Dict[Tuple[str, str], List[Tuple[str, str]]] = field(
        default_factory=dict)
    #: hero document reference (read-only use by the trim step)
    hero_doc: Dict[str, Any] = field(default_factory=dict)

    def record_choice(self, parent_name: str, option_names: List[str]) -> None:
        if not parent_name:
            logger.debug("grant_reconcile: choice feature without a name: %s",
                         option_names)
            return
        bucket = self.choices.setdefault(parent_name, [])
        for name in option_names:
            if name and name not in bucket:
                bucket.append(name)

    def record_parentage(self, container: Tuple[str, str],
                         child: Tuple[str, str]) -> None:
        kids = self.parentage.setdefault(container, [])
        if child not in kids:
            kids.append(child)


def _walk_feature(node: Any, ctx: SelectionContext,
                  parents: Tuple[Tuple[str, str], ...] = ()) -> None:
    """Walk one hero-side feature tree recording choices and container
    parentage."""
    if not isinstance(node, dict):
        return
    name = str(node.get("name", ""))
    ftype = str(node.get("type", ""))
    me = (name, ftype)
    if name:
        for parent in parents:
            ctx.record_parentage(parent, me)
    data = node.get("data") or {}
    children: List[Any] = []
    if ftype == "Ancestry Feature Choice":
        sel = data.get("selected")
        if isinstance(sel, dict):
            ctx.record_choice(name, [str(sel.get("name", ""))])
            children = [sel]
    elif ftype in _CHOICE_TYPES:
        subs = [s for s in (data.get("selected", []) or [])
                if isinstance(s, dict)]
        ctx.record_choice(name, [str(s.get("name", "")) for s in subs])
        children = subs
    elif ftype in ("Multiple Features", "Package"):
        children = [s for s in (data.get("features", []) or [])
                    if isinstance(s, dict)]
    elif ftype == "Kit":
        for kit in data.get("selected", []) or []:
            if isinstance(kit, dict):
                children.extend(s for s in kit.get("features", []) or []
                                if isinstance(s, dict))
    for child in children:
        _walk_feature(child, ctx, parents + (me,))


def build_selection_context(hero_doc: Dict[str, Any],
                            hero_level: Optional[int]) -> SelectionContext:
    """Single construction site (called by convert_character): walk the hero
    document's choice-bearing blocks into a SelectionContext."""
    ctx = SelectionContext(hero_level=hero_level, hero_doc=hero_doc)
    for section in _HERO_SECTIONS:
        block = hero_doc.get(section) or {}
        if isinstance(block, list):
            block = block[0] if block else {}
        for feature in block.get("features", []) or []:
            _walk_feature(feature, ctx)
        for bucket in block.get("featuresByLevel", []) or []:
            for feature in bucket.get("features", []) or []:
                _walk_feature(feature, ctx)
    return ctx


def _name_type(item: Dict[str, Any]) -> Tuple[str, str]:
    return (str(item.get("name", "")), str(item.get("type", "")))


def _strip_junk(item: Dict[str, Any]) -> Dict[str, Any]:
    for junk in _ITEM_JUNK:
        item.pop(junk, None)
    return item


def _dsid_of(item: Dict[str, Any]) -> Optional[str]:
    sysb = item.get("system")
    return sysb.get("_dsid") if isinstance(sysb, dict) else None


def _dedupe(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """First-wins on exact case-sensitive (name, type). Abilities carrying
    distinct ``_dsid`` values are distinct items (canonical ``X - Activate``
    pairs) and both survive."""
    seen: Set[Tuple[str, str]] = set()
    seen_ability: Dict[Tuple[str, str], Set[Optional[str]]] = {}
    out: List[Dict[str, Any]] = []
    for item in items:
        key = _name_type(item)
        if key[1] == "ability":
            dsids = seen_ability.setdefault(key, set())
            dsid = _dsid_of(item)
            if dsid is not None and dsid in dsids:
                continue
            dsids.add(dsid)
            out.append(item)
            continue
        if key in seen:
            logger.info("grant_reconcile: deduped duplicate %r", key)
            continue
        seen.add(key)
        out.append(item)
    return out


def _resolve_pool_item(compendium: Dict[str, Any], uuid: str
                       ) -> Optional[Dict[str, Any]]:
    target = str(uuid).split(".")[-1]
    resolver = getattr(compendium, "resolve_by_uuid", None)
    if resolver is not None:
        found = resolver(target)
        if found is not None:
            return found
    for comp in compendium.values():
        if comp.get("_id") == target or (
                comp.get("flags", {}).get("draw-steel", {})
                .get("sourceId") == uuid):
            return comp
    return None


def _item_advancements(item: Dict[str, Any]) -> Dict[str, Any]:
    sysb = item.get("system")
    adv = sysb.get("advancements") if isinstance(sysb, dict) else None
    return adv if isinstance(adv, dict) else {}


def hero_above_level_names(ctx: SelectionContext) -> Set[str]:
    """Hero-side names granted ONLY in above-level buckets (keep-if-any-grant;
    names with no bucket evidence are never included). Children inherit their
    container's bucket level."""
    hero_level = ctx.hero_level
    above: Set[str] = set()
    at_or_below: Set[str] = set()
    if hero_level is None:
        return above

    def scan(node: Any, bucket_level: int) -> None:
        if not isinstance(node, dict):
            return
        name = str(node.get("name", ""))
        if name:
            if bucket_level > hero_level:
                above.add(name)
            else:
                at_or_below.add(name)
            children: list = []
            data = node.get("data") or {}
            for key in ("features", "selected"):
                subs = data.get(key, [])
                if isinstance(subs, dict):
                    subs = [subs]
                if isinstance(subs, list):
                    children.extend(s for s in subs if isinstance(s, dict))
            for child in children:
                scan(child, bucket_level)

    for section in ("class", "subclass"):
        block = (ctx.hero_doc or {}).get(section) or {}
        for bucket in block.get("featuresByLevel", []) or []:
            lvl = bucket.get("level")
            if not isinstance(lvl, int):
                continue
            for feature in bucket.get("features", []) or []:
                if str(feature.get("name", "")):
                    scan(feature, lvl)
    return above - at_or_below


def _trim_above_level(character: Dict[str, Any],
                      ctx: SelectionContext) -> None:
    """Keep-if-any-grant, never trim blind (design D2 step 2).

    Evidence is the hero's own class/subclass ``featuresByLevel`` buckets:
    a name granted ONLY in above-level buckets is dropped (together with its
    recorded children — container-unit cascade). Names with any grant at or
    below hero level, or without any bucket evidence, are kept."""
    if ctx.hero_level is None:
        logger.info("grant_reconcile: hero level unknown — trim step skipped")
        return
    droppable = hero_above_level_names(ctx)
    if not droppable:
        return
    kept = []
    for item in character.get("items", []):
        if str(item.get("name", "")) in droppable:
            logger.info("grant_reconcile: trimmed above-level item %r",
                        _name_type(item))
            continue
        kept.append(item)
    character["items"] = kept


def _existing_pairs(character: Dict[str, Any]) -> Set[Tuple[str, str]]:
    return {_name_type(i) for i in character.get("items", [])}


def _complete_grant_all(character: Dict[str, Any],
                        compendium: Dict[str, Any],
                        ctx: SelectionContext) -> None:
    """itemGrant pools without chooseN grant every member (issue #3 A).

    Level gate: advancement level, and — because grantor advancements often
    carry no level — the hero-side above-level evidence (a name the hero
    only gains at higher levels is never injected, even when a level-less
    pool references it; e.g. Blessed Domain on a level-1 Conduit)."""
    hero_level = ctx.hero_level
    above = hero_above_level_names(ctx)
    additions: List[Dict[str, Any]] = []
    existing = _existing_pairs(character)
    for item in list(character.get("items", [])) + additions:
        for adv in _item_advancements(item).values():
            if not isinstance(adv, dict) or adv.get("type") != "itemGrant":
                continue
            if adv.get("chooseN"):
                continue  # choose-N pools handled by the next step
            for pool_item in adv.get("pool", []) or []:
                uuid = pool_item.get("uuid") if isinstance(pool_item, dict) else None
                if not uuid:
                    continue
                comp = _resolve_pool_item(compendium, uuid)
                if comp is None:
                    logger.warning(
                        "grant_reconcile: grant-all pool uuid %s "
                        "unresolvable; skipping", uuid)
                    continue
                adv_level = adv.get("level")
                if hero_level is not None and isinstance(adv_level, int) \
                        and adv_level > hero_level:
                    continue
                if str(comp.get("name", "")) in above:
                    logger.debug(
                        "grant_reconcile: pool item %r above hero level; "
                        "not injected", comp.get("name"))
                    continue
                new_item = _strip_junk(copy.deepcopy(comp))
                pair = _name_type(new_item)
                if pair in existing or pair in {
                        _name_type(a) for a in additions}:
                    continue
                additions.append(new_item)
                existing.add(pair)
    if additions:
        character["items"].extend(additions)
        logger.info("grant_reconcile: grant-all completion added %d item(s)",
                    len(additions))


def _emit_choose_n(character: Dict[str, Any],
                   compendium: Dict[str, Any],
                   ctx: SelectionContext) -> None:
    """choose-N pools: the hero's recorded picks must exist as items.

    A pick is matched to a pool entry by NAME (the union of all recorded
    option names across the hero document): the choice's feature name
    (e.g. 'Domain') rarely equals the name of the item carrying the
    advancement (e.g. the class item 'Conduit'), so name-membership in the
    pool — not key equality — is the authoritative criterion."""
    additions: List[Dict[str, Any]] = []
    existing = _existing_pairs(character)
    all_picks: Set[str] = set()
    for names in ctx.choices.values():
        all_picks.update(names)
    for item in character.get("items", []):
        item_name = str(item.get("name", ""))
        for adv in _item_advancements(item).values():
            if not isinstance(adv, dict) or adv.get("type") != "itemGrant":
                continue
            if not adv.get("chooseN"):
                continue
            for pool_item in adv.get("pool", []) or []:
                uuid = pool_item.get("uuid") if isinstance(pool_item, dict) else None
                if not uuid:
                    continue
                comp = _resolve_pool_item(compendium, uuid)
                if comp is None:
                    logger.warning(
                        "grant_reconcile: choose-N pool uuid %s "
                        "unresolvable; skipping", uuid)
                    continue
                comp_name = comp.get("name")
                if comp_name not in all_picks:
                    continue
                new_item = _strip_junk(copy.deepcopy(comp))
                pair = _name_type(new_item)
                if pair in existing or pair in {
                        _name_type(a) for a in additions}:
                    continue
                additions.append(new_item)
                existing.add(pair)
                logger.info("grant_reconcile: choose-N pick %r emitted",
                            comp_name)
    if additions:
        character["items"].extend(additions)


def _harvest_skills(character: Dict[str, Any],
                    ctx: SelectionContext) -> None:
    """Nested Skill Choice selections (issue #3 C): union into
    system.hero.hero.skills preserving order."""
    hero_block = character.get("system")
    skills = ((hero_block or {}).get("hero") or {}).get("hero", {}).get(
        "skills")
    added: List[str] = []
    if not isinstance(skills, list):
        skills = []
    for item in character.get("items", []):
        for adv in _item_advancements(item).values():
            if not isinstance(adv, dict) or adv.get("type") != "skill":
                continue
            for pick in ctx.choices.get(str(item.get("name", "")), []):
                if pick not in skills and pick not in added:
                    added.append(pick)
    if added:
        skills_block = character.setdefault("system", {}).setdefault(
            "hero", {}).setdefault("hero", {})
        existing = skills_block.setdefault("skills", [])
        existing.extend(added)
        logger.info("grant_reconcile: skill harvest added %s", added)


def _write_summon_flags(character: Dict[str, Any],
                        compendium: Dict[str, Any],
                        ctx: SelectionContext) -> None:
    """Summon picks become flags.draw-steel.advancement.<id>.selected with
    compendium Actor UUIDs; a pick that cannot be resolved aborts that
    advancement's flag write entirely (never a partial list)."""
    resolver = getattr(compendium, "resolve_by_name", None)
    if resolver is None:
        logger.info("grant_reconcile: compendium index has no name "
                    "resolver; summon flags skipped")
        return
    for item in character.get("items", []):
        for adv_id, adv in _item_advancements(item).items():
            if not isinstance(adv, dict) or adv.get("type") != "summon":
                continue
            picks = ctx.choices.get(str(item.get("name", "")), [])
            if not picks:
                continue
            uuids: List[str] = []
            complete = True
            for pick in picks:
                found = resolver(pick)
                if found is None or not found[1]:
                    logger.warning(
                        "grant_reconcile: summon pick %r not resolvable "
                        "from the compendium index; advancement %s left "
                        "without flags", pick, adv_id)
                    complete = False
                    break
                uuids.append(found[1])
            if complete and uuids:
                flags = item.setdefault("flags", {}).setdefault(
                    "draw-steel", {}).setdefault("advancement", {})
                flags.setdefault(adv_id, {})["selected"] = uuids
                logger.info("grant_reconcile: summon flags written for %s",
                            item.get("name"))


def reconcile(character: Dict[str, Any], compendium: Dict[str, Any],
              ctx: SelectionContext) -> Dict[str, Any]:
    """Reconcile a converted actor (design D2). Returns the reconciled
    character on success; the ORIGINAL, unmodified character on failure."""
    work = copy.deepcopy(character)
    steps = (
        ("dedupe", lambda: work.__setitem__(
            "items", _dedupe(work.get("items", [])))),
        ("trim", lambda: _trim_above_level(work, ctx)),
        ("grant-all", lambda: _complete_grant_all(work, compendium, ctx)),
        ("choose-N", lambda: _emit_choose_n(work, compendium, ctx)),
        ("skills", lambda: _harvest_skills(work, ctx)),
        ("summons", lambda: _write_summon_flags(work, compendium, ctx)),
        ("final-dedupe", lambda: work.__setitem__(
            "items", _dedupe(work.get("items", [])))),
    )
    for name, step in steps:
        try:
            step()
        except Exception:  # noqa: BLE001 — log-and-keep-original (design D2)
            logger.exception(
                "grant_reconcile: step %s failed; returning unreconciled "
                "character", name)
            return character
    return work
