"""Dual-source payload provider (task 1.4, design D3).

Resolution order: versioned ``fs_data`` dump (canonical) -> sample-file cache
-> reportable miss. When both sources hold the same dsid with divergent
content, the dump wins and a ``payload-divergence`` warning is recorded so a
stale sample can never silently override pinned data.
"""

import json
import logging
from typing import Any, Dict, Optional, Tuple

from .fs_data_cache import FsData
from .loss_report import LossReport
from .sample_cache import SampleCache

logger = logging.getLogger(__name__)

SOURCE_DUMP = "dump"
SOURCE_SAMPLE = "sample"


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False)


class PayloadProvider:
    def __init__(self, fs_data: Optional[FsData], samples: SampleCache,
                 report: Optional[LossReport] = None) -> None:
        self.fs_data = fs_data
        self.samples = samples
        self.report = report
        self.sources_used: Dict[str, str] = {}
        self._divergence_seen: set = set()

    def get(self, dsid: str) -> Tuple[Optional[Any], Optional[str]]:
        """Return (payload, source) — (None, None) when no source has it."""
        dump_obj = self.fs_data.get_payload(dsid) if self.fs_data else None
        sample_obj = self.samples.get_payload(dsid)

        if dump_obj is not None:
            if sample_obj is not None and _canonical(dump_obj) != _canonical(sample_obj):
                if dsid not in self._divergence_seen and self.report is not None:
                    self._divergence_seen.add(dsid)
                    self.report.warning(
                        "payload-divergence",
                        f"{dsid}: dump payload differs from sample corpus; "
                        "dump used (refresh dump/samples if unexpected)",
                    )
            self.sources_used[dsid] = SOURCE_DUMP
            return dump_obj, SOURCE_DUMP

        if sample_obj is not None:
            self.sources_used[dsid] = SOURCE_SAMPLE
            return sample_obj, SOURCE_SAMPLE

        return None, None

    def get_or_raise(self, dsid: str) -> Any:
        obj, _src = self.get(dsid)
        if obj is None:
            raise KeyError(f"no payload source for dsid {dsid!r}")
        return obj
