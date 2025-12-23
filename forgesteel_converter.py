"""
===============================================================================
FORGESTEEL CONVERTER - MAIN CONVERSION SCRIPT
===============================================================================

THIS IS THE PRIMARY SCRIPT FOR CONVERTING FORGESTEEL CHARACTERS TO FOUNDRY VTT

USAGE:
    python forgesteel_converter.py input.ds-hero output.json

EXAMPLE:
    python forgesteel_converter.py Swami.ds-hero Swami_converted.json

DO NOT USE converter/mapper.py DIRECTLY - that is an internal module only!
===============================================================================
"""

import argparse
import json
import sys
import logging
from pathlib import Path
from converter.loader import load_forgesteel_character, load_compendium_items
from converter.mapper import convert_character
from converter.writer import write_foundry_character

# Version
__version__ = "1.2.0"

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Convert forgesteel character files to Foundry VTT format.",
        epilog="Example: python forgesteel_converter.py character.ds-hero character.json",
    )
    parser.add_argument("input", help="The path to the forgesteel .ds-hero file")
    parser.add_argument(
        "output", help="The path to save the converted Foundry VTT .json file"
    )
    parser.add_argument(
        "--compendium",
        help="The path to the draw_steel_repo/src/packs directory",
        default="draw_steel_repo/src/packs",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging for debugging",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail on missing compendium items instead of creating placeholders",
    )
    parser.add_argument(
        "--update-compendium",
        "-u",
        action="store_true",
        help="Force update compendium to latest version from GitHub",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Validate input file
    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(f"Input file not found: {args.input}")
        return 1

    try:
        # Note: Compendium path uses hybrid approach:
        # 1. Local (if specified/exists)
        # 2. Cache (if available)
        # 3. GitHub (automatic fallback)
        compendium_path = Path(args.compendium)

        logger.debug(f"Input: {input_path.resolve()}")
        logger.debug(f"Output: {Path(args.output).resolve()}")
        logger.debug(f"Compendium (preferred): {compendium_path.resolve()}")

        logger.info(f"Loading character from {args.input}...")
        forgesteel_char = load_forgesteel_character(args.input)
        char_name = forgesteel_char.get("name", "Unknown")
        logger.debug(f"Loaded character: {char_name}")

        logger.info("Loading compendium items...")
        # Check if we should only load specific types for performance
        target_types = [
            "ability",
            "ancestry",
            "career",
            "culture",
            "class",
            "perk",
            "project",
        ]
        compendium_items = load_compendium_items(
            str(compendium_path),
            verbose=args.verbose,
            force_update=args.update_compendium,
            target_types=target_types,
        )
        logger.debug(f"Loaded {len(compendium_items)} compendium items")

    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        return 1
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {args.input}: {e}")
        return 1
    except Exception as e:
        logger.error(f"Error loading files: {e}")
        if args.verbose:
            logger.debug("", exc_info=True)
        return 1

    try:
        logger.info("Converting character...")
        foundry_char = convert_character(
            forgesteel_char, compendium_items, strict=args.strict, verbose=args.verbose
        )
        logger.debug(f"Loaded {len(compendium_items)} compendium items")

    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        return 1
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {args.input}: {e}")
        return 1
    except Exception as e:
        logger.error(f"Error loading files: {e}")
        if args.verbose:
            logger.debug("", exc_info=True)
        return 1

    try:
        logger.info("Converting character...")
        foundry_char = convert_character(
            forgesteel_char, compendium_items, strict=args.strict, verbose=args.verbose
        )

        if not foundry_char:
            logger.error("Character conversion failed - no data returned")
            return 1

        item_count = len(foundry_char.get("items", []))
        logger.debug(f"Converted to {item_count} Foundry items")

        logger.info(f"Saving converted character to {args.output}...")
        write_foundry_character(foundry_char, args.output)

        logger.info("Conversion complete!")
        logger.info(f"Successfully converted '{char_name}' with {item_count} items")
        return 0

    except Exception as e:
        logger.error(f"Error during conversion: {e}")
        if args.verbose:
            logger.debug("", exc_info=True)
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code if exit_code else 0)
