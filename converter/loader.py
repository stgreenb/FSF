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
import zipfile
import tempfile
import shutil
from pathlib import Path

# GitHub repository details for Draw Steel
GITHUB_REPO = "MetaMorphic-Digital/draw-steel"
GITHUB_BRANCH = "main"  # Fallback branch
GITHUB_RAW_URL = (
    f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/src/packs"
)
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/contents/src/packs"
GITHUB_RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases"


def _get_github_headers():
    """Get headers for GitHub API requests, including auth if available."""
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "forgesteel-converter",
    }
    # Check for GitHub token in environment (increases rate limit to 5000/hr)
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _log_http_error(operation, e, verbose=False):
    """Log HTTP errors with useful diagnostic information."""
    error_msg = f"HTTP error during {operation}"
    if hasattr(e, "code"):
        error_msg += f": HTTP {e.code}"
    if hasattr(e, "reason"):
        error_msg += f" - {e.reason}"

    # Common GitHub API error codes
    if hasattr(e, "code"):
        if e.code == 403:
            error_msg += " (rate limit exceeded or unauthenticated request blocked)"
            if verbose:
                print(
                    "DEBUG: To increase rate limit, set GITHUB_TOKEN environment variable"
                )
        elif e.code == 401:
            error_msg += " (invalid or expired token)"
        elif e.code == 404:
            error_msg += " (resource not found)"
    error_msg += f": {e}"

    if verbose:
        print(f"DEBUG: {error_msg}")
    return error_msg


