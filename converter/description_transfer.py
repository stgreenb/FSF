"""
Robust description transfer with validation and formatting preservation.

This module handles description transfer between source data and compendium items
with comprehensive validation and safe fallback handling.
"""

import logging
import re
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class DescriptionTransfer:
    """Handles description transfer with validation and formatting preservation."""

    @classmethod
    def transfer_description(
        cls,
        source_item: Dict[str, Any],
        compendium_item: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Transfer description with fallback handling and validation.

        Args:
            source_item: Source item with description
            compendium_item: Optional compendium item to get description from

        Returns:
            Transferred description text
        """
        from converter.text_normalizer import TextNormalizer

        # Try compendium description first
        if compendium_item:
            compendium_desc = compendium_item.get("description", "").strip()
            if not compendium_desc:
                # Try nested description structure
                compendium_desc = (
                    compendium_item.get("system", {})
                    .get("description", {})
                    .get("value", "")
                    .strip()
                )

            # Try effect.before field (used in ability items)
            if not compendium_desc:
                compendium_desc = (
                    compendium_item.get("system", {})
                    .get("effect", {})
                    .get("before", "")
                    .strip()
                )

            if compendium_desc:
                logger.debug("Using compendium description")
                return cls._preserve_formatting(
                    TextNormalizer.normalize_text(compendium_desc)
                )
            else:
                logger.warning("Compendium item has empty description")

        # Fallback to source description
        source_desc = source_item.get("description", "").strip()
        if source_desc:
            logger.debug("Using source description")
            return cls._preserve_formatting(TextNormalizer.normalize_text(source_desc))

        # Try to extract from sections (used by abilities like "Mark: Trigger")
        sections = source_item.get("sections", [])
        if not sections:
            sections = (
                source_item.get("data", {}).get("ability", {}).get("sections", [])
            )
        if sections:
            text_parts = []
            for section in sections:
                if section.get("type") == "text" and section.get("text"):
                    text_parts.append(section["text"].strip())
            if text_parts:
                combined_text = " ".join(text_parts)
                logger.debug("Using sections text as description")
                return cls._preserve_formatting(
                    TextNormalizer.normalize_text(combined_text)
                )

        # Safe fallback
        logger.warning("No description found, using safe fallback")
        return "No description available"

    @classmethod
    def _preserve_formatting(cls, description: str) -> str:
        """Preserve supported formatting while ensuring safety.

        Args:
            description: Raw description text

        Returns:
            Description with preserved safe formatting
        """
        if not description:
            return description

        # Preserve basic HTML/markdown that Foundry supports
        # Remove or escape potentially problematic tags

        # List of allowed HTML tags in Foundry
        allowed_tags = [
            "p",
            "strong",
            "em",
            "i",
            "b",
            "u",
            "ul",
            "ol",
            "li",
            "br",
            "div",
            "span",
        ]

        # Simple tag validation - check for balanced tags
        for tag in allowed_tags:
            open_pattern = f"<{tag}"
            close_pattern = f"</{tag}>"
            self_closing_pattern = f"<{tag}[^>]*/>"

            open_count = len(re.findall(open_pattern, description, re.IGNORECASE))
            close_count = len(re.findall(close_pattern, description, re.IGNORECASE))
            self_closing_count = len(
                re.findall(self_closing_pattern, description, re.IGNORECASE)
            )

            # Check for tag balance (self-closing tags don't need closing tags)
            if tag not in ["br", "img", "hr"]:  # These are self-closing tags
                expected_close = open_count - self_closing_count
                if close_count < expected_close:
                    unclosed_count = expected_close - close_count
                    logger.debug(
                        f"Auto-closed {unclosed_count} unclosed <{tag}> tags in description"
                    )
                    description = description.rstrip()
                    for _ in range(unclosed_count):
                        description += f"</{tag}>"

        return description

    @classmethod
    def validate_transfer(cls, original: str, transferred: str) -> bool:
        """Validate that description transfer was successful.

        Args:
            original: Original description text
            transferred: Transferred description text

        Returns:
            True if transfer was successful, False otherwise
        """
        # Both empty is valid
        if not original and not transferred:
            return True

        # Lost content is invalid
        if original and not transferred:
            return False

        # Check for significant truncation
        if len(transferred) < len(original) * 0.5:
            logger.warning("Significant description truncation detected")
            return False

        # Check JSON safety
        from converter.text_normalizer import TextNormalizer

        if not TextNormalizer.validate_json_roundtrip(transferred):
            logger.warning("Description is not JSON-safe")
            return False

        return True

    @classmethod
    def enhance_description_for_foundry(
        cls, description: str, item_type: str = ""
    ) -> str:
        """Enhance description for Foundry VTT compatibility.

        Args:
            description: Original description
            item_type: Type of item for context-specific enhancements

        Returns:
            Enhanced description
        """
        if not description or description == "No description available":
            return description

        enhanced = description

        # Ensure proper paragraph structure
        if not enhanced.startswith("<p>") and not enhanced.startswith("<div>"):
            # Wrap in paragraph tags if it's plain text
            if "<" not in enhanced:  # No HTML tags
                enhanced = f"<p>{enhanced}</p>"

        # Convert common markdown patterns to HTML for Foundry
        # Bold text: **text** -> <strong>text</strong>
        enhanced = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", enhanced)

        # Italic text: *text* -> <em>text</em>
        enhanced = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", enhanced)

        # Double line breaks to paragraph breaks
        enhanced = re.sub(r"\n\s*\n", "</p><p>", enhanced)

        # Single line breaks to line break tags
        enhanced = re.sub(r"\n", "<br>", enhanced)

        # Item-specific enhancements
        if item_type.lower() == "ability":
            # Add ability-specific formatting if needed
            pass
        elif item_type.lower() == "feature":
            # Add feature-specific formatting if needed
            pass

        return enhanced

    @classmethod
    def get_description_statistics(cls, description: str) -> Dict[str, Any]:
        """Get statistics about a description for analysis.

        Args:
            description: Description text to analyze

        Returns:
            Dictionary with description statistics
        """
        if not description:
            return {
                "length": 0,
                "word_count": 0,
                "has_html": False,
                "has_markdown": False,
                "html_tags": [],
                "is_empty": True,
            }

        stats = {
            "length": len(description),
            "word_count": len(description.split()),
            "has_html": bool(re.search(r"<[^>]+>", description)),
            "has_markdown": bool(re.search(r"\*\*.*?\*\*|_.*?_|`.*?`", description)),
            "is_empty": not description.strip(),
        }

        # Extract HTML tags
        if stats["has_html"]:
            stats["html_tags"] = list(set(re.findall(r"<(\w+)", description)))

        return stats

    @classmethod
    def audit_description_transfers(
        cls, source_items: list, converted_items: list
    ) -> Dict[str, Any]:
        """Audit description transfers across multiple items.

        Args:
            source_items: List of source items
            converted_items: List of converted items

        Returns:
            Audit results with statistics and issues
        """
        audit_results = {
            "total_items": len(source_items),
            "successful_transfers": 0,
            "failed_transfers": 0,
            "empty_descriptions": 0,
            "truncated_descriptions": 0,
            "encoding_issues": 0,
            "issues": [],
        }

        for i, (source, converted) in enumerate(zip(source_items, converted_items)):
            source_desc = source.get("description", "")
            converted_desc = (
                converted.get("system", {}).get("description", {}).get("value", "")
            )

            if not source_desc and not converted_desc:
                audit_results["empty_descriptions"] += 1
                continue

            if cls.validate_transfer(source_desc, converted_desc):
                audit_results["successful_transfers"] += 1
            else:
                audit_results["failed_transfers"] += 1
                audit_results["issues"].append(
                    {
                        "item_index": i,
                        "item_name": source.get("name", f"Item {i}"),
                        "issue": "Transfer validation failed",
                    }
                )

            # Check for truncation
            if (
                source_desc
                and converted_desc
                and len(converted_desc) < len(source_desc) * 0.5
            ):
                audit_results["truncated_descriptions"] += 1

            # Check for encoding issues
            from converter.text_normalizer import TextNormalizer

            if not TextNormalizer.validate_json_roundtrip(converted_desc):
                audit_results["encoding_issues"] += 1

        return audit_results


def test_description_transfer():
    """Run basic tests on description transfer functionality."""
    # Test data
    source_item = {
        "name": "Test Ability",
        "description": "This is a **test** ability with *formatting*.",
    }

    compendium_item = {
        "name": "Test Ability",
        "system": {
            "description": {
                "value": "<p>This is a compendium description with <strong>HTML</strong> formatting.</p>"
            }
        },
    }

    print("Running description transfer tests...")

    # Test compendium transfer
    desc = DescriptionTransfer.transfer_description(source_item, compendium_item)
    print(f"Compendium transfer: {desc[:50]}...")

    # Test source transfer
    desc = DescriptionTransfer.transfer_description(source_item)
    print(f"Source transfer: {desc[:50]}...")

    # Test enhancement
    enhanced = DescriptionTransfer.enhance_description_for_foundry(
        "Simple text description", "ability"
    )
    print(f"Enhanced: {enhanced}")

    # Test statistics
    stats = DescriptionTransfer.get_description_statistics(desc)
    print(f"Stats: {stats}")


if __name__ == "__main__":
    test_description_transfer()
