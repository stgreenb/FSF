#!/usr/bin/env python3
"""Reverse converter CLI: Foundry VTT actor export -> ForgeSteel .ds-hero.

    python foundry_to_forgesteel.py fvtt-Actor-pyre-XXXX.json pyre.ds-hero
    python foundry_to_forgesteel.py export.json out.ds-hero --strict

Writes ``<output>.report.json`` on every successful conversion. Exit codes:
0 success (losses reported via the sidecar), non-zero on fatal input errors
or structural validation failure, non-zero under --strict when losses exist.
"""

import argparse
import json
import logging
import os
import shutil
import sys
from typing import Optional

from converter.reverse import foundry_format as ff
from converter.reverse.ds_hero_schema import load_spec, validate_document
from converter.reverse.fs_data_cache import (
    FsData, check_freshness, current_repo_sha, find_cache,
)
from converter.reverse.ingestion import (
    ConversionInputError, PackIndex, load_actor,
)
from converter.reverse.loss_report import LossReport
from converter.reverse.payload_provider import PayloadProvider
from converter.reverse.reverse_mapper import ReverseMapper
from converter.reverse.sample_cache import SampleCache

logger = logging.getLogger("foundry_to_forgesteel")

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PACKS = os.path.join(REPO_ROOT, "draw_steel_repo", "src", "packs")
DEFAULT_FS_REPO = os.path.join(REPO_ROOT, "forgesteel_repo")
DEFAULT_CORPUS = os.path.join(REPO_ROOT, "*.ds-hero")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Convert a Foundry VTT Draw Steel actor export to a "
                    "ForgeSteel .ds-hero file.")
    p.add_argument("input", help="Foundry actor JSON export (Export JSON)")
    p.add_argument("output", help="output .ds-hero path")
    p.add_argument("--strict", action="store_true",
                   help="exit non-zero when any item was lost")
    p.add_argument("--debug", action="store_true",
                   help="on structural validation failure, save the rejected "
                        "document to <output>.rejected.json")
    p.add_argument("--packs", default=DEFAULT_PACKS,
                   help="pinned Draw Steel packs directory (name-match index)")
    p.add_argument("--fs-repo", default=DEFAULT_FS_REPO,
                   help="forgesteel_repo checkout (freshness check)")
    p.add_argument("--fs-data", default=None,
                   help="fs_data dump directory (default: newest cached)")
    p.add_argument("--corpus", default=DEFAULT_CORPUS,
                   help="glob of sample .ds-hero files for the payload cache")
    p.add_argument("--picture", default=None, metavar="IMAGE",
                   help="image file to embed as the hero portrait (data URL)")
    p.add_argument("--verbose", "-v", action="store_true")
    return p


def load_picture(path: str) -> str:
    """Read an image file and encode it as a ForgeSteel portrait data URL
    (ForgeSteel stores hero.picture as an embedded base64 data URL)."""
    import base64
    with open(path, "rb") as fh:
        blob = fh.read()
    mime = "application/octet-stream"
    if blob[:8] == b"\x89PNG\r\n\x1a\n":
        mime = "image/png"
    elif blob[:3] == b"\xff\xd8\xff":
        mime = "image/jpeg"
    elif blob[:6] in (b"GIF87a", b"GIF89a"):
        mime = "image/gif"
    elif blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        mime = "image/webp"
    elif blob[:5] == b"<svg " or blob[:4] == b"<svg" or blob[:5] == b"<?xml":
        mime = "image/svg+xml"
    else:
        logger.warning("picture file %s has an unrecognized header; ForgeSteel "
                       "may not render it", path)
    return "data:%s;base64,%s" % (mime, base64.b64encode(blob).decode("ascii"))


def run(args: argparse.Namespace) -> int:
    report = LossReport()
    report.input_path = os.path.abspath(args.input)
    report.output_path = os.path.abspath(args.output)

    pack_index: Optional[PackIndex] = None
    try:
        pack_index = PackIndex.from_pack_directory(args.packs)
    except ConversionInputError as exc:
        logger.warning("pack index unavailable (%s); name-match fallback disabled",
                       exc)

    actor = load_actor(args.input, pack_index=pack_index, report=report)

    fs_data: Optional[FsData] = None
    data_dir = args.fs_data or find_cache()
    if data_dir and os.path.isdir(data_dir):
        fs_data = FsData(data_dir)
        report.sources["fs_data_sha"] = fs_data.sha or "unknown"
        if args.fs_repo and fs_data.sha:
            head = current_repo_sha(args.fs_repo)
            if head and not check_freshness(args.fs_repo, fs_data.sha):
                report.warning("dump-stale",
                               f"cached fs_data {fs_data.sha} != forgesteel_repo "
                               f"HEAD {head}; refresh the dump")
    else:
        logger.warning("no fs_data dump found (cache empty); relying on sample "
                       "payload cache only")
    report.sources["packs"] = _pack_version(args.packs)

    samples = SampleCache(args.corpus)
    provider = PayloadProvider(fs_data, samples, report)

    picture = None
    if args.picture:
        try:
            picture = load_picture(args.picture)
        except OSError as exc:
            print(f"error: cannot read --picture file: {exc}", file=sys.stderr)
            return 2

    mapper = ReverseMapper(actor, fs_data, provider, report,
                           skill_groups=_load_skill_groups(args),
                           picture=picture)
    document = mapper.build()

    violations = validate_document(document, load_spec())
    if violations:
        if args.debug:
            rejected = args.output + ".rejected.json"
            with open(rejected, "w", encoding="utf-8") as fh:
                json.dump(document, fh, indent=2, ensure_ascii=False)
            logger.error("structural validation failed; intermediate document "
                         "saved to %s", rejected)
        for violation in violations:
            logger.error("schema violation: %s", violation)
        raise ConversionInputError(
            f"structural validation failed with {len(violations)} violation(s); "
            "no output written")

    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(document, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    report.write(args.output + ".report.json")
    print(report.summary_line(actor.name, document["class"]["level"]))
    print(f"output: {args.output}")
    print(f"report: {args.output}.report.json")
    for warning in report.warnings:
        print(f"warning [{warning['code']}]: {warning['detail']}")
    if args.strict and report.has_losses:
        print(f"strict mode: {len(report.losses)} loss(es) -> non-zero exit")
        return 2
    return 0


def _load_skill_groups(args: argparse.Namespace) -> dict:
    config = os.path.join(REPO_ROOT, "draw_steel_repo", "src", "module",
                          "config.mjs")
    return ff.parse_skill_groups(config)


def _pack_version(packs_dir: str) -> str:
    marker = os.path.join(packs_dir, os.pardir, os.pardir, os.pardir,
                          "system.json")
    try:
        with open(marker, encoding="utf-8") as fh:
            return str(json.load(fh).get("version", "unknown"))
    except (OSError, ValueError):
        return "unknown"


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s")
    try:
        return run(args)
    except ConversionInputError as exc:
        logger.error("%s", exc)
        return 1
    except (OSError, ValueError) as exc:
        logger.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
