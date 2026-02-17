import json
import os


def _convert_feature(feature_data, item_type):
    """Converts a forgesteel feature to a Foundry VTT item."""
    return {
        "name": feature_data.get("name"),
        "type": item_type,
        "img": "icons/svg/mystery-man.svg",
        "system": {
            "description": {"value": feature_data.get("description"), "director": ""}
        },
    }


def _map_action_type(source_action_type: str) -> str:
    """Map source action types to Foundry's expected lowercase values.

    Args:
        source_action_type: Action type from source data (e.g., "Maneuver", "Main Action")

    Returns:
        Foundry-compatible action type (e.g., "maneuver", "main")
    """
    # Mapping from source action types to Foundry's expected values
    action_type_mapping = {
        "Maneuver": "maneuver",
        "Main Action": "main",
        "Move Action": "move",
        "Triggered Action": "triggered",
        "Free Action": "free",
        "Reaction": "reaction",
        "main": "main",
        "maneuver": "maneuver",
        "move": "move",
        "triggered": "triggered",
        "free": "free",
        "reaction": "reaction",
    }

    return action_type_mapping.get(source_action_type, source_action_type.lower())


def _convert_feature(feature_data, item_type, compendium_items):
    """Converts a forgesteel feature to a Foundry VTT item."""
    from converter.text_normalizer import TextNormalizer

    original_name = feature_data.get("name")
    name = (
        TextNormalizer.normalize_text(original_name) if original_name else original_name
    )

    # Special case mappings for features that have different names in Forgesteel vs Compendium
    known_mappings = {
        "Clarity": "clarity-and-strain",
        "Glowing Eyes": "glowing-eyes",
        "Psionic Bolt": "psionic-bolt",  # Handle space naming difference
    }

    compendium_item = None

    # Check if this is a known mapping
    if name in known_mappings and known_mappings[name] in compendium_items:
        compendium_item = compendium_items[known_mappings[name]]
    else:
        # Type mapping from Forgesteel to Foundry item types
        type_mapping = {
            "culture": "culture",
            "career": "career",
            "ancestry": "ancestry",
            "ancestryTrait": "ancestrytrait",
            "ability": "ability",
            "feature": "feature",
            "perk": "perk",
            "project": "project",
            "subclass": "subclass",
            "complication": "complication",
            "treasure": "treasure",
        }

        compendium_type = type_mapping.get(item_type)

        # First, try to find by name AND type (strict matching)
        if compendium_type:
            compendium_item = next(
                (
                    item
                    for item in compendium_items.values()
                    if item.get("name", "").lower() == name.lower()
                    and item.get("type", "").lower() == compendium_type.lower()
                ),
                None,
            )

        # If not found by exact name, try finding by type and similar name
        if not compendium_item and compendium_type:
            compendium_item = next(
                (
                    item
                    for item in compendium_items.values()
                    if name.lower() in item.get("name", "").lower()
                    and item.get("type", "").lower() == compendium_type.lower()
                ),
                None,
            )

        # If still not found by type, try just by name (case-insensitive, any type)
        if not compendium_item:
            compendium_item = next(
                (
                    item
                    for item in compendium_items.values()
                    if item.get("name", "").lower() == name.lower()
                ),
                None,
            )

        # Also try with quotes (some names have quotes in compendium)
        if not compendium_item:
            quoted_name = f'"{name}"'
            compendium_item = next(
                (
                    item
                    for item in compendium_items.values()
                    if item.get("name", "").lower() == quoted_name.lower()
                ),
                None,
            )

    # If not found by type+name, try variations by removing punctuation using text normalizer
    if not compendium_item and name:
        sanitized_name = TextNormalizer.sanitize_for_compendium_lookup(name)
        for item_name, item in compendium_items.items():
            item_sanitized = TextNormalizer.sanitize_for_compendium_lookup(item_name)
            if item_sanitized == sanitized_name:
                compendium_item = item
                break

    if compendium_item:
        item_copy = compendium_item.copy()
        # Override type to match what was requested (in case we found by name but different type)
        if item_copy.get("type") != item_type:
            item_copy["type"] = item_type

        # Apply description transfer to ensure proper Foundry format
        from converter.description_transfer import DescriptionTransfer

        description = DescriptionTransfer.transfer_description(feature_data, item_copy)

        # Ensure the description field exists and is properly formatted
        if "system" not in item_copy:
            item_copy["system"] = {}
        item_copy["system"]["description"] = {"value": description, "director": ""}

        # Override action type from source data for abilities
        if item_type == "ability":
            # Handle both wrapped data structures: {"data": {"ability": {...}}} and direct ability objects
            ability_data = None
            if "data" in feature_data and "ability" in feature_data["data"]:
                ability_data = feature_data["data"]["ability"]
            elif "type" in feature_data and "usage" in feature_data.get("type", {}):
                # This is a direct ability object
                ability_data = feature_data

            if ability_data:
                source_action_type = ability_data.get("type", {}).get("usage", "main")
                if source_action_type:
                    # Map source action types to Foundry's expected lowercase values
                    mapped_action_type = _map_action_type(source_action_type)
                    item_copy["system"]["type"] = mapped_action_type

        return item_copy

    # Use enhanced description transfer
    from converter.description_transfer import DescriptionTransfer

    description = DescriptionTransfer.transfer_description(
        feature_data, compendium_item
    )

    result_item = {
        "name": name,
        "type": item_type,
        "img": "icons/svg/mystery-man.svg",
        "system": {
            "_dsid": feature_data.get("id"),
            "description": {"value": description, "director": ""},
        },
        "effects": [],
        "flags": {},
        "_stats": {
            "compendiumSource": None,
            "duplicateSource": None,
            "exportSource": None,
            "coreVersion": "13.350",
            "systemId": "draw-steel",
            "systemVersion": "0.8.1",
            "lastModifiedBy": None,
        },
        "folder": None,
        "sort": 0,
        "ownership": {"default": 0},
    }

    # Add special handling for abilities with complex data
    if (
        item_type == "ability"
        and "data" in feature_data
        and "ability" in feature_data["data"]
    ):
        ability_data = feature_data["data"]["ability"]
        source_action_type = ability_data.get("type", {}).get("usage", "main")
        result_item["system"].update(
            {
                "keywords": ability_data.get("keywords", []),
                "type": _map_action_type(source_action_type),
                "distance": {
                    "type": "melee",
                    "primary": 1,
                    "secondary": None,
                    "tertiary": None,
                },
                "target": {"type": "creature", "value": 1},
                "effect": {"before": ability_data.get("description", ""), "after": ""},
                "power": {
                    "roll": {
                        "formula": "@chr",
                        "characteristics": ability_data.get("characteristic", []),
                    },
                    "effects": {},
                },
            }
        )

    return result_item


