"""Structural invariants of the .ds-hero format, derived from the app corpus.

The sample corpus (*.ds-hero at repo root) consists of files exported by the
ForgeSteel app itself — immune to forward-converter bugs. Invariants are
derived from the corpus intersection (conservative) and frozen into
``schema/spec.json``; generated documents are validated against the spec
before write.

Usage:
    python -m converter.reverse.ds_hero_schema refresh [--corpus GLOB]
    python -m converter.reverse.ds_hero_schema check DOC.json [...]
"""

import argparse
import glob
import json
import logging
import os
import sys
from collections import Counter
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

SPEC_PATH = os.path.join(os.path.dirname(__file__), "schema", "spec.json")
DEFAULT_CORPUS = "*.ds-hero"

#: FeatureType enum values (forgesteel_repo/src/enums/feature-type.ts). Objects
#: carrying id/type but one of these types are not Feature documents (e.g.
#: Kit objects embedded in ``data.selected``) and carry no ``data`` key.
FEATURE_TYPES = frozenset({
    "Text", "Ability", "Ability Cost", "Ability Damage", "Ability Distance",
    "Add-On", "Ancestry Choice", "Ancestry Feature Choice", "Bonus",
    "Characteristic Bonus", "Choice", "Class Ability", "Companion",
    "Condition Immunity", "Damage Modifier", "Domain", "Domain Feature",
    "Fixture", "Follower", "Heroic Resource", "Heroic Resource Gain",
    "Item Choice", "Kit", "Language", "Language Choice", "Malice",
    "Malice Ability", "Movement Mode", "Multiple Features", "Package",
    "Package Content", "Perk", "Proficiency", "Save Threshold", "Size",
    "Skill Choice", "Speed", "Summon", "Summon Choice", "Tagged Feature",
    "Tagged Feature Choice", "Title",
})

TYPE_NAMES = {
    dict: "object", list: "array", str: "string",
    int: "integer", float: "number", bool: "boolean",
}


def _tname(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int,)):
        return "integer"
    return TYPE_NAMES.get(type(value), type(value).__name__)


def _iter_features(doc: Dict[str, Any]):
    """Yield every feature-shaped object embedded in a hero document."""
    def walk_features(seq: Any):
        if isinstance(seq, list):
            for f in seq:
                if isinstance(f, dict) and "id" in f and "type" in f \
                        and f.get("type") in FEATURE_TYPES:
                    yield f
                    data = f.get("data")
                    if isinstance(data, dict):
                        for nested_key in ("features",):
                            yield from walk_features(data.get(nested_key))
                        selected = data.get("selected")
                        if isinstance(selected, list):
                            for sel in selected:
                                if isinstance(sel, dict) and "id" in sel \
                                        and sel.get("type") in FEATURE_TYPES:
                                    yield sel
    blocks = [doc.get("features")]
    for key in ("ancestry", "career", "complication"):
        block = doc.get(key)
        if isinstance(block, dict):
            blocks.append(block.get("features"))
    hero_class = doc.get("class")
    if isinstance(hero_class, dict):
        for entry in hero_class.get("featuresByLevel", []) or []:
            blocks.append(entry.get("features") if isinstance(entry, dict) else None)
        for sub in hero_class.get("subclasses", []) or []:
            if isinstance(sub, dict):
                for entry in sub.get("featuresByLevel", []) or []:
                    blocks.append(entry.get("features") if isinstance(entry, dict) else None)
    for block in blocks:
        yield from walk_features(block)


