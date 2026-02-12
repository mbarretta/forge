"""
Configuration dataclasses for output generators.

Provides strongly-typed configuration objects for each output format,
replacing loose **kwargs with structured configuration.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from forge_gauge.constants import (
    DEFAULT_HOURS_PER_VULNERABILITY,
    DEFAULT_HOURLY_RATE,
    DEFAULT_PLATFORM,
)


@dataclass
class GeneratorConfig:
    """Base configuration for all generators."""

    customer_name: str = "Customer"
    platform: str = DEFAULT_PLATFORM
    include_negligible: bool = False

    def validate(self) -> None:
        """
        Validate configuration values.

        Raises:
            ValueError: If configuration is invalid
        """
        from forge_gauge.utils.validation import validate_customer_name

        self.customer_name = validate_customer_name(self.customer_name)


@dataclass
class HTMLGeneratorConfig(GeneratorConfig):
    """Configuration for HTML output generator."""

    exec_summary_path: Optional[Path] = None
    appendix_path: Optional[Path] = None
    kev_catalog: Optional['KEVCatalog'] = None

    def validate(self) -> None:
        """Validate HTML-specific configuration."""
        super().validate()

        from forge_gauge.utils.validation import validate_file_path

        if self.exec_summary_path:
            self.exec_summary_path = validate_file_path(
                self.exec_summary_path,
                must_exist=True
            )

        if self.appendix_path:
            self.appendix_path = validate_file_path(
                self.appendix_path,
                must_exist=True
            )


@dataclass
class XLSXGeneratorConfig(GeneratorConfig):
    """Configuration for XLSX output generator."""

    hours_per_vuln: float = DEFAULT_HOURS_PER_VULNERABILITY
    hourly_rate: float = DEFAULT_HOURLY_RATE
    auto_detect_fips: bool = False
    kev_catalog: Optional['KEVCatalog'] = None

    def validate(self) -> None:
        """Validate XLSX-specific configuration."""
        super().validate()

        from forge_gauge.utils.validation import validate_positive_number

        self.hours_per_vuln = validate_positive_number(
            self.hours_per_vuln,
            "hours_per_vuln",
            min_value=0.1,
            max_value=100.0,
        )

        self.hourly_rate = validate_positive_number(
            self.hourly_rate,
            "hourly_rate",
            min_value=1.0,
            max_value=10000.0,
        )


__all__ = [
    "GeneratorConfig",
    "HTMLGeneratorConfig",
    "XLSXGeneratorConfig",
]