def convert_character(character_data, compendium_items, strict=False, verbose=False):
    """Converts forgesteel character data to Foundry VTT format.

    Args:
        character_data: Forgesteel character data (dict)
        compendium_items: Loaded compendium items (dict)
        strict: If True, fail on missing compendium items; if False, create placeholders
        verbose: If True, enable debug logging

    Returns:
        Foundry VTT character data (dict) or None on failure
    """
    from converter.level_detector import LevelDetector
    from converter.text_normalizer import TextNormalizer

    # Detect character level using multi-source detection
    character_level = LevelDetector.detect_level(character_data)
    if verbose:
        level_summary = LevelDetector.get_level_detection_summary(character_data)
        print(f"Level detection: {level_summary}")

    # Base values - stamina is always 20 for heroes at level 1
    base_stamina = 20

    # Get recoveries from class definition
    class_data = character_data.get("class", {})
    base_recoveries = class_data.get("recoveries", 8)

    # Calculate stability from ancestry traits (e.g., Grounded adds +1)
    base_stability = 0
    ancestry = character_data.get("ancestry", {})
    if ancestry:
        for feature in ancestry.get("features", []):
            if feature.get("type") == "Choice":
                for selected_feature in feature.get("data", {}).get("selected", []):
                    if selected_feature.get("name") == "Grounded":
                        base_stability += 1
            elif feature.get("name") == "Grounded":
                base_stability += 1

    # NOTE: Stamina is always 20 for level 1 heroes in Foundry
    # Kit bonuses are applied separately during prepareBaseData
    # Don't override the base stamina value

    # Basic Information
    foundry_character = {
        "name": character_data.get("name"),
        "type": "hero",
        "img": "icons/svg/mystery-man.svg",
        "system": {
            "stamina": {
                "value": base_stamina
                - character_data.get("state", {}).get("staminaDamage", 0),
                "temporary": character_data.get("state", {}).get("staminaTemp", 0),
            },
            "characteristics": {
                "might": {"value": 0},
                "agility": {"value": 0},
                "reason": {"value": 0},
                "intuition": {"value": 0},
                "presence": {"value": 0},
            },
            "combat": {
                "save": {"threshold": 6, "bonus": ""},
                "size": {"value": 1, "letter": "M"},
                "stability": base_stability,
                "turns": 1,
            },
            "biography": {
                "value": "",
                "director": "",
                "languages": [],
                "height": {"units": "in", "value": None},
                "weight": {"units": "lb", "value": None},
            },
            "movement": {"value": 6, "types": ["walk"], "hover": False, "disengage": 1},
            "damage": {
                "immunities": {
                    "all": 0,
                    "acid": 0,
                    "cold": 0,
                    "corruption": 0,
                    "fire": 0,
                    "holy": 0,
                    "lightning": 0,
                    "poison": 0,
                    "psychic": 0,
                    "sonic": 0,
                },
                "weaknesses": {
                    "all": 0,
                    "acid": 0,
                    "cold": 0,
                    "corruption": 0,
                    "fire": 0,
                    "holy": 0,
                    "lightning": 0,
                    "poison": 0,
                    "psychic": 0,
                    "sonic": 0,
                },
            },
            "recoveries": {"value": base_recoveries, "max": 0},
            "hero": {
                "primary": {"value": 0},
                "epic": {"value": 0},
                "surges": character_data.get("state", {}).get("surges", 0),
                "xp": character_data.get("state", {}).get("xp", 0),
                "victories": character_data.get("state", {}).get("victories", 0),
                "renown": character_data.get("state", {}).get("renown", 0),
                "wealth": character_data.get("state", {}).get("wealth", 0),
                "skills": [],
                "preferredKit": None,
            },
        },
        "items": [],
    }

    # Movement calculation: extract from ancestry Speed features
    movement_speed = 5  # Default base movement for all heroes
    kit_speed_bonus = 0
    ancestry_speed = None

    # Process Ancestry Features for Speed
    ancestry = character_data.get("ancestry")
    if ancestry:
        for feature in ancestry.get("features", []):
            if feature.get("type") == "Choice":
                for selected_feature in feature.get("data", {}).get("selected", []):
                    if selected_feature.get("type") == "Speed":
                        ancestry_speed = selected_feature.get("data", {}).get("speed")
                        if ancestry_speed:
                            movement_speed = ancestry_speed
            elif feature.get("type") == "Speed":
                ancestry_speed = feature.get("data", {}).get("speed")
                if ancestry_speed:
                    movement_speed = ancestry_speed

    # Process Class Kits for Speed bonus
    for level_data in class_data.get("featuresByLevel", []):
        for feature in level_data.get("features", []):
            if feature.get("type") == "Kit" and "selected" in feature.get("data", {}):
                for kit in feature.get("data", {}).get("selected", []):
                    kit_speed = kit.get("speed", 0)
                    kit_speed_bonus = max(kit_speed_bonus, kit_speed)

    movement_speed += kit_speed_bonus

    # Update Foundry character movement
    foundry_character["system"]["movement"]["value"] = movement_speed

    print(
        f"Calculated Movement Speed: {movement_speed} (ancestry {ancestry_speed or 'base 5'} + kit bonus {kit_speed_bonus})"
    )

    # Characteristics - prioritize explicit values over calculated ones
    char_values = {"might": 0, "agility": 0, "reason": 0, "intuition": 0, "presence": 0}

    # First, check if there are explicit characteristic values in the class
    if "characteristics" in class_data:
        # Use explicit characteristic values if they exist
        for char in class_data["characteristics"]:
            char_name = char.get("characteristic", "").lower()
            char_value = char.get("value", 0)
            if char_name in char_values:
                char_values[char_name] = char_value
    else:
        # Fall back to calculating from class structure (for older formats)
        # Set base characteristics from class primary characteristics
        primary_chars = class_data.get("primaryCharacteristics", [])

        # Primary characteristics start at 2
        for char in primary_chars:
            if char.lower() in char_values:
                char_values[char.lower()] = 2

        # Apply characteristic bonuses from features
        if class_data.get("featuresByLevel"):
            character_level = class_data.get(
                "level", 1
            )  # Default to level 1 if not specified

            for level_data in class_data["featuresByLevel"]:
                level_num = level_data.get("level", 1)
                # Only apply features up to the character's level
                if level_num <= character_level:
                    for feature in level_data.get("features", []):
                        if feature.get("type") == "Characteristic Bonus":
                            char_name = (
                                feature.get("data", {})
                                .get("characteristic", "")
                                .lower()
                            )
                            value = feature.get("data", {}).get("value", 0)
                            if char_name in char_values:
                                char_values[char_name] += value

    # Set the final characteristic values
    for char_name, value in char_values.items():
        if char_name in foundry_character["system"]["characteristics"]:
            foundry_character["system"]["characteristics"][char_name]["value"] = value

    # Ancestry
    ancestry = character_data.get("ancestry")
    if ancestry:
        item = _convert_feature(ancestry, "ancestry", compendium_items)
        if item:
            foundry_character["items"].append(item)

        # Process ancestry advancements to add granted items (traits/abilities)
        # Only process if the ancestry doesn't have features that are already handled separately
        # This prevents duplicate items from being added
        if (
            "system" in item
            and "advancements" in item["system"]
            and not ancestry.get("features")
        ):
            for advancement_id, advancement in item["system"]["advancements"].items():
                if advancement.get("type") == "itemGrant" and "pool" in advancement:
                    # Add items from the ancestry's advancement pool
                    for pool_item in advancement["pool"]:
                        if "uuid" in pool_item:
                            uuid_target = pool_item["uuid"].split(".")[-1]
                            # Look up the item in compendium by UUID
                            added_item = None
                            for comp_item in compendium_items.values():
                                if (
                                    comp_item.get("_id") == uuid_target
                                    or comp_item.get("flags", {})
                                    .get("draw-steel", {})
                                    .get("sourceId")
                                    == pool_item["uuid"]
                                ):
                                    item_copy = comp_item.copy()
                                    foundry_character["items"].append(item_copy)
                                    added_item = item_copy
                                    break

                            # If we added an item, process its advancements too
                            if added_item:
                                _process_item_advancements(
                                    added_item, compendium_items, foundry_character
                                )

        for feature in ancestry.get("features", []):
            if feature.get("type") == "Choice":
                for selected_feature in feature.get("data", {}).get("selected", []):
                    # Ancestry features should always be ancestryTrait, even if they contain abilities
                    # The abilities will be granted through the trait's advancements
                    selected_type = selected_feature.get("type", "ancestryTrait")
                    item_type = "ancestryTrait"

                    # Try to find the item in compendium first (to get advancements)
                    item_name = selected_feature.get("name")
                    item = None
                    for comp_item in compendium_items.values():
                        if (
                            comp_item.get("name") == item_name
                            and comp_item.get("type") == item_type
                        ):
                            item = comp_item.copy()
                            break

                    # If not found in compendium, create from feature data
                    if not item:
                        item = _convert_feature(
                            selected_feature, item_type, compendium_items
                        )

                    if item:
                        # Check for duplicates before adding
                        is_duplicate = any(
                            existing.get("name") == item.get("name")
                            and existing.get("type") == item.get("type")
                            for existing in foundry_character["items"]
                        )
                        if not is_duplicate:
                            foundry_character["items"].append(item)

                        # Process selected feature advancements to add granted abilities
                        if "system" in item and "advancements" in item["system"]:
                            for advancement_id, advancement in item["system"][
                                "advancements"
                            ].items():
                                if (
                                    advancement.get("type") == "itemGrant"
                                    and "pool" in advancement
                                ):
                                    # Add abilities from the feature's advancement pool
                                    for pool_item in advancement["pool"]:
                                        if "uuid" in pool_item:
                                            # Look up the ability in compendium by UUID
                                            for comp_item in compendium_items.values():
                                                if (
                                                    comp_item.get("_id")
                                                    == pool_item["uuid"].split(".")[-1]
                                                    or comp_item.get("flags", {})
                                                    .get("draw-steel", {})
                                                    .get("sourceId")
                                                    == pool_item["uuid"]
                                                ):
                                                    ability_copy = comp_item.copy()
                                                    ability_copy["type"] = "ability"
                                                    # Ensure action type is lowercase for Foundry compatibility
                                                    if (
                                                        "system" in ability_copy
                                                        and "type"
                                                        in ability_copy["system"]
                                                    ):
                                                        current_type = ability_copy[
                                                            "system"
                                                        ]["type"]
                                                        if isinstance(
                                                            current_type, str
                                                        ):
                                                            ability_copy["system"][
                                                                "type"
                                                            ] = current_type.lower()
                                                    foundry_character["items"].append(
                                                        ability_copy
                                                    )
                                                    break

                    # Handle nested Choice features (e.g., Psionic Gift -> Psionic Bolt)
                    if (
                        selected_type == "Choice"
                        and "data" in selected_feature
                        and "selected" in selected_feature.get("data", {})
                    ):
                        # For nested Choice features, we need to:
                        # 1. Add the parent feature as a trait from compendium (to get advancements)
                        # 2. Process its advancement to grant the selected ability
                        parent_name = selected_feature.get("name")

                        # Look up the parent trait in compendium
                        parent_trait = None
                        for comp_item in compendium_items.values():
                            if (
                                comp_item.get("name") == parent_name
                                and comp_item.get("type") == "ancestryTrait"
                            ):
                                parent_trait = comp_item.copy()
                                break

                        if parent_trait:
                            # Check for duplicates before adding the trait
                            is_duplicate = any(
                                existing.get("name") == parent_trait.get("name")
                                and existing.get("type") == parent_trait.get("type")
                                for existing in foundry_character["items"]
                            )
                            if not is_duplicate:
                                foundry_character["items"].append(parent_trait)

                                # Process the trait's advancement to grant selected abilities
                                _process_choice_advancement(
                                    parent_trait,
                                    selected_feature.get("data", {}).get(
                                        "selected", []
                                    ),
                                    compendium_items,
                                    foundry_character,
                                )
            else:
                # For non-Choice features, try to use compendium version to get advancements
                feature_name = feature.get("name")
                item = None
                for comp_item in compendium_items.values():
                    if (
                        comp_item.get("name") == feature_name
                        and comp_item.get("type") == "ancestryTrait"
                    ):
                        item = comp_item.copy()
                        break

                # If not found in compendium, create from feature data
                if not item:
                    item = _convert_feature(feature, "ancestryTrait", compendium_items)

                if item:
                    # Check for duplicates before adding
                    is_duplicate = any(
                        existing.get("name") == item.get("name")
                        and existing.get("type") == item.get("type")
                        for existing in foundry_character["items"]
                    )
                    if not is_duplicate:
                        foundry_character["items"].append(item)

                        # Process ancestry trait advancements to add granted abilities
                        _process_item_advancements(
                            item, compendium_items, foundry_character
                        )

    # Culture
    culture = character_data.get("culture")
    if culture:
        item = _convert_feature(culture, "culture", compendium_items)
        if item:
            foundry_character["items"].append(item)

    # Class
    hero_class = character_data.get("class")
    if hero_class:
        item = _convert_feature(hero_class, "class", compendium_items)
        if item:
            # Add the level to the class item system
            if "system" not in item:
                item["system"] = {}
            item["system"]["level"] = hero_class.get("level", 1)
        if item:
            foundry_character["items"].append(item)
        # Process class features with level filtering
        for level_data in hero_class.get("featuresByLevel", []):
            level_num = level_data.get("level", 1)
            # Only process features up to the character's level
            if level_num <= character_level:
                for feature in level_data.get("features", []):
                    # Skip placeholder features that have no actual content selected
                    feature_type = feature.get("type", "")
                    feature_data = feature.get("data", {})

                    # Always skip Skill Choice and Language Choice features - they're handled separately
                    if feature_type in ["Skill Choice", "Language Choice"]:
                        continue

                    # Skip Class Ability features - they're meta containers, the actual abilities are handled separately
                    if feature_type == "Class Ability":
                        continue

                    # Handle Domain Feature by extracting selected abilities
                    if feature_type == "Domain Feature":
                        selected_items = feature_data.get("selected", [])
                        for selected_item in selected_items:
                            item = _convert_feature(
                                selected_item, "ability", compendium_items
                            )
                            if item:
                                foundry_character["items"].append(item)
                        continue

                    # Skip other framework/container features that don't represent actual content
                    feature_name = feature.get("name", "")
                    skip_patterns = [
                        "pt Ability",
                        "Signature Ability",
                        "Kit",
                        "1st-Level",
                        "4th-Level",
                        "5th-Level",
                        "7th-Level",
                        "9th-Level",
                    ]
                    if any(pattern in feature_name for pattern in skip_patterns):
                        continue

                    # Handle Perk and Project features by extracting their selected items
                    if feature_type in ["Perk", "Project"]:
                        selected_items = feature_data.get("selected", [])
                        for selected_item in selected_items:
                            item = _convert_feature(
                                selected_item, feature_type.lower(), compendium_items
                            )
                            if item:
                                foundry_character["items"].append(item)
                        continue

                    if feature.get("type") == "Choice":
                        for selected_feature in feature.get("data", {}).get(
                            "selected", []
                        ):
                            selected_type = selected_feature.get("type", "")
                            # Skip bonus-type features that are just modifiers
                            if selected_type in [
                                "Bonus",
                                "Ability Damage",
                                "Characteristic Bonus",
                            ]:
                                continue
                            item_type = (
                                "ability" if selected_type == "Ability" else "feature"
                            )

                            item = _convert_feature(
                                selected_feature, item_type, compendium_items
                            )
                            if item:
                                foundry_character["items"].append(item)
                        continue
                    elif feature_type == "Multiple Features":
                        # Process Multiple Features to extract nested abilities
                        nested_features = feature_data.get("features", [])
                        for nested_feature in nested_features:
                            if nested_feature.get("type") == "Ability":
                                # Extract the actual ability data from nested structure
                                # Create a proper feature structure that matches what _convert_feature expects
                                ability_data = nested_feature.get("data", {}).get(
                                    "ability", nested_feature
                                )
                                # Reconstruct the feature structure with proper data nesting
                                reconstructed_feature = {
                                    "name": ability_data.get("name"),
                                    "description": ability_data.get("description"),
                                    "data": {"ability": ability_data},
                                }
                                item = _convert_feature(
                                    reconstructed_feature, "ability", compendium_items
                                )
                                if item:
                                    foundry_character["items"].append(item)
                        continue
                    elif feature_type not in [
                        "Bonus",
                        "Characteristic Bonus",
                        "Heroic Resource Gain",
                    ]:
                        # Process non-placeholder feature types (including Heroic Resource, Text, Ability, etc.)
                        # Use the feature's actual type for conversion
                        item_type = (
                            "ability" if feature_type == "Ability" else "feature"
                        )

                        # For Ability type, extract the nested ability data
                        if (
                            feature_type == "Ability"
                            and "data" in feature
                            and "ability" in feature["data"]
                        ):
                            feature_to_convert = feature["data"]["ability"]
                        else:
                            feature_to_convert = feature

                        item = _convert_feature(
                            feature_to_convert, item_type, compendium_items
                        )
                        if item:
                            foundry_character["items"].append(item)

    # Career
    career = character_data.get("career")
    if career:
        item = _convert_feature(career, "career", compendium_items)
        if item:
            foundry_character["items"].append(item)
        for feature in career.get("features", []):
            feature_name = feature.get("name", "")
            feature_type = feature.get("type", "")

            # Skip framework/placeholder features
            if feature_type in ["Skill Choice", "Bonus", "Characteristic Bonus"]:
                continue

            # Handle Perk and Project features by extracting their selected items
            if feature_type in ["Perk", "Project"]:
                selected_items = feature.get("data", {}).get("selected", [])
                for selected_item in selected_items:
                    item = _convert_feature(
                        selected_item, feature_type.lower(), compendium_items
                    )
                    if item:
                        foundry_character["items"].append(item)
                continue

            skip_patterns = ["Skill", "Language", "Feature"]
            if any(pattern in feature_name for pattern in skip_patterns):
                continue

            processed_feature = _convert_feature(feature, "feature", compendium_items)
            if processed_feature:
                foundry_character["items"].append(processed_feature)

    # Collect selected kits that will be processed later
    selected_kits = []

    # Subclass items (only include selected subclass)
    subclasses = class_data.get("subclasses", [])
    for subclass in subclasses:
        if subclass.get("selected", False):
            item = _convert_feature(subclass, "subclass", compendium_items)
            if item:
                foundry_character["items"].append(item)

    # Subclass features (including skills) - only for selected subclass
    subclasses = class_data.get("subclasses", [])
    for subclass in subclasses:
        if not subclass.get("selected", False):
            continue
        for level_data in subclass.get("featuresByLevel", []):
            level_num = level_data.get("level", 1)
            if level_num <= character_level:
                for feature in level_data.get("features", []):
                    feature_type = feature.get("type", "")

                    # Skip Skill Choice - will be processed by _process_skills_from_advancements
                    if feature_type == "Skill Choice":
                        continue

                    # Process Kit features to get kit abilities
                    if feature_type == "Kit":
                        # Process the selected kits and their abilities
                        selected_kits.extend(feature_data.get("selected", []))
                        continue

                    # Process Multiple Features to extract nested abilities
                    if feature_type == "Multiple Features":
                        nested_features = feature_data.get("features", [])
                        for nested_feature in nested_features:
                            if nested_feature.get("type") == "Ability":
                                # Extract the actual ability data from nested structure
                                # Create a proper feature structure that matches what _convert_feature expects
                                ability_data = nested_feature.get("data", {}).get(
                                    "ability", nested_feature
                                )
                                # Reconstruct the feature structure with proper data nesting
                                reconstructed_feature = {
                                    "name": ability_data.get("name"),
                                    "description": ability_data.get("description"),
                                    "data": {"ability": ability_data},
                                }
                                item = _convert_feature(
                                    reconstructed_feature, "ability", compendium_items
                                )
                                if item:
                                    foundry_character["items"].append(item)
                        continue

                    # Skip other placeholder/container features
                    if feature_type in ["Perk", "Domain Feature", "Class Ability"]:
                        continue

                    # Handle Choice type features by extracting selected items
                    if feature_type == "Choice":
                        for selected_feature in feature.get("data", {}).get(
                            "selected", []
                        ):
                            selected_type = selected_feature.get("type", "")
                            # Skip bonus-type features that are just modifiers
                            if selected_type in [
                                "Bonus",
                                "Ability Damage",
                                "Characteristic Bonus",
                            ]:
                                continue
                            item_type = (
                                "ability" if selected_type == "Ability" else "feature"
                            )
                            item = _convert_feature(
                                selected_feature, item_type, compendium_items
                            )
                            if item:
                                foundry_character["items"].append(item)
                        continue

                    # Process other features normally (Heroic Resource should be processed as feature, Heroic Resource Gain should be skipped)
                    if feature_type not in [
                        "Bonus",
                        "Characteristic Bonus",
                        "Heroic Resource Gain",
                    ]:
                        # Use the feature's actual type for conversion
                        item_type = (
                            "ability" if feature_type == "Ability" else "feature"
                        )

                        # For Ability type, extract the nested ability data
                        if (
                            feature_type == "Ability"
                            and "data" in feature
                            and "ability" in feature["data"]
                        ):
                            feature_to_convert = feature["data"]["ability"]
                        else:
                            feature_to_convert = feature

                        item = _convert_feature(
                            feature_to_convert, item_type, compendium_items
                        )
                        if item:
                            foundry_character["items"].append(item)

    # Skills from characteristics section
    if "characteristics" in class_data:
        skills_list = []
        for char in class_data["characteristics"]:
            if "skills" in char:
                skills_list.extend(
                    [_normalize_skill_name(s) for s in char.get("skills", [])]
                )
        if skills_list:
            # Add skills to hero section
            foundry_character["system"]["hero"]["skills"] = skills_list

    # Complication
    complication = character_data.get("complication")
    if complication and complication != "null":
        item = _convert_feature(complication, "complication", compendium_items)
        if item:
            foundry_character["items"].append(item)

    # Top-level features
    for feature in character_data.get("features", []):
        feature_type = feature.get("type", "")
        # Skip placeholder/framework features
        if feature_type in ["Language Choice", "Skill Choice"]:
            continue
        item = _convert_feature(feature, "feature", compendium_items)
        if item:
            foundry_character["items"].append(item)

    # Collect selected ability IDs from all level features
    selected_ability_ids = set()

    for level_data in class_data.get("featuresByLevel", []):
        level_num = level_data.get("level", 1)
        # Only process features up to the character's level
        if level_num <= character_level:
            for feature in level_data.get("features", []):
                # Collect selected ability IDs
                if feature.get(
                    "type"
                ) == "Class Ability" and "selectedIDs" in feature.get("data", {}):
                    selected_ability_ids.update(
                        feature.get("data", {}).get("selectedIDs", [])
                    )
                # Collect selected kits (from features with type "Kit" that have selected kits)
                elif feature.get("type") == "Kit" and "selected" in feature.get(
                    "data", {}
                ):
                    selected_kits.extend(feature.get("data", {}).get("selected", []))

    # Kits - process selected kits from class features
    for kit in selected_kits:
        kit_item = _convert_feature(kit, "kit", compendium_items)
        if kit_item:
            foundry_character["items"].append(kit_item)

            # Process kit advancements to add kit-specific abilities
            if "system" in kit_item and "advancements" in kit_item["system"]:
                for advancement_id, advancement in kit_item["system"][
                    "advancements"
                ].items():
                    if advancement.get("type") == "itemGrant" and "pool" in advancement:
                        # Add abilities from the kit's advancement pool
                        for pool_item in advancement["pool"]:
                            if "uuid" in pool_item:
                                # Look up the ability in compendium by UUID
                                for comp_item in compendium_items.values():
                                    if (
                                        comp_item.get("_id")
                                        == pool_item["uuid"].split(".")[-1]
                                        or comp_item.get("flags", {})
                                        .get("draw-steel", {})
                                        .get("sourceId")
                                        == pool_item["uuid"]
                                    ):
                                        ability_copy = comp_item.copy()
                                        ability_copy["type"] = "ability"
                                        # Ensure action type is lowercase for Foundry compatibility
                                        if (
                                            "system" in ability_copy
                                            and "type" in ability_copy["system"]
                                        ):
                                            current_type = ability_copy["system"][
                                                "type"
                                            ]
                                            if isinstance(current_type, str):
                                                ability_copy["system"]["type"] = (
                                                    current_type.lower()
                                                )
                                        foundry_character["items"].append(ability_copy)
                                        break

    # Abilities - include basic abilities plus level-appropriate class abilities
    from converter.ability_converter import AbilityConverter

    # Add basic abilities that all heroes have regardless of level
    # These are fundamental abilities from the Basic_Abilities folder
    basic_dsids = {
        "aid-attack",
        "catch-breath",
        "charge",
        "defend",
        "escape-grab",
        "grab",
        "heal",
        "knockback",
        "melee-free-strike",
        "ranged-free-strike",
        "stand-up",
        "advance",
        "disengage",
        "ride",
    }

    # Always include basic abilities - these are fundamental to all characters
    for dsid, compendium_item in compendium_items.items():
        if dsid in basic_dsids and compendium_item.get("type") == "ability":
            ability_copy = compendium_item.copy()
            # Ensure action type is lowercase for Foundry compatibility
            if "system" in ability_copy and "type" in ability_copy["system"]:
                current_type = ability_copy["system"]["type"]
                if isinstance(current_type, str):
                    ability_copy["system"]["type"] = current_type.lower()
            foundry_character["items"].append(ability_copy)

    # Then convert and add class abilities with level filtering
    class_abilities = AbilityConverter.convert_class_abilities(
        character_data, character_level, compendium_items
    )
    foundry_character["items"].extend(class_abilities)

    # Log ability conversion summary
    if class_abilities:
        all_abilities = hero_class.get("abilities", [])
        validation = AbilityConverter.validate_ability_conversion(
            all_abilities, class_abilities, character_level
        )
        summary = AbilityConverter.get_ability_conversion_summary(validation)
        print(f"Ability conversion: {summary}")

    # Inventory
    for item in character_data.get("state", {}).get("inventory", []):
        foundry_character["items"].append(
            _convert_feature(item, "treasure", compendium_items)
        )

    # Post-processing: Extract skills from item advancements
    _populate_advancement_selections(
        foundry_character, character_data, compendium_items
    )
    _process_skills_from_advancements(foundry_character, character_data)
    _post_process_languages_and_culture(foundry_character, character_data)
    _fix_ability_types(foundry_character)

    return foundry_character