def derive_invariants(docs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Intersect required keys/types across all corpus documents."""
    if not docs:
        raise ValueError("cannot derive invariants from an empty corpus")

    top_required = set(docs[0].keys())
    for d in docs[1:]:
        top_required &= set(d.keys())

    state_types: Dict[str, str] = {}
    states = [d.get("state") for d in docs if isinstance(d.get("state"), dict)]
    if states:
        common = set(states[0].keys())
        for s in states[1:]:
            common &= set(s.keys())
        for key in sorted(common):
            kinds = {_tname(s[key]) for s in states}
            if len(kinds) == 1:
                state_types[key] = next(iter(kinds))

    feature_key_counts: Counter = Counter()
    feature_total = 0
    for d in docs:
        for feature in _iter_features(d):
            feature_total += 1
            for key in feature.keys():
                feature_key_counts[key] += 1
    # Required iff present on EVERY feature object in the corpus.
    feature_required = sorted(
        k for k, n in feature_key_counts.items() if n == feature_total
    )

    def block_required(path_keys: List[str]) -> List[str]:
        blocks = []
        for d in docs:
            node = d.get(path_keys[0])
            if isinstance(node, dict):
                blocks.append(node)
        if not blocks:
            return []
        common = set(blocks[0].keys())
        for b in blocks[1:]:
            common &= set(b.keys())
        return sorted(common)

    return {
        "corpus_size": len(docs),
        "top_required": sorted(top_required),
        "state_types": state_types,
        "feature_required_keys": feature_required,
        "blocks": {
            "ancestry": block_required(["ancestry"]),
            "culture": block_required(["culture"]),
            "class": block_required(["class"]),
            "career": block_required(["career"]),
            "complication": block_required(["complication"]),
        },
    }


def validate_document(doc: Dict[str, Any], spec: Dict[str, Any]) -> List[str]:
    """Return a list of ``json-path: problem`` violation strings (empty = OK)."""
    violations: List[str] = []

    for key in spec.get("top_required", []):
        if key not in doc:
            violations.append(f"$/{key}: required top-level key missing")

    state = doc.get("state")
    if isinstance(state, dict):
        for key, expected in spec.get("state_types", {}).items():
            if key not in state:
                violations.append(f"$/state/{key}: required state key missing")
            elif _tname(state[key]) != expected:
                violations.append(
                    f"$/state/{key}: expected {expected}, got {_tname(state[key])}"
                )

    for block_key, required in spec.get("blocks", {}).items():
        block = doc.get(block_key)
        if block is None and block_key in ("complication",):
            continue  # optional block
        if isinstance(block, dict):
            for key in required:
                if key not in block:
                    violations.append(f"$/{block_key}/{key}: required key missing")
        elif block is not None:
            violations.append(f"$/{block_key}: expected object, got {_tname(block)}")

    hero_class = doc.get("class")
    if isinstance(hero_class, dict):
        level = hero_class.get("level")
        if not isinstance(level, int) or not 1 <= level <= 10:
            violations.append("$/class/level: expected integer 1..10")

    required_feature_keys = set(spec.get("feature_required_keys", []))
    for feature in _iter_features(doc):
        missing = required_feature_keys - set(feature.keys())
        for key in sorted(missing):
            violations.append(
                f"$/feature[{feature.get('id')}]: required key '{key}' missing"
            )
    return violations


def load_spec(spec_path: str = SPEC_PATH) -> Dict[str, Any]:
    with open(spec_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def refresh_spec(corpus_glob: str = DEFAULT_CORPUS, spec_path: str = SPEC_PATH) -> Dict[str, Any]:
    paths = sorted(glob.glob(corpus_glob))
    docs = []
    for p in paths:
        try:
            with open(p, "r", encoding="utf-8") as fh:
                docs.append(json.load(fh))
        except (OSError, ValueError):
            logger.warning("skipping unreadable corpus file %s", p)
    spec = derive_invariants(docs)
    os.makedirs(os.path.dirname(spec_path), exist_ok=True)
    with open(spec_path, "w", encoding="utf-8") as fh:
        json.dump(spec, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return spec


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(prog="ds_hero_schema")
    sub = parser.add_subparsers(dest="cmd", required=True)
    refresh = sub.add_parser("refresh", help="re-derive spec.json from the corpus")
    refresh.add_argument("--corpus", default=DEFAULT_CORPUS)
    refresh.add_argument("--out", default=SPEC_PATH)
    check = sub.add_parser("check", help="validate documents against the spec")
    check.add_argument("docs", nargs="+")
    args = parser.parse_args(argv)

    if args.cmd == "refresh":
        spec = refresh_spec(args.corpus, args.out)
        print(f"spec refreshed from {spec['corpus_size']} files -> {args.out}")
        return 0

    spec = load_spec()
    failures = 0
    for path in args.docs:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
        violations = validate_document(doc, spec)
        if violations:
            failures += 1
            print(f"FAIL {path}")
            for violation in violations:
                print(f"  {violation}")
        else:
            print(f"OK   {path}")
    return 1 if failures else 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
