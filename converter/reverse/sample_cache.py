"""Sample-file payload cache (task 1.3).

The root-level ``*.ds-hero`` corpus consists of real ForgeSteel app exports;
every payload object embedded in them (features, abilities, perks, kits, …)
is indexed by dsid and used as the fallback source when the versioned dump
lacks an object (design D3: dump canonical, samples fill gaps).
"""

import glob
import json
import logging
import os
from typing import Any, Dict, Optional

from .fs_data_cache import _Index, _walk_payloads

logger = logging.getLogger(__name__)


class SampleCache:
    """Payload index built from known-good app-exported .ds-hero files."""

    def __init__(self, corpus_glob: str) -> None:
        self.index = _Index()
        self.file_count = 0
        self.loaded_from: list = []
        for path in sorted(glob.glob(corpus_glob)):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    doc = json.load(fh)
            except (OSError, ValueError):
                logger.warning("sample cache: skipping unreadable %s", path)
                continue
            self.file_count += 1
            self.loaded_from.append(os.path.basename(path))
            for payload in _walk_payloads(doc):
                self.index.add(payload)  # first file (sorted) wins: deterministic

    def get_payload(self, dsid: str) -> Optional[Any]:
        return self.index.by_id.get(dsid)
