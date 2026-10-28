"""Foundry export format boundary.

Every literal path/key of the Foundry VTT Draw Steel actor export lives HERE
and nowhere else in the reverse package, so a module version bump is a
one-file change (design D4). Unknown shapes degrade to ``None``/empty values
rather than raising.

The pinned pack version mirrors the checkout pin in ``draw_steel_repo``
"""

import json
import re
from typing import Any, Dict, List, Optional

#: Draw Steel system module version the pinned packs correspond to.
PACK_VERSION = "1.1.0"

# --- item type taxonomy (Foundry document types we understand) ---------------
TYPE_ANCESTRY = "ancestry"
TYPE_ANCESTRY_TRAIT = "ancestryTrait"
TYPE_CULTURE = "culture"
TYPE_CLASS = "class"
TYPE_SUBCLASS = "subclass"
TYPE_CAREER = "career"
TYPE_COMPPLICATION = "complication"
TYPE_FEATURE = "feature"
TYPE_PERK = "perk"
TYPE_KIT = "kit"
TYPE_ABILITY = "ability"
TYPE_TREASURE = "treasure"
TYPE_PROJECT = "project"
TYPE_TITLE = "title"

KNOWN_TYPES = (
    TYPE_ANCESTRY, TYPE_ANCESTRY_TRAIT, TYPE_CULTURE, TYPE_CLASS, TYPE_SUBCLASS,
    TYPE_CAREER, TYPE_COMPPLICATION, TYPE_FEATURE, TYPE_PERK, TYPE_KIT,
    TYPE_ABILITY, TYPE_TREASURE, TYPE_PROJECT, TYPE_TITLE,
)

#: Basic (gratuitous) combat abilities the Foundry system grants to every hero.
#: ForgeSteel's app also adds these implicitly, so they are never written to
#: a .ds-hero and their absence from the export is not a loss.
BASIC_ABILITY_DSIDS = frozenset({
    "advance", "aid-attack", "catch-breath", "charge", "defend", "disengage",
    "escape-grab", "grab", "heal", "knockback", "melee-free-strike",
    "ranged-free-strike", "ride", "stand-up",
})

#: Characteristic keys used by the Foundry actor system block.
CHARACTERISTIC_KEYS = ("might", "agility", "reason", "intuition", "presence")


def is_actor_document(doc: Any) -> bool:
    """True if the parsed JSON has the minimal Foundry actor shape."""
    return isinstance(doc, dict) and isinstance(doc.get("items"), list) \
        and isinstance(doc.get("system"), dict)


def item_name(item: Dict[str, Any]) -> str:
    """Item name or empty string when absent/malformed."""
    name = item.get("name")
    return name if isinstance(name, str) else ""


def item_type(item: Dict[str, Any]) -> str:
    t = item.get("type")
    return t if isinstance(t, str) else ""


def system_of(item: Dict[str, Any]) -> Dict[str, Any]:
    s = item.get("system")
    return s if isinstance(s, dict) else {}


def get_dsid(item: Dict[str, Any]) -> Optional[str]:
    """Native ForgeSteel provenance id shipped in the official packs."""
    dsid = system_of(item).get("_dsid")
    return dsid if isinstance(dsid, str) and dsid else None


def get_pack_dsid(pack_entry: Dict[str, Any]) -> Optional[str]:
    """Provenance id on a raw compendium pack entry (flat, not under system)."""
    dsid = pack_entry.get("_dsid")
    return dsid if isinstance(dsid, str) and dsid else None


def get_level(item: Dict[str, Any]) -> Optional[int]:
    lvl = system_of(item).get("level")
    return lvl if isinstance(lvl, int) else None


