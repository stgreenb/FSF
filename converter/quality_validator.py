"""
Quality instrumentation and validation for conversion process.

This module provides comprehensive validation, quality checks, and reporting
to ensure conversion success and data integrity.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

@dataclass
class ValidationResult:
    """Result of a validation check."""
    is_valid: bool
    message: str
    severity: str = "warning"  # "info", "warning", "error"
    details: Optional[Dict[str, Any]] = None

@dataclass
class QualityMetrics:
    """Quality metrics for a conversion process."""
    total_items: int
    successful_conversions: int
    failed_conversions: int
    items_with_warnings: int
    processing_time: float
    issues_found: List[ValidationResult]

class QualityValidator:
    """Comprehensive quality validation for conversion processes."""

    def __init__(self):
        self.validation_results: List[ValidationResult] = []
        self.start_time = None
        self.end_time = None

    def start_validation(self):
        """Start the validation process."""
        self.start_time = datetime.now()
        self.validation_results = []

    def end_validation(self):
        """End the validation process."""
        self.end_time = datetime.now()

    def get_processing_time(self) -> float:
        """Get total processing time in seconds."""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0.0

    def validate_character_conversion(self, original_data: Dict[str, Any],
                                    converted_data: Dict[str, Any],
                                    compendium_items: Dict[str, Any]) -> QualityMetrics:
        """Comprehensive validation of character conversion.

        Args:
            original_data: Original Forgesteel character data
            converted_data: Converted Foundry VTT character data
            compendium_items: Loaded compendium items

        Returns:
            Quality metrics for the conversion
        """
        from converter.text_normalizer import TextNormalizer
        from converter.level_detector import LevelDetector
        from converter.ability_converter import AbilityConverter
        from converter.description_transfer import DescriptionTransfer

        logger.info("Starting comprehensive character conversion validation")

        total_items = 0
        successful_conversions = 0
        failed_conversions = 0
        items_with_warnings = 0

        # Basic structure validation
        self._validate_basic_structure(original_data, converted_data)
        total_items += 1

        # Level detection validation
        level_validation = self._validate_level_detection(original_data, converted_data)
        total_items += 1
        if level_validation.is_valid:
            successful_conversions += 1
        else:
            failed_conversions += 1

        # Ability conversion validation
        ability_metrics = self._validate_ability_conversion(original_data, converted_data, compendium_items)
        total_items += ability_metrics.total_items
        successful_conversions += ability_metrics.successful_conversions
        failed_conversions += ability_metrics.failed_conversions

        # Description transfer validation
        description_metrics = self._validate_description_transfers(original_data, converted_data)
        total_items += description_metrics.total_items
        successful_conversions += description_metrics.successful_conversions
        failed_conversions += description_metrics.failed_conversions

        # Text encoding validation
        encoding_validation = self._validate_text_encoding(converted_data)
        total_items += 1
        if encoding_validation.is_valid:
            successful_conversions += 1
        else:
            failed_conversions += 1

        # Compendium mapping validation
        mapping_validation = self._validate_compendium_mappings(converted_data, compendium_items)
        total_items += 1
        if mapping_validation.is_valid:
            successful_conversions += 1
        else:
            items_with_warnings += 1

        # Count items with warnings
        items_with_warnings += sum(1 for result in self.validation_results if result.severity == "warning")

        return QualityMetrics(
            total_items=total_items,
            successful_conversions=successful_conversions,
            failed_conversions=failed_conversions,
            items_with_warnings=items_with_warnings,
            processing_time=self.get_processing_time(),
            issues_found=self.validation_results
        )

    def _validate_basic_structure(self, original: Dict[str, Any], converted: Dict[str, Any]):
        """Validate basic Foundry VTT structure."""
        if not converted.get("name"):
            self.validation_results.append(ValidationResult(
                is_valid=False,
                message="Character missing name",
                severity="error",
                details={"original_name": original.get("name")}
            ))

        if converted.get("type") != "hero":
            self.validation_results.append(ValidationResult(
                is_valid=False,
                message="Character type is not 'hero'",
                severity="error",
                details={"actual_type": converted.get("type")}
            ))

        if "system" not in converted:
            self.validation_results.append(ValidationResult(
                is_valid=False,
                message="Character missing system data",
                severity="error"
            ))

        # Check for required system fields
        required_fields = ["stamina", "characteristics", "combat", "hero"]
        system_data = converted.get("system", {})
        missing_fields = [field for field in required_fields if field not in system_data]

        if missing_fields:
            self.validation_results.append(ValidationResult(
                is_valid=False,
                message=f"Missing required system fields: {', '.join(missing_fields)}",
                severity="error",
                details={"missing_fields": missing_fields}
            ))

    def _validate_level_detection(self, original: Dict[str, Any], converted: Dict[str, Any]) -> ValidationResult:
        """Validate level detection and consistency."""
        from converter.level_detector import LevelDetector

        detected_level = LevelDetector.detect_level(original)
        validation = LevelDetector.validate_level_consistency(original)

        # Check if level is properly set in converted data
        class_items = [item for item in converted.get("items", []) if item.get("type") == "class"]
        converted_level = None
        if class_items:
            converted_level = class_items[0].get("system", {}).get("level")

        if converted_level != detected_level:
            return ValidationResult(
                is_valid=False,
                message=f"Level mismatch: detected {detected_level}, converted {converted_level}",
                severity="error",
                details={
                    "detected_level": detected_level,
                    "converted_level": converted_level,
                    "sources_consistent": validation["is_consistent"]
                }
            )

        if not validation["is_consistent"]:
            return ValidationResult(
                is_valid=True,  # Still valid but with warning
                message="Level sources inconsistent but conversion successful",
                severity="warning",
                details=validation
            )

        return ValidationResult(
            is_valid=True,
            message=f"Level detection successful: {detected_level}",
            severity="info"
        )

    def _validate_ability_conversion(self, original: Dict[str, Any], converted: Dict[str, Any],
                                   compendium_items: Dict[str, Any]) -> QualityMetrics:
        """Validate ability conversion completeness."""
        from converter.ability_converter import AbilityConverter
        from converter.level_detector import LevelDetector

        character_level = LevelDetector.detect_level(original)
        all_abilities = original.get("class", {}).get("abilities", [])
        converted_abilities = [item for item in converted.get("items", []) if item.get("type") == "ability"]

        validation = AbilityConverter.validate_ability_conversion(
            all_abilities, converted_abilities, character_level
        )

        total_items = 1
        successful = 1 if validation["is_valid"] else 0
        failed = 0 if validation["is_valid"] else 1

        if not validation["is_valid"]:
            self.validation_results.append(ValidationResult(
                is_valid=False,
                message=f"Ability conversion incomplete: {validation['converted_count']}/{validation['expected_count']}",
                severity="error",
                details=validation
            ))

        return QualityMetrics(
            total_items=total_items,
            successful_conversions=successful,
            failed_conversions=failed,
            items_with_warnings=0,
            processing_time=0.0,
            issues_found=[]
        )

    def _validate_description_transfers(self, original: Dict[str, Any], converted: Dict[str, Any]) -> QualityMetrics:
        """Validate description transfer quality."""
        from converter.description_transfer import DescriptionTransfer

        # Collect source and converted items for audit
        source_items = []
        converted_items = []

        # Add various item types
        for section in ["ancestry", "culture", "career", "class"]:
            if section in original:
                source_items.append(original[section])

        converted_section_items = converted.get("items", [])
        converted_items.extend(converted_section_items)

        audit = DescriptionTransfer.audit_description_transfers(source_items, converted_items)

        if audit["failed_transfers"] > 0:
            self.validation_results.append(ValidationResult(
                is_valid=False,
                message=f"Description transfer failures: {audit['failed_transfers']}",
                severity="error",
                details=audit
            ))

        if audit["empty_descriptions"] > 0:
            self.validation_results.append(ValidationResult(
                is_valid=True,
                message=f"Empty descriptions: {audit['empty_descriptions']}",
                severity="warning",
                details={"empty_count": audit["empty_descriptions"]}
            ))

        return QualityMetrics(
            total_items=1,
            successful_conversions=1 if audit["failed_transfers"] == 0 else 0,
            failed_conversions=audit["failed_transfers"],
            items_with_warnings=1 if audit["empty_descriptions"] > 0 else 0,
            processing_time=0.0,
            issues_found=[]
        )

    def _validate_text_encoding(self, converted: Dict[str, Any]) -> ValidationResult:
        """Validate text encoding and JSON safety."""
        from converter.text_normalizer import TextNormalizer

        # Test character name
        name = converted.get("name", "")
        if not TextNormalizer.validate_json_roundtrip(name):
            return ValidationResult(
                is_valid=False,
                message="Character name is not JSON-safe",
                severity="error",
                details={"name": name}
            )

        # Test item names and descriptions
        items = converted.get("items", [])
        encoding_issues = []

        for item in items:
            item_name = item.get("name", "")
            item_description = item.get("system", {}).get("description", {}).get("value", "")

            if item_name and not TextNormalizer.validate_json_roundtrip(item_name):
                encoding_issues.append(f"Item '{item_name}' name")

            if item_description and not TextNormalizer.validate_json_roundtrip(item_description):
                encoding_issues.append(f"Item '{item_name}' description")

        if encoding_issues:
            return ValidationResult(
                is_valid=False,
                message=f"Text encoding issues found: {len(encoding_issues)} items",
                severity="error",
                details={"encoding_issues": encoding_issues}
            )

        return ValidationResult(
            is_valid=True,
            message="All text encoding is valid",
            severity="info"
        )

    def _validate_compendium_mappings(self, converted: Dict[str, Any], compendium_items: Dict[str, Any]) -> ValidationResult:
        """Validate compendium mapping success rate."""
        items = converted.get("items", [])
        total_items = len(items)
        mapped_items = 0
        unmapped_items = []

        for item in items:
            # Check if item has compendium source or matches a compendium item
            has_compendium_source = (
                "_stats" in item and
                item["_stats"].get("compendiumSource") is not None
            ) or (
                "img" in item and
                item["img"] != "icons/svg/mystery-man.svg"
            )

            if has_compendium_source:
                mapped_items += 1
            else:
                unmapped_items.append(item.get("name", "Unnamed item"))

        mapping_rate = mapped_items / total_items if total_items > 0 else 0

        if mapping_rate < 0.5:
            return ValidationResult(
                is_valid=True,  # Still valid but poor mapping
                message=f"Low compendium mapping rate: {mapping_rate:.1%}",
                severity="warning",
                details={
                    "mapping_rate": mapping_rate,
                    "mapped_items": mapped_items,
                    "total_items": total_items,
                    "unmapped_items": unmapped_items[:5]  # First 5 unmapped items
                }
            )

        return ValidationResult(
            is_valid=True,
            message=f"Good compendium mapping rate: {mapping_rate:.1%}",
            severity="info",
            details={"mapping_rate": mapping_rate}
        )

    def generate_quality_report(self, metrics: QualityMetrics) -> str:
        """Generate a comprehensive quality report.

        Args:
            metrics: Quality metrics from validation

        Returns:
            Formatted quality report string
        """
        report_lines = [
            "=== Conversion Quality Report ===",
            f"Processing time: {metrics.processing_time:.2f} seconds",
            f"Total validation items: {metrics.total_items}",
            f"Successful conversions: {metrics.successful_conversions}",
            f"Failed conversions: {metrics.failed_conversions}",
            f"Items with warnings: {metrics.items_with_warnings}",
            ""
        ]

        # Success rate
        success_rate = metrics.successful_conversions / metrics.total_items if metrics.total_items > 0 else 0
        report_lines.append(f"Overall success rate: {success_rate:.1%}")

        # Issues summary
        if metrics.issues_found:
            report_lines.extend([
                "",
                "=== Issues Found ===",
                f"Total issues: {len(metrics.issues_found)}"
            ])

            errors = [issue for issue in metrics.issues_found if issue.severity == "error"]
            warnings = [issue for issue in metrics.issues_found if issue.severity == "warning"]

            if errors:
                report_lines.extend(["", f"Errors ({len(errors)}):"])
                for error in errors[:5]:  # Show first 5 errors
                    report_lines.append(f"  - {error.message}")

            if warnings:
                report_lines.extend(["", f"Warnings ({len(warnings)}):"])
                for warning in warnings[:5]:  # Show first 5 warnings
                    report_lines.append(f"  - {warning.message}")

        # Overall assessment
        report_lines.extend([
            "",
            "=== Overall Assessment ==="
        ])

        if metrics.failed_conversions == 0:
            if metrics.items_with_warnings == 0:
                report_lines.append("✅ Excellent: All conversions successful with no warnings")
            else:
                report_lines.append("✅ Good: All conversions successful with some warnings")
        else:
            failure_rate = metrics.failed_conversions / metrics.total_items
            if failure_rate < 0.1:
                report_lines.append("⚠️ Fair: Most conversions successful, some issues detected")
            else:
                report_lines.append("❌ Poor: Significant conversion issues detected")

        return "\n".join(report_lines)


def validate_conversion_with_quality(original_data: Dict[str, Any],
                                  converted_data: Dict[str, Any],
                                  compendium_items: Dict[str, Any]) -> str:
    """Convenience function to perform full quality validation.

    Args:
        original_data: Original character data
        converted_data: Converted character data
        compendium_items: Compendium items used in conversion

    Returns:
        Quality report string
    """
    validator = QualityValidator()
    validator.start_validation()

    metrics = validator.validate_character_conversion(original_data, converted_data, compendium_items)
    validator.end_validation()

    return validator.generate_quality_report(metrics)


if __name__ == "__main__":
    # Test the quality validator
    test_original = {
        "name": "Test Character",
        "class": {
            "level": 5,
            "abilities": [
                {"id": "test1", "name": "Test Ability", "level": 1, "description": "Test description"}
            ]
        }
    }

    test_converted = {
        "name": "Test Character",
        "type": "hero",
        "system": {
            "stamina": {"value": 20},
            "characteristics": {},
            "combat": {},
            "hero": {}
        },
        "items": [
            {
                "name": "Test Ability",
                "type": "ability",
                "system": {"description": {"value": "Test description"}}
            }
        ]
    }

    report = validate_conversion_with_quality(test_original, test_converted, {})
    print(report)