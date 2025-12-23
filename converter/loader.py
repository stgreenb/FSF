"""
===============================================================================
CONVERTER MODULES - INTERNAL USE ONLY
===============================================================================

These are internal modules for the forgesteel converter.
DO NOT RUN THESE MODULES DIRECTLY!

USE THE MAIN CONVERSION SCRIPT:
    python forgesteel_converter.py input.ds-hero output.json

See forgesteel_converter.py for proper usage instructions.
===============================================================================
"""

import json
import os
import urllib.request
import urllib.error
from pathlib import Path

# GitHub repository details for Draw Steel
GITHUB_REPO = "MetaMorphic-Digital/draw-steel"
GITHUB_BRANCH = "main"
GITHUB_RAW_URL = (
    f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/src/packs"
)
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/contents/src/packs"


def load_forgesteel_character(file_path):
    """Loads a forgesteel character from a .ds-hero file."""
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _fetch_github_files(verbose=False):
    """Fetches JSON files from Draw Steel GitHub repository.

    Returns a dict of {dsid: item_data} loaded from GitHub.
    """
    items = {}
    items_loaded = 0

    if verbose:
        print("DEBUG: Fetching compendium from GitHub...")

    try:
        # Get list of pack directories
        req = urllib.request.Request(
            GITHUB_API_URL,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "forgesteel-converter",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            packs = json.loads(response.read().decode("utf-8"))

        for pack in packs:
            if pack["type"] != "dir":
                continue

            pack_name = pack["name"]
            if verbose:
                print(f"DEBUG: Fetching pack directory: {pack_name}")

            # Recursively get files from this pack directory
            _fetch_pack_files(pack["url"], items, pack_name, verbose)

        if verbose:
            print(f"DEBUG: GitHub fetch complete: {len(items)} items loaded")
        return items

    except urllib.error.URLError as e:
        print(f"Warning: Could not fetch from GitHub: {e}")
        return {}
    except Exception as e:
        print(f"Warning: Error fetching GitHub files: {e}")
        return {}


def _fetch_pack_files(api_url, items_dict, pack_name, verbose=False, depth=0):
    """Recursively fetches JSON files from a GitHub API directory URL."""
    if depth > 10:  # Increase depth limit for nested directories
        return

    try:
        req = urllib.request.Request(
            api_url,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "forgesteel-converter",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            items = json.loads(response.read().decode("utf-8"))

        if verbose:
            print(
                f"DEBUG: Processing {len(items)} items in {pack_name} (depth {depth})"
            )

        for item in items:
            if item["type"] == "file" and item["name"].endswith(".json"):
                # Download the file
                raw_url = item["download_url"]
                try:
                    with urllib.request.urlopen(raw_url, timeout=10) as response:
                        file_data = json.loads(response.read().decode("utf-8"))
                        if "_dsid" in file_data.get("system", {}):
                            dsid = file_data["system"]["_dsid"]
                            if dsid not in items_dict:
                                items_dict[dsid] = file_data
                                if verbose:
                                    print(f"DEBUG: Loaded {dsid} from {item['name']}")
                except Exception as e:
                    if verbose:
                        print(f"DEBUG: Could not load {item['name']}: {e}")

            elif item["type"] == "dir":
                # Recurse into subdirectory
                if verbose:
                    print(f"DEBUG: Recursing into directory: {item['name']}")
                _fetch_pack_files(
                    item["url"], items_dict, pack_name, verbose, depth + 1
                )

    except urllib.error.URLError:
        if verbose:
            print(f"DEBUG: Could not access {pack_name} directory")
    except Exception as e:
        if verbose:
            print(f"DEBUG: Error processing {pack_name}: {e}")


def _ensure_compendium_path(compendium_path):
    """Ensures compendium path exists, fetching from GitHub if needed."""
    compendium_path = Path(compendium_path)

    # If local path exists, use it
    if compendium_path.exists():
        return str(compendium_path)

    # Try cache
    cache_dir = Path.home() / ".cache" / "forgesteel-converter" / "compendium"
    if cache_dir.exists() and list(cache_dir.glob("*.json")):
        return str(cache_dir)

    # Return the default path anyway (will be handled by caller)
    return str(compendium_path)


def _find_ancestries_directory(packs_path):
    """Find the actual ancestries directory with ID suffix."""
    origins_dir = packs_path / "origins"
    if origins_dir.exists():
        for item in origins_dir.iterdir():
            if item.is_dir() and item.name.startswith("Ancestries"):
                return item
    return None


def load_compendium_items(
    compendium_path, verbose=False, force_update=False, target_types=None
):
    """Loads all items from the compendium packs with enhanced ancestry support.

    Args:
        compendium_path: Path to the draw_steel_repo/src/packs directory
        verbose: Enable verbose logging for debugging
        force_update: Force refresh from GitHub (currently ignored)
        target_types: List of item types to load for better performance
    """
    items = {}
    items_loaded = 0
    duplicates_resolved = 0

    compendium_path = Path(compendium_path)
    cache_dir = Path.home() / ".cache" / "forgesteel-converter" / "compendium"

    # Try local path first
    if compendium_path.exists() and compendium_path.is_dir():
        if verbose:
            print(f"DEBUG: Loading local compendium from {compendium_path}")

        for root, _, files in os.walk(compendium_path):
            for file in files:
                if file.endswith(".json"):
                    file_path = os.path.join(root, file)
                    _load_json_item(file_path, items, verbose)

        if items:
            items_loaded = len(items)
            if verbose:
                print(
                    f"DEBUG: Compendium stats: {items_loaded} items loaded from local"
                )
            return items

    # Try cache next
    if cache_dir.exists() and cache_dir.is_dir():
        if verbose:
            print(f"DEBUG: Loading compendium from cache...")

        for file in cache_dir.glob("*.json"):
            _load_json_item(str(file), items, verbose)

        if items:
            items_loaded = len(items)
            if verbose:
                print(
                    f"DEBUG: Compendium stats: {items_loaded} items loaded from cache"
                )
            return items

    # Fall back to GitHub
    if verbose:
        print(f"DEBUG: Local and cache not available, fetching from GitHub...")

    github_items = _fetch_github_files(verbose)

    if github_items:
        # Cache the downloaded items
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            for dsid, item_data in github_items.items():
                cache_file = cache_dir / f"{dsid}.json"
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(item_data, f)
            if verbose:
                print(f"DEBUG: Cached {len(github_items)} items to {cache_dir}")
        except Exception as e:
            if verbose:
                print(f"DEBUG: Could not cache items: {e}")

        items_loaded = len(github_items)
        if verbose:
            print(f"DEBUG: Compendium stats: {items_loaded} items loaded from GitHub")
        return github_items

    # If nothing worked, return empty
    print("Warning: Could not load compendium from local, cache, or GitHub")
    return {}


def _load_json_item(file_path, items_dict, verbose=False):
    """Loads a single JSON item and adds it to items_dict."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            item_data = json.load(f)

            # Fix action types to be lowercase for Foundry compatibility
            if (
                item_data.get("type") == "ability"
                and "system" in item_data
                and "type" in item_data["system"]
            ):
                current_type = item_data["system"]["type"]
                if isinstance(current_type, str):
                    item_data["system"]["type"] = current_type.lower()

            if "_dsid" in item_data.get("system", {}):
                dsid = item_data["system"]["_dsid"]

                # If we haven't seen this dsid yet, add it
                if dsid not in items_dict:
                    items_dict[dsid] = item_data
                    if verbose:
                        print(f"DEBUG: Loaded {dsid} ({item_data.get('type')})")
                else:
                    # If we have seen it, prefer non-heroic over heroic
                    existing_category = (
                        items_dict[dsid].get("system", {}).get("category", "")
                    )
                    new_category = item_data.get("system", {}).get("category", "")

                    # Prefer non-heroic (empty category) over heroic
                    if existing_category == "heroic" and new_category != "heroic":
                        if verbose:
                            print(
                                f"DEBUG: Duplicate {dsid}: preferring {item_data.get('name')} (non-heroic) over existing (heroic)"
                            )
                        items_dict[dsid] = item_data
    except json.JSONDecodeError:
        print(f"Warning: Could not decode JSON from {file_path}")