def get_advancement_defs(item: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Advancement *definitions* (what may be chosen), keyed by advancement id."""
    advs = system_of(item).get("advancements")
    if not isinstance(advs, dict):
        return {}
    return {k: v for k, v in advs.items() if isinstance(v, dict)}


def _flags(item: Dict[str, Any]) -> Dict[str, Any]:
    flags = item.get("flags")
    if not isinstance(flags, dict):
        return {}
    ds = flags.get("draw-steel")
    return ds if isinstance(ds, dict) else {}


def get_flag_selections(item: Dict[str, Any]) -> Dict[str, List[str]]:
    """Recorded advancement selections: {advancement_id: [selected keys]}.

    Tolerates missing flag namespace, null selections, and non-list payloads.
    """
    raw = _flags(item).get("advancement")
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, List[str]] = {}
    for adv_id, sel in raw.items():
        if not isinstance(sel, dict):
            continue
        selected = sel.get("selected")
        if isinstance(selected, list):
            out[adv_id] = [s for s in selected if isinstance(s, str)]
    return out


def get_advancement_kind(item: Dict[str, Any], adv_id: str) -> str:
    """Definition type for an advancement id ('skill', 'language', ...)."""
    defn = get_advancement_defs(item).get(adv_id, {})
    kind = defn.get("type")
    return kind if isinstance(kind, str) else ""


def get_advancement_requirement_level(item: Dict[str, Any], adv_id: str) -> Optional[int]:
    defn = get_advancement_defs(item).get(adv_id, {})
    req = defn.get("requirements")
    if isinstance(req, dict) and isinstance(req.get("level"), int):
        return req["level"]
    return None


# --- actor-level system block accessors --------------------------------------

def actor_name(doc: Dict[str, Any]) -> str:
    name = doc.get("name")
    return name if isinstance(name, str) else ""


def actor_img(doc: Dict[str, Any]) -> Optional[str]:
    """Actor portrait path (a Foundry asset, not representable in .ds-hero)."""
    img = doc.get("img")
    return img if isinstance(img, str) and img else None


def actor_system(doc: Dict[str, Any]) -> Dict[str, Any]:
    return doc.get("system") if isinstance(doc.get("system"), dict) else {}


def actor_hero(doc: Dict[str, Any]) -> Dict[str, Any]:
    hero = actor_system(doc).get("hero")
    return hero if isinstance(hero, dict) else {}


def actor_hero_int(doc: Dict[str, Any], key: str, default: int = 0) -> int:
    val = actor_hero(doc).get(key)
    return val if isinstance(val, int) else default


def actor_hero_skills(doc: Dict[str, Any]) -> List[str]:
    skills = actor_hero(doc).get("skills")
    if not isinstance(skills, list):
        return []
    return [s for s in skills if isinstance(s, str)]


def actor_characteristics(doc: Dict[str, Any]) -> Dict[str, int]:
    """Final characteristic values keyed by Foundry lowercase name."""
    block = actor_system(doc).get("characteristics")
    out: Dict[str, int] = {}
    if not isinstance(block, dict):
        return out
    for key in CHARACTERISTIC_KEYS:
        entry = block.get(key)
        if isinstance(entry, dict) and isinstance(entry.get("value"), int):
            out[key] = entry["value"]
    return out


def actor_stamina_value(doc: Dict[str, Any]) -> Optional[int]:
    st = actor_system(doc).get("stamina")
    if isinstance(st, dict) and isinstance(st.get("value"), int):
        return st["value"]
    return None


def actor_recoveries_value(doc: Dict[str, Any]) -> Optional[int]:
    rec = actor_system(doc).get("recoveries")
    if isinstance(rec, dict) and isinstance(rec.get("value"), int):
        return rec["value"]
    return None


def career_item_counters(item: Dict[str, Any]) -> Dict[str, int]:
    """projectPoints/renown/wealth carried on the career item system block."""
    sysb = system_of(item)
    out: Dict[str, int] = {}
    for key in ("projectPoints", "renown", "wealth"):
        val = sysb.get(key)
        if isinstance(val, int):
            out[key] = val
    return out


def is_activate_companion_dsid(dsid: Optional[str]) -> bool:
    """True when an ability dsid is a '<feature>-activate' companion."""
    return bool(dsid) and dsid.endswith("-activate")


#: fallback skill -> group map used when config.mjs cannot be parsed
#: (values verified against the Draw Steel 1.1 rules).
DEFAULT_SKILL_GROUPS: Dict[str, str] = {
    "alchemy": "crafting", "architecture": "crafting",
    "blacksmithing": "crafting", "carpentry": "crafting",
    "forgery": "crafting", "jewelry": "crafting", "mechanics": "crafting",
    "tailoring": "crafting",
    "climb": "exploration", "drive": "exploration", "endurance": "exploration",
    "escapeArtist": "exploration", "gymnastics": "exploration", "hide": "exploration",
    "jump": "exploration", "lift": "exploration", "navigate": "exploration",
    "pickLock": "exploration", "ride": "exploration", "search": "exploration",
    "sneak": "exploration", "swim": "exploration", "track": "exploration",
    "empathize": "interpersonal", "flirt": "interpersonal", "intimidate": "interpersonal",
    "lead": "interpersonal", "lie": "interpersonal", "persuade": "interpersonal",
    "readPerson": "interpersonal",
    "brag": "intrigue", "gamble": "intrigue", "interrogate": "intrigue",
    "pickPocket": "intrigue", "rumors": "intrigue", "sabotage": "intrigue",
    "strategy": "intrigue",
    "history": "lore", "magic": "lore", "monsters": "lore", "nature": "lore",
    "psionics": "lore", "religion": "lore", "timescape": "lore",
}

_SKILL_ENTRY_RE = re.compile(
    r"^  (\w+): \{\s*\n    label: \"[^\"]+\",\s*\n    group: \"(\w+)\",",
    re.MULTILINE)


def parse_skill_groups(config_path: str) -> Dict[str, str]:
    """Extract skill -> group mapping from the Draw Steel config.mjs."""
    try:
        with open(config_path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        logger.warning("cannot read %s; using built-in DEFAULT_SKILL_GROUPS "
                       "(verify against module version)", config_path)
        return dict(DEFAULT_SKILL_GROUPS)
    start = text.find("const skillList")
    end = text.find("skillGroups", start) if start >= 0 else -1
    region = text[start:end] if start >= 0 and end > start else text
    found = {k.lower(): v for k, v in _SKILL_ENTRY_RE.findall(region)}
    if not found:
        logger.warning("no skill entries parsed from %s; using built-in "
                       "DEFAULT_SKILL_GROUPS (verify against module version)",
                       config_path)
        return dict(DEFAULT_SKILL_GROUPS)
    return found


