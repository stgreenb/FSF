"""Versioned fs_data cache + ForgeSteel data index (tasks 1.2, 1.5).

The dump produced by ``tools/fs-data-dump`` is copied into
``~/.cache/forgesteel-converter/fs_data/<forgesteel-git-sha>/`` mirroring the
existing compendium cache pattern (design D2). This module also owns the
id/name resolution used by the reverse mapper: Foundry ``_dsid`` conventions
and ForgeSteel raw ids do not always agree (e.g. Foundry ``traveling-artisan``
vs ForgeSteel ``perk-travelling-artisan``), so every lookup goes through
:meth:`FsData.resolve` which tries id variants, scoped name matches, and a
curated alias table — and reports nothing (the mapper files the loss).
"""

import glob
import json
import logging
import os
import shutil
import subprocess
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

CACHE_ROOT = os.path.join(os.path.expanduser("~"), ".cache",
                          "forgesteel-converter", "fs_data")

DUMP_KINDS = ("ancestries", "classes", "subclasses", "careers", "cultures",
              "complications", "perks", "kits", "items", "titles", "domains")

#: Deterministic id transforms from Foundry ``_dsid`` conventions to raw
#: ForgeSteel ids (verified empirically against the pinned packs).
TYPE_PREFIXES = {
    "ancestry": "ancestry-",
    "culture": "culture-",
    "class": "class-",
    "career": "career-",
    "complication": "comp-",
    "perk": "perk-",
    "kit": "kit-",
    "title": "title-",
}

#: Cultures carry the name stem + '-culture' in Foundry packs
#: ('memonek-culture' -> 'culture-memonek').
CULTURE_DSID_SUFFIX = "-culture"

#: Curated crosswalks for discovered id drift between the Foundry packs and
#: the ForgeSteel raw data (name spellings differ; id slugs differ).
#: Keys: "{foundry_type}\x00{foundry_dsid or name-key}". See tests.
ID_ALIASES: Dict[str, str] = {
    "perk\x00traveling-artisan": "perk-travelling-artisan",
    "perk\x00traveling-sage": "perk-travelling-sage",
    # Pack-native ids whose ForgeSteel data uses a different id/name
    # (forward known_mappings emit the pack item; reverse maps it back).
    "feature\x00mighty-leap": "fury-1-4",
    "feature\x00headbutt": "title-brawler-3",
}


def norm_key(name: str) -> str:
    """Normalized match key: casefold, collapse whitespace, unify quotes."""
    s = (name or "")
    for src, dst in (("\u2019", "'"), ("\u2018", "'"),
                     ("\u201c", '"'), ("\u201d", '"')):
        s = s.replace(src, dst)
    return " ".join(s.casefold().split())