def _normalize_skill_name(skill_name):
    """Convert skill name from Forgesteel format (Title Case) to Foundry format (camelCase)."""
    if not skill_name:
        return skill_name

    # Special cases
    special_map = {
        "Read Person": "readPerson",
        "Aid Attack": "aidAttack",
        "Catch Breath": "catchBreath",
        "Escape Grab": "escapeGrab",
        "Melee Free Strike": "meleeFreeStrike",
        "Ranged Free Strike": "rangedFreeStrike",
        "Stand Up": "standUp",
        "Handle Animals": "handleAnimals",
    }

    if skill_name in special_map:
        return special_map[skill_name]

    # General case: convert to camelCase
    # Split by spaces and capitalize each word except the first
    words = skill_name.split()
    if not words:
        return skill_name

    # First word is lowercase, rest are capitalized
    first_word = words[0].lower()
    other_words = [word.capitalize() for word in words[1:]]

    return first_word + "".join(other_words)


def _process_item_advancements(item, compendium_items, foundry_character):
    """Process advancements for an item to add granted abilities."""
    if "system" not in item or "advancements" not in item["system"]:
        return

    for advancement_id, advancement in item["system"]["advancements"].items():
        if advancement.get("type") == "itemGrant" and "pool" in advancement:
            # Add abilities from the item's advancement pool
            for pool_item in advancement["pool"]:
                if "uuid" in pool_item:
                    uuid_target = pool_item["uuid"].split(".")[-1]
                    # Look up the ability in compendium by UUID
                    for comp_item in compendium_items.values():
                        if (
                            comp_item.get("_id") == uuid_target
                            or comp_item.get("flags", {})
                            .get("draw-steel", {})
                            .get("sourceId")
                            == pool_item["uuid"]
                        ):
                            ability_copy = comp_item.copy()
                            ability_copy["type"] = "ability"
                            # Ensure action type is lowercase for Foundry compatibility
                            if (
                                "system" in ability_copy
                                and "type" in ability_copy["system"]
                            ):
                                current_type = ability_copy["system"]["type"]
                                if isinstance(current_type, str):
                                    ability_copy["system"]["type"] = (
                                        current_type.lower()
                                    )
                            foundry_character["items"].append(ability_copy)
                            break
                    else:
                        # If not found by _id, search all compendium items for matching _id
                        # This handles cases where items have same _dsid but different _id
                        for root, dirs, files in os.walk("draw_steel_repo/src/packs"):
                            for file in files:
                                if file.endswith(".json") and uuid_target in file:
                                    file_path = os.path.join(root, file)
                                    try:
                                        with open(
                                            file_path, "r", encoding="utf-8"
                                        ) as f:
                                            direct_item = json.load(f)
                                            if direct_item.get("_id") == uuid_target:
                                                ability_copy = direct_item.copy()
                                                ability_copy["type"] = "ability"
                                                # Ensure action type is lowercase for Foundry compatibility
                                                if (
                                                    "system" in ability_copy
                                                    and "type" in ability_copy["system"]
                                                ):
                                                    current_type = ability_copy[
                                                        "system"
                                                    ]["type"]
                                                    if isinstance(current_type, str):
                                                        ability_copy["system"][
                                                            "type"
                                                        ] = current_type.lower()
                                                foundry_character["items"].append(
                                                    ability_copy
                                                )
                                                break
                                    except:
                                        pass
                            if any(
                                item.get("_id") == uuid_target
                                for item in foundry_character["items"][-1:]
                            ):
                                break


