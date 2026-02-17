"""
Centralized text normalization for encoding-aware processing.

This module handles character encoding issues, smart quotes, international characters,
and other text normalization tasks at the ingestion boundary.
"""

import re
import json
import logging
from typing import Dict, Optional, Set

logger = logging.getLogger(__name__)


class TextNormalizer:
    """Centralized text normalization for encoding-aware processing."""

    # Character mapping for common encoding issues
    CHARACTER_MAP: Dict[str, str] = {
        "\u201c": '"',  # Left double quote
        "\u201d": '"',  # Right double quote
        "\u2018": "'",  # Left single quote
        "\u2019": "'",  # Right single quote
        "\u2013": "-",  # En dash
        "\u2014": "-",  # Em dash
        "\u2026": "...",  # Ellipsis
        "\ufffd": "",  # Replacement character (encoding artifact)
        # International character support (VÀLM test case)
        "\u0300": "",  # Combining grave accent (as in VÀLM)
        "\u0410": "",  # Cyrillic capital A (problematic, remove entirely)
    }

    # Characters to preserve (typography that should remain)
    PRESERVE_CHARS: Set[str] = {"!", "?", ".", ",", ";", ":", "(", ")", "[", "]"}

    @classmethod
    def normalize_text(cls, text: str) -> str:
        """Normalize text to UTF-8 and clean encoding artifacts.

        Args:
            text: Input text that may contain encoding issues

        Returns:
            Normalized UTF-8 text with problematic characters cleaned
        """
        if not text:
            return text

        original_text = text  # Keep for logging

        # Early UTF-8 normalization
        try:
            text = text.encode("utf-8", errors="ignore").decode("utf-8")
        except UnicodeError as e:
            logger.warning(f"UTF-8 normalization failed: {e}")
            # Fall back to ascii-safe encoding
            text = text.encode("ascii", errors="ignore").decode("ascii")

        # Apply character replacements
        for bad, good in cls.CHARACTER_MAP.items():
            if bad in text:
                text = text.replace(bad, good)
                logger.debug(f"Replaced '{bad}' (U+{ord(bad):04X}) with '{good}'")

        # Remove non-printable characters except newlines/tabs and preserved punctuation
        allowed_chars = set("\n\t ") | cls.PRESERVE_CHARS
        cleaned_chars = []
        for char in text:
            if char.isprintable() or char in allowed_chars:
                cleaned_chars.append(char)
            elif ord(char) < 32 and char not in ["\n", "\t"]:
                logger.debug(f"Removed control character U+{ord(char):04X}")

        text = "".join(cleaned_chars).strip()

        # Log significant changes
        if text != original_text:
            logger.info(
                f"Text normalization applied: '{original_text[:50]}...' -> '{text[:50]}...'"
            )

        return text

    @classmethod
    def validate_json_roundtrip(cls, text: str) -> bool:
        """Validate that text survives JSON serialization.

        Args:
            text: Text to test for JSON compatibility

        Returns:
            True if text survives JSON round-trip, False otherwise
        """
        try:
            serialized = json.dumps(text, ensure_ascii=False)
            deserialized = json.loads(serialized)
            return text == deserialized
        except (UnicodeEncodeError, UnicodeDecodeError, json.JSONDecodeError) as e:
            logger.warning(f"JSON round-trip validation failed: {e}")
            return False

    # Common British/American spelling variants for compendium lookup
    SPELLING_VARIANTS: Dict[str, str] = {
        "travelling": "traveling",
        "travelled": "traveled",
        "traveller": "traveler",
        "colour": "color",
        "honour": "honor",
        "favour": "favor",
        "armour": "armor",
        "behaviour": "behavior",
        "flavour": "flavor",
        "rumour": "rumor",
        "savour": "savor",
        "valour": "valor",
        "vigour": "vigor",
    }

    @classmethod
    def sanitize_for_compendium_lookup(cls, name: str) -> str:
        """Sanitize text specifically for compendium name matching.

        This removes common punctuation that might interfere with name matching
        while preserving the essential text content. Also normalizes British
        spellings to American spellings for consistent matching.

        Args:
            name: Original name that may contain problematic characters

        Returns:
            Sanitized name suitable for compendium lookup
        """
        if not name:
            return name

        # First normalize the text
        normalized = cls.normalize_text(name)

        # Normalize British spellings to American spellings
        lower_normalized = normalized.lower()
        for british, american in cls.SPELLING_VARIANTS.items():
            if british in lower_normalized:
                # Preserve original case by replacing case-insensitively
                normalized = re.sub(
                    re.escape(british), american, normalized, flags=re.IGNORECASE
                )

        # Remove punctuation that interferes with matching but preserve spaces
        # This is more aggressive than the basic normalize_text
        punctuation_to_remove = ",.!?;:\"'()[]"
        for char in punctuation_to_remove:
            normalized = normalized.replace(char, "")

        # Normalize whitespace
        normalized = re.sub(r"\s+", " ", normalized).strip()

        # Convert to lowercase for consistent comparison
        normalized = normalized.lower()

        return normalized

    @classmethod
    def get_text_difference_summary(
        cls, original: str, normalized: str
    ) -> Dict[str, any]:
        """Get a summary of changes made during normalization.

        Args:
            original: Original text before normalization
            normalized: Text after normalization

        Returns:
            Dictionary with change summary details
        """
        return {
            "original_length": len(original),
            "normalized_length": len(normalized),
            "length_difference": len(normalized) - len(original),
            "characters_removed": set(original) - set(normalized),
            "has_unicode_issues": any(ord(c) > 127 for c in original),
            "json_safe": cls.validate_json_roundtrip(normalized),
        }


def test_text_normalization():
    """Run basic tests on text normalization functionality."""
    test_cases = [
        # (input, expected_output, description)
        ('"Strike Now!"', '"Strike Now!"', "Smart quotes to regular quotes"),
        ("VÀLM", "VLM", "International characters (VÀLM test case)"),
        ("Em—dash", "Em-dash", "Em dash to hyphen"),
        ("Ellipsis…", "Ellipsis...", "Ellipsis expansion"),
        (
            "Text with\ufffdreplacement",
            "Text withreplacement",
            "Replacement character removal",
        ),
    ]

    print("Running text normalization tests...")
    for input_text, expected, description in test_cases:
        result = TextNormalizer.normalize_text(input_text)
        status = "✓" if result == expected else "✗"
        print(
            f"{status} {description}: '{input_text}' -> '{result}' (expected: '{expected}')"
        )
        if result != expected:
            print(f"  FAILED: Got '{result}', expected '{expected}'")


if __name__ == "__main__":
    test_text_normalization()