def current_repo_sha(repo_path: str) -> Optional[str]:
    """Short git SHA of a checkout, or None when unavailable."""
    try:
        out = subprocess.run(
            ["git", "-C", repo_path, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10, check=True,
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def cache_path_for(sha: str, cache_root: Optional[str] = None) -> str:
    return os.path.join(cache_root or CACHE_ROOT, sha)


def install_dump(source_dir: str, sha: str,
                 cache_root: Optional[str] = None) -> str:
    """Copy a fresh dump into the SHA-keyed cache; returns the cache dir."""
    dest = cache_path_for(sha, cache_root)
    os.makedirs(dest, exist_ok=True)
    for name in os.listdir(source_dir):
        if name.endswith(".json"):
            shutil.copy2(os.path.join(source_dir, name), os.path.join(dest, name))
    marker = {"sha": sha, "source": os.path.abspath(source_dir)}
    with open(os.path.join(dest, "marker.json"), "w", encoding="utf-8") as fh:
        json.dump(marker, fh, indent=2)
    # copy2 preserves source mtimes; touch the dir so find_cache recency works.
    os.utime(dest, None)
    logger.info("Installed fs_data dump %s -> %s", sha, dest)
    return dest


def find_cache(sha: Optional[str] = None,
               cache_root: Optional[str] = None) -> Optional[str]:
    """Most recently modified cache dir (optionally for a specific sha)."""
    if sha and os.path.isdir(cache_path_for(sha, cache_root)):
        return cache_path_for(sha, cache_root)
    root = cache_root or CACHE_ROOT
    if not os.path.isdir(root):
        return None
    candidates = [os.path.join(root, d) for d in os.listdir(root)
                  if os.path.isdir(os.path.join(root, d))]
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def check_freshness(repo_path: str, cached_sha: str) -> bool:
    """True when the cached dump matches the checkout's current HEAD (task 1.5)."""
    head = current_repo_sha(repo_path)
    if head is None:
        return False
    return head == cached_sha


def _looks_like_payload(node: Any) -> bool:
    return (isinstance(node, dict) and isinstance(node.get("id"), str)
            and isinstance(node.get("name"), str))


def _walk_payloads(node: Any):
    """Yield every payload-shaped object (features, abilities, perks, kits...)."""
    stack = [node]
    while stack:
        cur = stack.pop()
        if isinstance(cur, list):
            stack.extend(reversed(cur))
        elif isinstance(cur, dict):
            if _looks_like_payload(cur):
                yield cur
            stack.extend(cur.values())


class _Index:
    """id and name indices over one scope (a dump kind dict or a class tree)."""

    def __init__(self) -> None:
        self.by_id: Dict[str, Any] = {}
        self.by_name: Dict[str, List[Any]] = {}

    def add(self, obj: Any) -> None:
        oid = obj.get("id")
        if isinstance(oid, str):
            existing = self.by_id.get(oid)
            # Prefer feature-shaped objects (str type) over raw ability objects
            # (dict type) that share the same id.
            if (existing is None or (not isinstance(existing.get("type"), str)
                                    and isinstance(obj.get("type"), str))):
                self.by_id[oid] = obj
        name = obj.get("name")
        if isinstance(name, str):
            key = norm_key(name)
            self.by_name.setdefault(key, []).append(obj)
            # Singular/plural drift between ForgeSteel data and Foundry
            # packs (e.g. 'Mighty Leaps' vs 'Mighty Leap'): register the
            # opposite-form key so a name lookup finds it. name_one still
            # requires a unique id, so genuinely distinct pairs stay
            # ambiguous and fall through to the loss report.
            variant = key[:-1] if key.endswith("s") else key + "s"
            if variant != key:
                self.by_name.setdefault(variant, []).append(obj)

    def name_one(self, name: str) -> Optional[Any]:
        """Unique-by-id name match (the same object can be indexed twice)."""
        hits = self.by_name.get(norm_key(name), [])
        unique: Dict[str, Any] = {}
        for h in hits:
            unique.setdefault(h.get("id"), h)
        if len(unique) == 1:
            return next(iter(unique.values()))
        return None


class FsData:
    """Loaded fs_data dump with resolution helpers."""

    def __init__(self, dir_path: str) -> None:
        self.dir_path = dir_path
        marker = os.path.join(dir_path, "marker.json")
        self.sha: Optional[str] = None
        if os.path.exists(marker):
            with open(marker, encoding="utf-8") as fh:
                self.sha = json.load(fh).get("sha")
        self.data: Dict[str, Dict[str, Any]] = {}
        for kind in DUMP_KINDS:
            path = os.path.join(dir_path, f"{kind}.json")
            if os.path.exists(path):
                with open(path, encoding="utf-8") as fh:
                    self.data[kind] = json.load(fh)
            else:
                self.data[kind] = {}
        grants_path = os.path.join(dir_path, "kit_grants.json")
        if os.path.exists(grants_path):
            with open(grants_path, encoding="utf-8") as fh:
                self.kit_grants: Dict[str, list] = json.load(fh)
        else:
            self.kit_grants = {}
            logger.warning("dump %s lacks kit_grants.json; kit re-nesting "
                           "falls back to type-matching", dir_path)
        membership_path = os.path.join(dir_path, "setting_membership.json")
        if os.path.exists(membership_path):
            with open(membership_path, encoding="utf-8") as fh:
                self.setting_membership: Dict[str, Dict[str, Any]] = \
                    json.load(fh)
        else:
            self.setting_membership = {}
            logger.warning("dump %s lacks setting_membership.json; "
                           "settingIDs derivation degrades to default",
                           dir_path)

        self.global_index = _Index()
        self.scopes: Dict[str, _Index] = {}
        for kind, entries in self.data.items():
            scope = _Index()
            for obj in entries.values():
                scope.add(obj)
                self.global_index.add(obj)
                for payload in _walk_payloads(obj):
                    scope.add(payload)
                    self.global_index.add(payload)
            self.scopes[f"kind:{kind}"] = scope
        # Class-scoped resolution indexes (features/abilities per class tree).
        for cls in self.data.get("classes", {}).values():
            scope = _Index()
            for payload in _walk_payloads(cls):
                scope.add(payload)
            self.scopes[f"class:{cls.get('id')}"] = scope
        # Ancestry-scoped indexes (trait choices live inside ancestry trees).
        for anc in self.data.get("ancestries", {}).values():
            scope = _Index()
            for payload in _walk_payloads(anc):
                scope.add(payload)
            self.scopes[f"ancestry:{anc.get('id')}"] = scope

    # --- payload lookup (spec: payload hydration) -----------------------------
    def get_payload(self, dsid: str) -> Optional[Any]:
        return self.global_index.by_id.get(dsid)

    # --- origin/kind resolution (design D7 id drift) --------------------------
    def resolve_kind(self, itype: str, dsid: Optional[str], name: str,
                     ) -> Optional[Any]:
        """Resolve a Foundry origin item to its raw ForgeSteel data object.

        Deterministic id transforms first (TYPE_PREFIXES, culture stem),
        then curated aliases, then an exact normalized-name match last.
        """
        kind = {"ancestry": "ancestries", "culture": "cultures", "class": "classes",
                "career": "careers", "complication": "complications",
                "perk": "perks", "kit": "kits", "title": "titles"}.get(itype)
        if kind is None:
            return None
        entries = self.data.get(kind, {})
        if dsid:
            candidates = [dsid, ID_ALIASES.get(f"{itype}\x00{dsid}")]
            prefix = TYPE_PREFIXES.get(itype)
            if prefix:
                candidates.append(f"{prefix}{dsid}")
            if itype == "culture" and dsid.endswith(CULTURE_DSID_SUFFIX):
                candidates.append(f"culture-{dsid[:-len(CULTURE_DSID_SUFFIX)]}")
            for candidate in candidates:
                if candidate and candidate in entries:
                    return entries[candidate]
        return self.scopes[f"kind:{kind}"].name_one(name)

    def resolve_trait(self, ancestry_obj: Optional[Any], dsid: Optional[str],
                      name: str) -> Optional[Any]:
        """Trait/ancestry-feature resolution: ancestry tree first, then global.

        Ancestry trees often hold the same trait twice (a fixed feature and a
        Choice option). Ambiguous name hits are resolved toward the pool the
        app actually selects from: ids appearing as a Choice option or an
        explicit selection inside the ancestry tree.
        """
        if ancestry_obj is not None:
            scope = self.scopes.get(f"ancestry:{ancestry_obj.get('id')}")
            if scope is not None:
                if dsid and dsid in scope.by_id:
                    return scope.by_id[dsid]
                hit = self._pick_trait(scope, name, ancestry_obj)
                if hit is not None:
                    return hit
        if dsid and dsid in self.global_index.by_id:
            return self.global_index.by_id[dsid]
        return self.global_index.name_one(name)

    @staticmethod
    def _pick_trait(scope: "_Index", name: str, ancestry_obj: Any) -> Optional[Any]:
        hits = scope.by_name.get(norm_key(name), [])
        unique: Dict[str, Any] = {}
        for h in hits:
            unique.setdefault(h.get("id"), h)
        if len(unique) == 1:
            return next(iter(unique.values()))
        if not unique:
            return None
        top_ids = {f.get("id") for f in ancestry_obj.get("features", [])
                   if isinstance(f, dict)}
        wanted = [h for hid, h in unique.items() if hid in top_ids]
        if len(wanted) == 1:
            return wanted[0]
        choice_ids: set = set()
        for payload in _walk_payloads(ancestry_obj):
            data = payload.get("data")
            if not isinstance(data, dict):
                continue
            for opt in data.get("options", []) or []:
                if isinstance(opt, dict) and isinstance(opt.get("feature"), dict):
                    choice_ids.add(opt["feature"].get("id"))
            sel = data.get("selected")
            if isinstance(sel, list):
                for s in sel:
                    if isinstance(s, dict):
                        choice_ids.add(s.get("id"))
        wanted = [h for hid, h in unique.items() if hid in choice_ids]
        return wanted[0] if len(wanted) == 1 else None

    def resolve_subclass(self, class_obj: Any, dsid: Optional[str], name: str,
                         ) -> Optional[Any]:
        for sub in (class_obj or {}).get("subclasses", []) or []:
            if dsid and sub.get("id") == dsid:
                return sub
        for sub in (class_obj or {}).get("subclasses", []) or []:
            if norm_key(sub.get("name", "")) == norm_key(name):
                return sub
        return None

    def resolve_feature(self, dsid: Optional[str], name: str,
                        class_obj: Optional[Any] = None,
                        prefer: str = "any") -> Optional[Any]:
        """Resolve a Foundry feature/ability item to an FS feature/ability.

        Order: class scope id -> class scope name -> global id -> global unique
        name -> alias table (design D7: never guess across scopes). Ambiguous
        name hits are disambiguated by ``prefer``: 'ability' items resolve to
        hits listed in the class's ability pool; 'feature' items to the rest.
        """
        if class_obj is not None:
            scope = self.scopes.get(f"class:{class_obj.get('id')}")
            if scope is not None:
                if dsid and dsid in scope.by_id:
                    return scope.by_id[dsid]
                hit = self._pick(scope, name, class_obj, prefer)
                if hit is not None:
                    return hit
        if dsid:
            alias = ID_ALIASES.get(f"feature\x00{dsid}") or ID_ALIASES.get(f"ability\x00{dsid}")
            for candidate in (dsid, alias):
                if candidate and candidate in self.global_index.by_id:
                    return self.global_index.by_id[candidate]
        return self.global_index.name_one(name)

    @staticmethod
    def _pick(scope: "_Index", name: str, class_obj: Any, prefer: str) -> Optional[Any]:
        hits = scope.by_name.get(norm_key(name), [])
        unique: Dict[str, Any] = {}
        for h in hits:
            unique.setdefault(h.get("id"), h)
        if len(unique) == 1:
            return next(iter(unique.values()))
        if not unique:
            return None
        ability_pool_ids = {a.get("id") for a in (class_obj or {}).get("abilities", [])
                            if isinstance(a, dict)}
        if prefer == "ability":
            wanted = [h for h in unique.values() if h.get("type") == "Ability"]
            if len(wanted) != 1:
                wanted = [h for hid, h in unique.items() if hid in ability_pool_ids]
        elif prefer == "feature":
            wanted = [h for h in unique.values() if h.get("type") != "Ability"]
        else:
            wanted = list(unique.values())
        return wanted[0] if len(wanted) == 1 else None

    def perk_by_name(self, name: str) -> Optional[Any]:
        return self.scopes["kind:perks"].name_one(name)

    def perk_by_dsid(self, dsid: str) -> Optional[Any]:
        if dsid in self.data.get("perks", {}):
            return self.data["perks"][dsid]
        alias = ID_ALIASES.get(f"perk\x00{dsid}")
        if alias:
            return self.data.get("perks", {}).get(alias)
        return None

    def settings_for(self, used_ids: List[str]) -> tuple:
        """(setting_ids, uncertain_ids): settings owning any used dsid.

        'core' is always included; ids not present in any setting membership
        (e.g. community/custom content) are returned as uncertain (design D6).
        """
        found: Dict[str, bool] = {"core": True}
        uncertain: List[str] = []
        for oid in used_ids:
            owners = [sid for sid, entry in self.setting_membership.items()
                      if oid in entry.get("members", [])]
            if owners:
                for sid in owners:
                    found[sid] = True
            else:
                uncertain.append(oid)
        settings = ["core"] + sorted(s for s in found if s != "core")
        return settings, uncertain