def _process_choice_advancement(
    trait_item, selected_items, compendium_items, foundry_character
):
    """Process a trait's choice advancement to grant only selected items."""
    if "system" not in trait_item or "advancements" not in trait_item["system"]:
        return

    # Get the names of selected items
    selected_names = [item.get("name", "") for item in selected_items]

    for advancement_id, advancement in trait_item["system"]["advancements"].items():
        if advancement.get("type") == "itemGrant" and "pool" in advancement:
            # Only add items that were selected
            for pool_item in advancement["pool"]:
                if "uuid" in pool_item:
                    uuid_target = pool_item["uuid"].split(".")[-1]

                    # Look up the item to get its name
                    pool_item_name = None
                    for comp_item in compendium_items.values():
                        if comp_item.get("_id") == uuid_target:
                            pool_item_name = comp_item.get("name", "")
                            break

                    # Skip if this item wasn't selected
                    if pool_item_name not in selected_names:
                        continue

                    # Add the selected item
                    for comp_item in compendium_items.values():
                        if (
                            comp_item.get("_id") == uuid_target
                            or comp_item.get("flags", {})
                            .get("draw-steel", {})
                            .get("sourceId")
                            == pool_item["uuid"]
                        ):
                            item_copy = comp_item.copy()
                            item_copy["type"] = (
                                "ability"  # Ensure it's marked as ability
                            )
                            # Ensure action type is lowercase for Foundry compatibility
                            if "system" in item_copy and "type" in item_copy["system"]:
                                current_type = item_copy["system"]["type"]
                                if isinstance(current_type, str):
                                    item_copy["system"]["type"] = current_type.lower()
                            foundry_character["items"].append(item_copy)
                            break