def load_forgesteel_character(file_path):
    """Loads a forgesteel character from a .ds-hero file."""
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_latest_release_tag(verbose=False):
    """Get the latest release tag from GitHub repository."""
    try:
        req = urllib.request.Request(
            GITHUB_RELEASES_URL,
            headers=_get_github_headers(),
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            releases = json.loads(response.read().decode("utf-8"))

        if releases:
            latest_tag = releases[0]["tag_name"]  # First release is the latest
            if verbose:
                print(f"DEBUG: Using latest release tag: {latest_tag}")
            return latest_tag
        else:
            if verbose:
                print("DEBUG: No releases found, using default branch")
            return None

    except urllib.error.HTTPError as e:
        _log_http_error("fetching releases", e, verbose)
        return None
    except urllib.error.URLError as e:
        _log_http_error("network error fetching releases", e, verbose)
        return None
    except Exception as e:
        if verbose:
            print(f"Warning: Error getting releases: {e}")
        return None


def _fetch_github_files(verbose=False):
    """Fetches JSON files from Draw Steel GitHub repository.

    Returns a dict of {dsid: item_data} loaded from GitHub.
    """
    items = {}

    if verbose:
        print("DEBUG: Fetching compendium from GitHub...")

    # Try to get the latest release tag
    release_tag = _get_latest_release_tag(verbose)

    if release_tag:
        # Try to fetch from release zipball
        items = _fetch_from_release_zipball(release_tag, verbose)
        if items:
            return items

    # Fallback to default branch using API
    if verbose:
        print("DEBUG: Fetching from default branch (API)")

    try:
        req = urllib.request.Request(
            GITHUB_API_URL,
            headers=_get_github_headers(),
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
            _fetch_pack_files(pack["url"], items, pack_name, verbose, release_tag=None)

        if verbose:
            print(f"DEBUG: GitHub fetch complete: {len(items)} items loaded")
        return items

    except urllib.error.HTTPError as e:
        _log_http_error("fetching pack list from GitHub", e, verbose)
        return {}
    except urllib.error.URLError as e:
        _log_http_error("network error fetching from GitHub", e, verbose)
        return {}
    except Exception as e:
        print(f"Warning: Error fetching GitHub files: {e}")
        return {}


def _fetch_from_release_zipball(release_tag, verbose=False):
    """Fetch compendium items from a GitHub release zipball.

    Args:
        release_tag: The release tag to download (e.g., "release-0.9.2")
        verbose: Enable verbose logging

    Returns:
        Dict of {dsid: item_data} or empty dict if failed
    """
    items = {}

    try:
        # Construct the zipball URL
        zipball_url = (
            f"https://github.com/{GITHUB_REPO}/archive/refs/tags/{release_tag}.zip"
        )

        if verbose:
            print(f"DEBUG: Downloading release zipball from {zipball_url}")

        # Download the zipball
        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as temp_file:
            req = urllib.request.Request(
                zipball_url,
                headers={
                    "Accept": "application/zip",
                    "User-Agent": "forgesteel-converter",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                shutil.copyfileobj(response, temp_file)

            temp_zip_path = temp_file.name

        # Extract and process the zipball
        with tempfile.TemporaryDirectory() as temp_dir:
            if verbose:
                print(f"DEBUG: Extracting zipball to {temp_dir}")

            with zipfile.ZipFile(temp_zip_path, "r") as zip_ref:
                zip_ref.extractall(temp_dir)

            # Find the extracted directory (it will have a name like "draw-steel-release-0.9.2")
            extracted_dirs = [d for d in Path(temp_dir).iterdir() if d.is_dir()]
            if not extracted_dirs:
                if verbose:
                    print("DEBUG: No extracted directory found in zipball")
                return {}

            repo_dir = extracted_dirs[0]
            packs_dir = repo_dir / "src" / "packs"

            if not packs_dir.exists():
                if verbose:
                    print(f"DEBUG: Packs directory not found at {packs_dir}")
                return {}

            # Walk through all JSON files in the packs directory
            for json_file in packs_dir.rglob("*.json"):
                try:
                    _load_json_item(str(json_file), items, verbose)
                except Exception as e:
                    if verbose:
                        print(f"DEBUG: Could not load {json_file}: {e}")

        if verbose:
            print(f"DEBUG: Release zipball fetch complete: {len(items)} items loaded")
        return items

    except urllib.error.URLError as e:
        if verbose:
            print(f"DEBUG: Could not download release zipball: {e}")
        return {}
    except Exception as e:
        if verbose:
            print(f"DEBUG: Error processing release zipball: {e}")
        return {}
    finally:
        # Clean up temporary zip file
        try:
            os.unlink(temp_zip_path)
        except:
            pass


def _fetch_pack_files(
    api_url, items_dict, pack_name, verbose=False, depth=0, release_tag=None
):
    """Recursively fetches JSON files from a GitHub API directory URL."""
    if depth > 10:  # Increase depth limit for nested directories
        return

    try:
        # Add ref parameter if we're using a release tag
        if release_tag:
            api_url_with_ref = f"{api_url}?ref={release_tag}"
        else:
            api_url_with_ref = api_url

        req = urllib.request.Request(
            api_url_with_ref,
            headers=_get_github_headers(),
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
                    item["url"], items_dict, pack_name, verbose, depth + 1, release_tag
                )

    except urllib.error.HTTPError as e:
        _log_http_error(f"accessing {pack_name} directory", e, verbose)
    except urllib.error.URLError as e:
        _log_http_error(f"network error accessing {pack_name}", e, verbose)
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

    # Try local path first (unless force_update is True)
    if not force_update and compendium_path.exists() and compendium_path.is_dir():
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

    # Try cache next (unless force_update is True)
    if not force_update and cache_dir.exists() and cache_dir.is_dir():
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

    # Fall back to GitHub (or use if force_update)
    if verbose:
        if force_update:
            print(f"DEBUG: Force update requested, fetching from GitHub...")
        else:
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

    # If nothing worked, return empty with helpful guidance
    print("Warning: Could not load compendium from local, cache, or GitHub")
    print("  - Ensure the local path exists: --compendium /path/to/packs")
    print(
        "  - Download zip from GitHub (Code > Download ZIP), extract, and point --compendium to src/packs"
    )
    print("  - Or set GITHUB_TOKEN environment variable for higher rate limits")
    print("  - Or use --update-compendium (-u) to refresh cached data")
    return {}


def _load_json_item(file_path, items_dict, verbose=False):
    """Loads a single JSON item and adds it to items_dict."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            item_data = json.load(f)

            # Note: Don't convert system.type to lowercase - Foundry expects camelCase
            # (e.g., "freeTriggered", "freeManeuver", not "freetriggered", "freemaneuver")

            if "_dsid" in item_data.get("system", {}):
                dsid = item_data["system"]["_dsid"]
                item_type = item_data.get("type", "")
                item_id = item_data.get("_id", "")

                # Create a unique key that includes both dsid and type/id to avoid collisions
                # For abilities with same _dsid as traits, append type to key
                unique_key = dsid
                if dsid in items_dict:
                    existing_item = items_dict[dsid]
                    existing_type = existing_item.get("type", "")
                    existing_id = existing_item.get("_id", "")

                    # If different types have the same dsid, use the _id as the key
                    if existing_type != item_type:
                        unique_key = item_id  # Use the unique _id instead
                        if verbose:
                            print(
                                f"DEBUG: Collision for {dsid} - using _id {item_id} for {item_type}"
                            )

                # If we haven't seen this key yet, add it
                if unique_key not in items_dict:
                    items_dict[unique_key] = item_data
                    if verbose:
                        print(f"DEBUG: Loaded {unique_key} ({item_data.get('type')})")
                else:
                    # If we have seen it, prefer non-heroic over heroic
                    existing_category = (
                        items_dict[unique_key].get("system", {}).get("category", "")
                    )
                    new_category = item_data.get("system", {}).get("category", "")

                    # Prefer non-heroic (empty category) over heroic
                    if existing_category == "heroic" and new_category != "heroic":
                        if verbose:
                            print(
                                f"DEBUG: Duplicate {unique_key}: preferring {item_data.get('name')} (non-heroic) over existing (heroic)"
                            )
                        items_dict[unique_key] = item_data
    except json.JSONDecodeError:
        print(f"Warning: Could not decode JSON from {file_path}")
