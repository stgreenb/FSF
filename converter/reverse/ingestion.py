"""Foundry actor export ingestion: parse, validate, classify, resolve provenance.

Spec: ``foundry-actor-ingestion``. All Foundry-format field access goes through
:mod:`converter.reverse.foundry_format`; nothing here hard-codes export paths.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import foundry_format as ff
from .loss_report import LossReport

logger = logging.getLogger(__name__)


class ConversionInputError(Exception):
    """Fatal, human-readable input problem. Aborts with no output file."""


def _norm_name(name: str) -> str:
    return " ".join((name or "").casefold().split())


class PackIndex:
    """Index of the pinned Draw Steel compendium packs (Foundry side).

    Provides ``dsid -> {type, name}`` and a name fallback lookup
    ``(type, normalized name) -> dsid`` used when an export item lacks ``_dsid``.
    """

    def __init__(self) -> None:
        self.by_dsid: Dict[str, Dict[str, str]] = {}
        self._by_name: Dict[str, str] = {}

    @classmethod
    def from_pack_directory(cls, packs_dir: str) -> "PackIndex":
        index = cls()
        if not os.path.isdir(packs_dir):
            raise ConversionInputError(
                f"Compendium packs directory not found: {packs_dir}"
            )
        for root, _dirs, files in os.walk(packs_dir):
            for fname in files:
                if not fname.endswith(".json"):
                    continue
                try:
                    with open(os.path.join(root, fname), "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                except (OSError, ValueError):
                    continue
                if not isinstance(data, dict):
                    continue
                dsid = ff.get_dsid(data) or ff.get_pack_dsid(data)
                itype = data.get("type")
                iname = data.get("name")
                if not dsid or not isinstance(itype, str) or not isinstance(iname, str):
                    continue
                index.by_dsid.setdefault(dsid, {"type": itype, "name": iname})
                index._by_name.setdefault(ff_key(itype, iname), dsid)
        logger.debug("Pack index built: %d dsids", len(index.by_dsid))
        return index

    @classmethod
    def from_dict(cls, mapping: Dict[str, Dict[str, str]]) -> "PackIndex":
        """Build from ``{dsid: {type, name}}`` (tests / synthetic indexes)."""
        index = cls()
        for dsid, entry in mapping.items():
            index.by_dsid[dsid] = dict(entry)
            index._by_name[ff_key(entry["type"], entry["name"])] = dsid
        return index

    def name_lookup(self, itype: str, name: str) -> Optional[str]:
        return self._by_name.get(ff_key(itype, name))


def ff_key(itype: str, name: str) -> str:
    return f"{itype}\x00{_norm_name(name)}"


@dataclass
class IngestedItem:
    """One export item after classification and provenance resolution."""

    raw: Dict[str, Any]
    itype: str
    name: str
    dsid: Optional[str] = None
    provenance: str = "none"  # 'dsid' | 'name' | 'none'

    @property
    def level(self) -> Optional[int]:
        return ff.get_level(self.raw)

    def selections(self) -> List["Selection"]:
        return extract_selections(self)

    def system(self) -> Dict[str, Any]:
        return ff.system_of(self.raw)


@dataclass
class Selection:
    """A recorded advancement selection with its definition metadata."""

    adv_id: str
    kind: str                    # 'skill' | 'language' | 'itemGrant' | ...
    level: Optional[int]         # requirement level from the definition
    choose_n: Optional[int]
    selected: List[str] = field(default_factory=list)


def extract_selections(item: IngestedItem) -> List[Selection]:
    """Pair flag selections with their advancement definitions (design D7/spec)."""
    raw_item = item.raw
    defs = ff.get_advancement_defs(raw_item)
    flags = ff.get_flag_selections(raw_item)
    out: List[Selection] = []
    for adv_id, selected in flags.items():
        defn = defs.get(adv_id, {})
        choose_n = defn.get("chooseN")
        out.append(Selection(
            adv_id=adv_id,
            kind=ff.get_advancement_kind(raw_item, adv_id),
            level=ff.get_advancement_requirement_level(raw_item, adv_id),
            choose_n=choose_n if isinstance(choose_n, int) else None,
            selected=list(selected),
        ))
    return out


@dataclass
class IngestedActor:
    """Validated, classified actor export ready for reverse mapping."""

    name: str
    doc: Dict[str, Any]
    items: List[IngestedItem] = field(default_factory=list)
    malformed_count: int = 0

    def by_type(self, itype: str) -> List[IngestedItem]:
        return [i for i in self.items if i.itype == itype]

    def first_of_type(self, itype: str) -> Optional[IngestedItem]:
        found = self.by_type(itype)
        return found[0] if found else None


def load_actor(
    path: str,
    pack_index: Optional[PackIndex] = None,
    report: Optional[LossReport] = None,
) -> IngestedActor:
    """Parse and ingest one Foundry actor JSON export.

    Raises :class:`ConversionInputError` for fatal problems (unparseable,
    not-an-actor). Malformed or unknown *items* degrade to loss entries.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except OSError as exc:
        raise ConversionInputError(f"Cannot read input file {path}: {exc}") from exc
    except ValueError as exc:
        raise ConversionInputError(
            f"Input file {path} is not parseable JSON: {exc}"
        ) from exc

    if not isinstance(doc, dict):
        raise ConversionInputError(
            f"Input file {path} is not a JSON object"
        )
    if not ff.is_actor_document(doc):
        raise ConversionInputError(
            f"Input file {path} is not a Foundry actor export "
            "(missing 'items' array or 'system' object — is this a .ds-hero "
            "file fed to the wrong direction?)"
        )

    report = report if report is not None else LossReport()
    actor = IngestedActor(name=ff.actor_name(doc), doc=doc)

    for entry in doc.get("items", []):
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str) \
                or not isinstance(entry.get("type"), str):
            actor.malformed_count += 1
            report.loss(
                item=(entry.get("name") if isinstance(entry, dict) else str(entry)),
                type=(entry.get("type") if isinstance(entry, dict) else "?"),
                dsid=None, reason="unsupported-construct", action="dropped",
                detail="malformed items[] entry (non-object or missing name/type)",
            )
            continue
        ingested = _classify(entry, pack_index, report)
        actor.items.append(ingested)

    classes = actor.by_type(ff.TYPE_CLASS)
    if not classes:
        raise ConversionInputError(
            f"Actor '{actor.name}' has no class item; level and class cannot "
            "be guessed — aborting (spec: unresolvable class aborts)."
        )
    for extra in classes[1:]:
        report.loss(extra.name, extra.itype, extra.dsid,
                    reason="unsupported-construct", action="dropped",
                    detail="multi-classing not representable in ForgeSteel")
    return actor


def _classify(
    entry: Dict[str, Any],
    pack_index: Optional[PackIndex],
    report: LossReport,
) -> IngestedItem:
    itype = ff.item_type(entry)
    name = ff.item_name(entry)
    dsid = ff.get_dsid(entry)
    provenance = "dsid" if dsid else "none"

    if dsid is None and pack_index is not None:
        match = pack_index.name_lookup(itype, name)
        if match:
            dsid = match
            provenance = "name"
            report.loss(name, itype, dsid, reason="unmappable",
                        action="recovered-by-name",
                        detail="no provenance id; recovered via exact name "
                               "match against pinned packs")

    if itype not in ff.KNOWN_TYPES:
        report.loss(name, itype, dsid, reason="unsupported-construct",
                    action="dropped", detail=f"unknown Foundry item type {itype!r}")
    elif dsid is None:
        report.loss(name, itype, None, reason="unmappable", action="dropped",
                    detail="no provenance id and no compendium name match")
    return IngestedItem(raw=entry, itype=itype, name=name, dsid=dsid,
                        provenance=provenance)