def _populate_advancement_selections(character_data, source_data, compendium_items):
    """Populate advancement selections in flags for skills and languages from origin items."""
    # Note: Actor-level flags remain empty - all selections are stored at the item level only

    # Collect all skill selections from Forgesteel character
    skill_selections = {}  # Maps advancement descriptions to selected skills

    # Helper function to extract skill names from Forgesteel Skill Choice features
    def collect_skills_from_features(features_list):
        selected_skills = []
        if not features_list:
            return selected_skills
        for feature in features_list:
            if feature.get("type") == "Skill Choice":
                skills = feature.get("data", {}).get("selected", [])
                if skills:
                    # Normalize skill names to camelCase format used by Foundry
                    selected_skills.extend([_normalize_skill_name(s) for s in skills])
            elif feature.get("type") == "Multiple Features":
                for sub_feature in feature.get("data", {}).get("features", []):
                    if sub_feature.get("type") == "Skill Choice":
                        skills = sub_feature.get("data", {}).get("selected", [])
                        if skills:
                            selected_skills.extend(
                                [_normalize_skill_name(s) for s in skills]
                            )
        return selected_skills

    # Collect skills from all sources
    all_selected_skills = set()

    # From ancestry
    ancestry = source_data.get("ancestry", {})
    if ancestry:
        all_selected_skills.update(
            collect_skills_from_features(ancestry.get("features", []))
        )

    # From culture sections
    culture = source_data.get("culture", {})
    if culture:
        for section_name in ["language", "environment", "organization", "upbringing"]:
            if section_name in culture:
                section = culture[section_name]
                if section.get("type") == "Skill Choice":
                    skills = section.get("data", {}).get("selected", [])
                    if skills:
                        all_selected_skills.update(
                            [_normalize_skill_name(s) for s in skills]
                        )

    # From career
    career = source_data.get("career", {})
    if career:
        all_selected_skills.update(
            collect_skills_from_features(career.get("features", []))
        )

    # From class
    class_data = source_data.get("class", {})
    if class_data:
        for level_data in class_data.get("featuresByLevel", []):
            all_selected_skills.update(
                collect_skills_from_features(level_data.get("features", []))
            )

    # From selected subclass
    for subclass in class_data.get("subclasses", []):
        if subclass.get("selected", False):
            for level_data in subclass.get("featuresByLevel", []):
                all_selected_skills.update(
                    collect_skills_from_features(level_data.get("features", []))
                )

    # Now go through character items and populate advancement selections
    for item in character_data.get("items", []):
        if item.get("type") not in [
            "ancestry",
            "culture",
            "career",
            "class",
            "subclass",
        ]:
            continue

        if "system" not in item or "advancements" not in item["system"]:
            continue

        # Ensure item has flags structure for storing advancement selections
        if "flags" not in item:
            item["flags"] = {}
        if "draw-steel" not in item["flags"]:
            item["flags"]["draw-steel"] = {}
        if "advancement" not in item["flags"]["draw-steel"]:
            item["flags"]["draw-steel"]["advancement"] = {}

        # For each advancement in the item
        for advancement_id, advancement in item["system"]["advancements"].items():
            advancement_type = advancement.get("type")

            # Skip non-skill, non-language advancements
            if advancement_type not in ["skill", "language"]:
                continue

            # Handle skill advancements
            if advancement_type == "skill":
                # Check what skills this advancement allows
                skills_in_adv = advancement.get("skills", {})
                choices = skills_in_adv.get("choices", [])
                groups = skills_in_adv.get("groups", [])

                # If it has direct choices, select the ones that were selected in Forgesteel
                if choices:
                    selected_from_choices = []
                    for choice in choices:
                        if choice in all_selected_skills:
                            selected_from_choices.append(choice)

                    if selected_from_choices:
                        selection_data = {"selected": selected_from_choices}
                        # Store at item level only (actor level should remain empty)
                        item["flags"]["draw-steel"]["advancement"][advancement_id] = (
                            selection_data
                        )

                # If it has groups, match selected skills against group members
                if groups:
                    selected_from_groups = []

                    # Complete skill-to-group mapping from Draw Steel config
                    skill_groups_map = {
                        "alchemy": "crafting",
                        "alertness": "intrigue",
                        "architecture": "crafting",
                        "blacksmithing": "crafting",
                        "brag": "interpersonal",
                        "carpentry": "crafting",
                        "climb": "exploration",
                        "concealObject": "intrigue",
                        "cooking": "crafting",
                        "criminalUnderworld": "lore",
                        "culture": "lore",
                        "disguise": "intrigue",
                        "drive": "exploration",
                        "eavesdrop": "intrigue",
                        "empathize": "interpersonal",
                        "endurance": "exploration",
                        "escapeArtist": "intrigue",
                        "fletching": "crafting",
                        "flirt": "interpersonal",
                        "forgery": "crafting",
                        "gamble": "interpersonal",
                        "gymnastics": "exploration",
                        "handleAnimals": "interpersonal",
                        "heal": "exploration",
                        "hide": "intrigue",
                        "history": "lore",
                        "interrogate": "interpersonal",
                        "intimidate": "interpersonal",
                        "jewelry": "crafting",
                        "jump": "exploration",
                        "lead": "interpersonal",
                        "lie": "interpersonal",
                        "lift": "exploration",
                        "magic": "lore",
                        "mechanics": "crafting",
                        "monsters": "lore",
                        "music": "interpersonal",
                        "nature": "lore",
                        "navigate": "exploration",
                        "perform": "interpersonal",
                        "persuade": "interpersonal",
                        "pickLock": "intrigue",
                        "pickPocket": "intrigue",
                        "psionics": "lore",
                        "readPerson": "interpersonal",
                        "religion": "lore",
                        "ride": "exploration",
                        "rumors": "lore",
                        "sabotage": "intrigue",
                        "search": "intrigue",
                        "sneak": "intrigue",
                        "society": "lore",
                        "strategy": "lore",
                        "swim": "exploration",
                        "tailoring": "crafting",
                        "timescape": "lore",
                        "track": "intrigue",
                    }

                    for skill in all_selected_skills:
                        skill_lower = skill.lower()
                        if skill_lower in skill_groups_map:
                            skill_group = skill_groups_map[skill_lower]
                            # If this skill's group is in the advancement's allowed groups, include it
                            if skill_group in groups:
                                selected_from_groups.append(skill)

                    if selected_from_groups:
                        selection_data = {"selected": selected_from_groups}
                        # Store at item level only (actor level should remain empty)
                        item["flags"]["draw-steel"]["advancement"][advancement_id] = (
                            selection_data
                        )

            # Handle language advancements
            elif advancement_type == "language":
                # For languages, collect from the appropriate source based on item type
                selected_languages = set()
                item_type = item.get("type")

                # Helper to collect languages from features
                def collect_languages_from_features(features_list):
                    langs = []
                    if not features_list:
                        return langs
                    for feature in features_list:
                        if feature.get("type") == "Language Choice":
                            feature_langs = feature.get("data", {}).get("selected", [])
                            if feature_langs:
                                langs.extend(
                                    [_normalize_skill_name(l) for l in feature_langs]
                                )
                    return langs

                # Only collect languages from the corresponding source for this item
                if item_type == "culture":
                    # Collect only from culture sections
                    culture = source_data.get("culture", {})
                    if culture:
                        for section_name in [
                            "language",
                            "environment",
                            "organization",
                            "upbringing",
                        ]:
                            if section_name in culture:
                                section = culture[section_name]
                                if section.get("type") == "Language Choice":
                                    langs = section.get("data", {}).get("selected", [])
                                    if langs:
                                        selected_languages.update(
                                            [_normalize_skill_name(l) for l in langs]
                                        )

                elif item_type == "career":
                    # Collect only from career
                    career = source_data.get("career", {})
                    if career:
                        selected_languages.update(
                            collect_languages_from_features(career.get("features", []))
                        )

                elif item_type == "class":
                    # Collect only from class
                    class_data = source_data.get("class", {})
                    if class_data:
                        for level_data in class_data.get("featuresByLevel", []):
                            selected_languages.update(
                                collect_languages_from_features(
                                    level_data.get("features", [])
                                )
                            )

                # Add selected languages to flags (only if this item's source had languages)
                if selected_languages:
                    selection_data = {"selected": sorted(list(selected_languages))}
                    # Store at item level only (actor level should remain empty)
                    item["flags"]["draw-steel"]["advancement"][advancement_id] = (
                        selection_data
                    )


