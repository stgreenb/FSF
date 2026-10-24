"""
Multi-source character level detection with priority-based extraction.

This module implements robust level detection from multiple data sources
with comprehensive validation and error handling.
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class LevelDetector:
    """Priority-based character level detection with validation."""

    LEVEL_SOURCES = [
        ('character.level', 'Top-level character field'),
        ('class.level', 'Class-level field'),
        ('featuresByLevel', 'Calculated from features'),
    ]

    # Test cases from real character data
    TEST_CASES = [
        {
            'name': 'Keth/Earth Cries',
            'class_level': 1,
            'max_features_level': 10,
            'expected': 10,
            'reasoning': 'featuresByLevel shows actual progression'
        },
        {
            'name': 'VÀLM',
            'class_level': 6,
            'max_features_level': 10,
            'expected': 6,
            'reasoning': 'Class level indicates current character level'
        }
    ]

    @classmethod
    def detect_level(cls, character_data: Dict[str, Any]) -> int:
        """Extract character level from multiple sources with priority.

        Args:
            character_data: Character data dictionary

        Returns:
            Detected character level (1-20)
        """
        level = None
        source_used = None

        # Priority 1: Top-level character field
        if 'level' in character_data:
            try:
                level = int(character_data['level'])
                source_used = 'character.level'
                logger.debug(f"Found level {level} in character.level")
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid level format in character.level: {character_data['level']} - {e}")

        # Priority 2: Class-level field
        if level is None:
            class_data = character_data.get('class', {})
            if 'level' in class_data:
                try:
                    level = int(class_data['level'])
                    source_used = 'class.level'
                    logger.debug(f"Found level {level} in class.level")
                except (ValueError, TypeError) as e:
                    logger.warning(f"Invalid level format in class.level: {class_data['level']} - {e}")

        # Priority 3: Calculate from features
        if level is None:
            class_data = character_data.get('class', {})
            features_by_level = class_data.get('featuresByLevel', [])
            if features_by_level:
                try:
                    max_level = max(feature.get('level', 1) for feature in features_by_level)
                    level = int(max_level)
                    source_used = 'featuresByLevel'
                    logger.debug(f"Calculated level {level} from featuresByLevel")
                except (ValueError, TypeError) as e:
                    logger.warning(f"Failed to calculate level from featuresByLevel - {e}")

        # Validation and normalization
        if level is not None:
            # Ensure valid D&D level range
            original_level = level
            level = max(1, min(20, level))

            if original_level != level:
                logger.warning(f"Level {original_level} normalized to {level} (valid range: 1-20)")

            logger.info(f"Level {level} detected from {source_used}")
            return level

        # Default fallback
        logger.warning("No level detected, using default level 1")
        return 1

    @classmethod
    def normalize_level_format(cls, level_value: Any) -> Optional[int]:
        """Normalize various level formats to canonical integer.

        Args:
            level_value: Level value in various formats

        Returns:
            Normalized integer level or None if invalid
        """
        if isinstance(level_value, int):
            return level_value

        if isinstance(level_value, float):
            if level_value.is_integer():
                return int(level_value)
            else:
                logger.warning(f"Non-integer level value: {level_value}")
                return None

        if isinstance(level_value, str):
            # Handle formats like "level 5", "5th level", "Lvl 5"
            import re
            numbers = re.findall(r'\d+', level_value)
            if numbers:
                try:
                    return int(numbers[0])
                except ValueError:
                    logger.warning(f"Could not parse level from string: {level_value}")
                    return None

        logger.warning(f"Unrecognized level format: {level_value} (type: {type(level_value)})")
        return None

    @classmethod
    def validate_level_consistency(cls, character_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate level consistency across different sources.

        Args:
            character_data: Character data dictionary

        Returns:
            Dictionary with validation results and detected inconsistencies
        """
        levels_found = {}

        # Check all sources
        if 'level' in character_data:
            try:
                levels_found['character.level'] = int(character_data['level'])
            except (ValueError, TypeError):
                pass

        class_data = character_data.get('class', {})
        if 'level' in class_data:
            try:
                levels_found['class.level'] = int(class_data['level'])
            except (ValueError, TypeError):
                pass

        features_by_level = class_data.get('featuresByLevel', [])
        if features_by_level:
            try:
                max_feature_level = max(feature.get('level', 1) for feature in features_by_level)
                levels_found['featuresByLevel'] = int(max_feature_level)
            except (ValueError, TypeError):
                pass

        # Check for inconsistencies
        unique_levels = set(levels_found.values())
        detected_level = cls.detect_level(character_data)

        validation_result = {
            'levels_found': levels_found,
            'unique_levels': list(unique_levels),
            'detected_level': detected_level,
            'is_consistent': len(unique_levels) <= 1,
            'inconsistencies': []
        }

        # Report inconsistencies
        if not validation_result['is_consistent']:
            for source, level in levels_found.items():
                if level != detected_level:
                    validation_result['inconsistencies'].append({
                        'source': source,
                        'level': level,
                        'difference': level - detected_level
                    })

        return validation_result

    @classmethod
    def get_level_detection_summary(cls, character_data: Dict[str, Any]) -> str:
        """Get a human-readable summary of level detection.

        Args:
            character_data: Character data dictionary

        Returns:
            Formatted string describing level detection results
        """
        validation = cls.validate_level_consistency(character_data)
        detected = validation['detected_level']

        summary_parts = [f"Detected level: {detected}"]

        if validation['is_consistent']:
            summary_parts.append("Sources consistent")
        else:
            summary_parts.append("Sources inconsistent:")
            for inconsistency in validation['inconsistencies']:
                summary_parts.append(f"  - {inconsistency['source']}: {inconsistency['level']} ({inconsistency['difference']} difference)")

        return " | ".join(summary_parts)


def test_level_detection():
    """Run basic tests on level detection functionality."""
    # Test case 1: Keth/Earth Cries scenario
    keth_data = {
        'class': {
            'level': 1,
            'featuresByLevel': [
                {'level': 1, 'features': []},
                {'level': 2, 'features': []},
                {'level': 10, 'features': []}  # Max level 10
            ]
        }
    }

    # Test case 2: VÀLM scenario
    valm_data = {
        'class': {
            'level': 6,
            'featuresByLevel': [
                {'level': 1, 'features': []},
                {'level': 6, 'features': []},
                {'level': 10, 'features': []}  # Max level 10
            ]
        }
    }

    print("Running level detection tests...")

    keth_level = LevelDetector.detect_level(keth_data)
    print(f"Keth level: {keth_level} (expected: 1)")

    valm_level = LevelDetector.detect_level(valm_data)
    print(f"VÀLM level: {valm_level} (expected: 6)")

    # Test validation
    keth_validation = LevelDetector.validate_level_consistency(keth_data)
    print(f"Keth validation: {keth_validation['is_consistent']}")


if __name__ == "__main__":
    test_level_detection()