"""Structured loss/warning reporting (spec: conversion-loss-reporting).

Closed vocabularies: loss REASONS and ACTIONS are fixed; warnings ride in an
independent array so a clean losses list never masks state fidelity gaps.
"""

import json
from typing import Any, Dict, List, Optional

REASONS = frozenset({
    "unmappable",
    "payload-unavailable",
    "unsupported-construct",
    "version-mismatch",
    "defaulted",
})

ACTIONS = frozenset({"dropped", "recovered-by-name", "defaulted"})

WARNING_CODES = frozenset({
    "payload-divergence",
    "state-reset",
    "setting-uncertain",
    "dump-stale",
    "unrepresentable-picture",
    "mechanical-effects-lost",
})


class LossReport:
    """Accumulates losses and warnings; serialized as ``<output>.report.json``."""

    def __init__(self) -> None:
        self.input_path: Optional[str] = None
        self.output_path: Optional[str] = None
        self.sources: Dict[str, str] = {}
        self.counts: Dict[str, Dict[str, int]] = {}
        self.losses: List[Dict[str, Any]] = []
        self.warnings: List[Dict[str, str]] = []

    # --- accumulation ---------------------------------------------------------
    def count(self, category: str, converted: int = 0, dropped: int = 0) -> None:
        bucket = self.counts.setdefault(category, {"converted": 0, "dropped": 0})
        bucket["converted"] += converted
        bucket["dropped"] += dropped

    def loss(
        self,
        item: Any,
        type: str,
        dsid: Optional[str],
        reason: str,
        action: str,
        detail: str = "",
    ) -> None:
        """Record a dropped/altered item. Raises on vocabulary violations."""
        if reason not in REASONS:
            raise ValueError(f"loss reason {reason!r} not in closed vocabulary")
        if action not in ACTIONS:
            raise ValueError(f"loss action {action!r} not in closed vocabulary")
        self.losses.append({
            "item": item if isinstance(item, str) else str(item),
            "type": type,
            "dsid": dsid,
            "reason": reason,
            "action": action,
            "detail": detail,
        })
        self.counts.setdefault(type, {"converted": 0, "dropped": 0})["dropped"] += 1

    def warning(self, code: str, detail: str = "") -> None:
        if code not in WARNING_CODES:
            raise ValueError(f"warning code {code!r} not in closed vocabulary")
        self.warnings.append({"code": code, "detail": detail})

    # --- queries ---------------------------------------------------------------
    @property
    def has_losses(self) -> bool:
        return bool(self.losses)

    @property
    def has_warnings(self) -> bool:
        return bool(self.warnings)

    def top_reasons(self, n: int = 3) -> List[str]:
        tally: Dict[str, int] = {}
        for entry in self.losses:
            tally[entry["reason"]] = tally.get(entry["reason"], 0) + 1
        ranked = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))
        return [f"{reason} x{count}" for reason, count in ranked[:n]]

    # --- serialization ----------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "input": self.input_path,
            "output": self.output_path,
            "sources": dict(self.sources),
            "counts": {k: dict(v) for k, v in sorted(self.counts.items())},
            "losses": self.losses,
            "warnings": self.warnings,
        }

    def write(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2, ensure_ascii=False)
            fh.write("\n")

    def summary_line(self, name: str, level: Any) -> str:
        return (
            f"{name} (level {level}): converted {self.total_converted()}, "
            f"dropped {len(self.losses)}, warnings {len(self.warnings)}"
            + (" — top reasons: " + ", ".join(self.top_reasons()) if self.losses else "")
        )

    def total_converted(self) -> int:
        return sum(b["converted"] for b in self.counts.values())