def _process_skills_from_advancements(character_data, source_data):
    """Extract skills from source data and add to hero skills list."""
    collected_skills = []

    # Process top-level features for skills
    for feature in source_data.get("features", []):
        if feature.get("type") == "Skill Choice":
            skills = feature.get("data", {}).get("selected", [])
            if skills:
                collected_skills.extend([_normalize_skill_name(s) for s in skills])
        elif feature.get("type") == "Multiple Features":
            for sub_feature in feature.get("data", {}).get("features", []):
                if sub_feature.get("type") == "Skill Choice":
                    skills = sub_feature.get("data", {}).get("selected", [])
                    if skills:
                        collected_skills.extend(
                            [_normalize_skill_name(s) for s in skills]
                        )

    # Extract skills from culture sections (language, environment, organization, upbringing)
    culture = source_data.get("culture", {})
    if culture:
        for section_name in ["language", "environment", "organization", "upbringing"]:
            if section_name in culture:
                section = culture[section_name]
                if section.get("type") == "Skill Choice":
                    skills = section.get("data", {}).get("selected", [])
                    if skills:
                        collected_skills.extend(
                            [_normalize_skill_name(s) for s in skills]
                        )

    # Extract skills from subclass features (only selected subclass)
    class_data = source_data.get("class", {})
    character_level = class_data.get("level", 1)
    subclasses = class_data.get("subclasses", [])
    for subclass in subclasses:
        if not subclass.get("selected", False):
            continue
        for level_data in subclass.get("featuresByLevel", []):
            level_num = level_data.get("level", 1)
            if level_num <= character_level:
                for feature in level_data.get("features", []):
                    if feature.get("type") == "Skill Choice":
                        skills = feature.get("data", {}).get("selected", [])
                        if skills:
                            collected_skills.extend(
                                [_normalize_skill_name(s) for s in skills]
                            )
                    # Check for nested features (like Multiple Features)
                    elif feature.get("type") == "Multiple Features":
                        for sub_feature in feature.get("data", {}).get("features", []):
                            if sub_feature.get("type") == "Skill Choice":
                                skills = sub_feature.get("data", {}).get("selected", [])
                                if skills:
                                    collected_skills.extend(
                                        [_normalize_skill_name(s) for s in skills]
                                    )

    # Extract skills from source character data (ancestry, culture, career, class)
    for data_type in ["ancestry", "culture", "career", "class"]:
        if data_type in source_data:
            data_section = source_data[data_type]

            # For class, check featuresByLevel as well
            if data_type == "class":
                for level_data in data_section.get("featuresByLevel", []):
                    for feature in level_data.get("features", []):
                        if feature.get("type") == "Skill Choice":
                            skills = feature.get("data", {}).get("selected", [])
                            if skills:
                                collected_skills.extend(
                                    [_normalize_skill_name(s) for s in skills]
                                )
                        # Check for nested features (like Multiple Features)
                        elif feature.get("type") == "Multiple Features":
                            for sub_feature in feature.get("data", {}).get(
                                "features", []
                            ):
                                if sub_feature.get("type") == "Skill Choice":
                                    skills = sub_feature.get("data", {}).get(
                                        "selected", []
                                    )
                                    if skills:
                                        collected_skills.extend(
                                            [_normalize_skill_name(s) for s in skills]
                                        )
            else:
                # Check for skill features (including nested ones)
                for feature in data_section.get("features", []):
                    if feature.get("type") == "Skill Choice":
                        skills = feature.get("data", {}).get("selected", [])
                        if skills:
                            collected_skills.extend(
                                [_normalize_skill_name(s) for s in skills]
                            )
                    # Check for nested features (like Multiple Features)
                    elif feature.get("type") == "Multiple Features":
                        for sub_feature in feature.get("data", {}).get("features", []):
                            if sub_feature.get("type") == "Skill Choice":
                                skills = sub_feature.get("data", {}).get("selected", [])
                                if skills:
                                    collected_skills.extend(
                                        [_normalize_skill_name(s) for s in skills]
                                    )
                    # Check skill choices in characteristics
                if "characteristics" in data_section:
                    for char_feature in data_section["characteristics"]:
                        if "skills" in char_feature:
                            collected_skills.extend(
                                [
                                    _normalize_skill_name(s)
                                    for s in char_feature.get("skills", [])
                                ]
                            )
                # Check for direct skills array
                if "skills" in data_section:
                    collected_skills.extend(
                        [_normalize_skill_name(s) for s in data_section["skills"]]
                    )

    # Also check converted items for advancements (for compendium items)
    for item in character_data.get("items", []):
        if "system" in item and "advancements" in item["system"]:
            for advancement_id, advancement in item["system"]["advancements"].items():
                if advancement.get("type") == "skill":
                    # Check if there's a selected field
                    if "selected" in advancement:
                        collected_skills.extend(
                            [_normalize_skill_name(s) for s in advancement["selected"]]
                        )

    # Add skills to hero section (avoid duplicates)
    if collected_skills:
        existing_skills = character_data["system"]["hero"].get("skills", [])
        # Combine and deduplicate
        all_skills = list(dict.fromkeys(existing_skills + collected_skills))
        character_data["system"]["hero"]["skills"] = all_skills
    else:
        character_data["system"]["hero"]["skills"] = []


def _post_process_languages_and_culture(character_data, source_data):
    """Process languages from source data and ensure culture conversion."""
    languages = []

    # Extract languages from source character data (ancestry/career/culture)
    for data_section_name in ["ancestry", "culture", "career"]:
        data_section = source_data.get(data_section_name, {})

        # Check for language feature in "features" list
        for feature in data_section.get("features", []) or []:
            if feature.get("type") == "Language Choice":
                languages.extend(feature.get("data", {}).get("selected", []))

        # Check for languages directly in "language" field (e.g., in culture)
        if "language" in data_section and data_section["language"].get("selected"):
            languages.extend(data_section["language"].get("selected", []))

        # Check for languages in a top-level "languages" field (e.g., in culture)
        if "languages" in data_section and isinstance(data_section["languages"], list):
            languages.extend(data_section["languages"])

    # Extract languages from top-level features
    for feature in source_data.get("features", []) or []:
        if feature.get("type") == "Language Choice":
            languages.extend(feature.get("data", {}).get("selected", []))

    # Remove duplicates
    languages = list(dict.fromkeys(languages))

    # Note: Do NOT populate biography.languages - Foundry gets languages from advancement selections
    # Adding them here would cause duplicates when Foundry combines both sources
    character_data["system"]["biography"]["languages"] = []

    # Remove generic language items from the Foundry character's items list to avoid redundancy
    # This specifically targets "Language" features that are now handled in biography.
    items_to_keep = []
    for item in character_data.get("items", []):
        if not (item.get("type") == "feature" and "Language" in item.get("name", "")):
            items_to_keep.append(item)
    character_data["items"] = items_to_keep


def _fix_ability_types(character_data):
    """Fix classification of certain items as abilities instead of features."""
    # NOTE: Pattern-based classification removed - items should be correctly classified
    # based on their source type, not hardcoded name patterns

    for item in character_data.get("items", []):
        item_name = item.get("name", "")
        item_system = item.get("system", {})

        # Fix based on system type - triggered actions should be abilities
        if item.get("type") == "feature" and item_system.get("type") == "triggered":
            item["type"] = "ability"


if __name__ == "__main__":
    print("WARNING: DO NOT RUN mapper.py DIRECTLY!")
    print("This is an internal module. Use the main conversion script instead:")
    print("   python forgesteel_converter.py input.ds-hero output.json")
    print("See forgesteel_converter.py for proper usage instructions.")
    print(
        "If you need to debug mapper functionality, modify forgesteel_converter.py instead."
    )
    import sys

    sys.exit(1)
