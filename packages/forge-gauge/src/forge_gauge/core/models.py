"""
Domain models for vulnerability assessment.

This module defines the core data structures used throughout the application.
All models are immutable (frozen dataclasses) to prevent accidental mutation.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class SeverityLevel(str, Enum):
    """CVE severity levels as defined by CVSS."""

    CRITICAL = "Critical"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"
    NEGLIGIBLE = "Negligible"
    UNKNOWN = "Unknown"

    @classmethod
    def ordered_levels(cls) -> list[str]:
        """Return severity levels in display order."""
        return [
            cls.CRITICAL.value,
            cls.HIGH.value,
            cls.MEDIUM.value,
            cls.LOW.value,
            cls.NEGLIGIBLE.value,
            cls.UNKNOWN.value,
        ]


class ImageTier(str, Enum):
    """Chainguard image tier types for pricing."""

    BASE = "base"
    APPLICATION = "application"
    FIPS = "fips"
    AI = "ai"


@dataclass(frozen=True)
class VulnerabilityCount:
    """
    Vulnerability counts broken down by severity level.

    Attributes:
        total: Total number of vulnerabilities
        critical: Number of critical vulnerabilities
        high: Number of high severity vulnerabilities
        medium: Number of medium severity vulnerabilities
        low: Number of low severity vulnerabilities
        negligible: Number of negligible/unknown vulnerabilities
    """

    total: int = 0
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    negligible: int = 0

    def get_total(self, include_negligible: bool = False) -> int:
        """
        Get total CVE count with optional negligible exclusion.

        Args:
            include_negligible: Whether to include negligible in total (default: False)

        Returns:
            Total CVE count
        """
        if include_negligible:
            return self.total
        else:
            return self.total - self.negligible

    def to_list(self) -> list[int]:
        """Convert to ordered list for tabular output."""
        return [
            self.total,
            self.critical,
            self.high,
            self.medium,
            self.low,
            self.negligible,
        ]

    def to_dict(self) -> dict[str, int]:
        """Convert to dictionary for serialization."""
        return {
            "total": self.total,
            "critical": self.critical,
            "high": self.high,
            "medium": self.medium,
            "low": self.low,
            "negligible": self.negligible,
        }

    @classmethod
    def from_dict(cls, data: dict[str, int]) -> "VulnerabilityCount":
        """Create from dictionary."""
        return cls(
            total=data.get("total", 0),
            critical=data.get("critical", 0),
            high=data.get("high", 0),
            medium=data.get("medium", 0),
            low=data.get("low", 0),
            negligible=data.get("negligible", 0),
        )


@dataclass(frozen=True)
class CHPSScore:
    """
    CHPS (Container Hardening and Provenance Scanner) scoring results.

    Attributes:
        score: Overall CHPS score (0-100)
        grade: Letter grade (A+, A, B, C, D, F)
        details: Detailed scoring breakdown from CHPS
    """

    score: float
    grade: str
    details: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ImageAnalysis:
    """
    Complete analysis results for a single container image.

    Attributes:
        name: Full image reference (registry/repo:tag)
        size_mb: Image size in megabytes
        package_count: Number of packages detected by Syft
        vulnerabilities: Vulnerability counts by severity
        scan_timestamp: When the scan was performed
        digest: Image digest (sha256)
        cache_hit: Whether result came from cache
        chps_score: CHPS scoring results (optional)
        used_latest_fallback: Whether we fell back to :latest tag due to old image
        original_image: Original image reference if fallback was used
        kev_count: Number of CISA Known Exploited Vulnerabilities found (optional)
        kev_cves: List of CVE IDs that are KEVs (optional)
    """

    name: str
    size_mb: float
    package_count: int
    vulnerabilities: VulnerabilityCount
    scan_timestamp: datetime = field(default_factory=datetime.now)
    digest: Optional[str] = None
    cache_hit: bool = False
    chps_score: Optional[CHPSScore] = None
    used_latest_fallback: bool = False
    original_image: Optional[str] = None
    kev_count: int = 0
    kev_cves: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ImagePair:
    """
    A pair of images to compare: Chainguard vs alternative.

    Attributes:
        chainguard_image: Chainguard image reference
        alternative_image: Alternative/upstream image reference
        upstream_image: Optional upstream image (e.g., docker.io equivalent for private registry images)
    """

    chainguard_image: str
    alternative_image: str
    upstream_image: Optional[str] = None

    def __str__(self) -> str:
        return f"{self.chainguard_image} vs {self.alternative_image}"


@dataclass(frozen=True)
class ScanResult:
    """
    Results of scanning an image pair.

    Attributes:
        pair: The image pair that was scanned
        chainguard_analysis: Analysis of Chainguard image
        alternative_analysis: Analysis of alternative image
        scan_successful: Whether both scans succeeded
        error_message: Error details if scan failed
    """

    pair: ImagePair
    chainguard_analysis: Optional[ImageAnalysis]
    alternative_analysis: Optional[ImageAnalysis]
    scan_successful: bool = True
    error_message: Optional[str] = None

    @property
    def vulnerability_reduction(self) -> Optional[float]:
        """Calculate percentage reduction in vulnerabilities."""
        if not self.scan_successful or not self.alternative_analysis or not self.chainguard_analysis:
            return None

        alt_total = self.alternative_analysis.vulnerabilities.total
        if alt_total == 0:
            return 0.0

        cgr_total = self.chainguard_analysis.vulnerabilities.total
        reduction = ((alt_total - cgr_total) / alt_total) * 100
        return round(reduction, 2)

    @property
    def size_reduction_mb(self) -> Optional[float]:
        """Calculate size reduction in megabytes."""
        if not self.scan_successful or not self.alternative_analysis or not self.chainguard_analysis:
            return None

        return self.alternative_analysis.size_mb - self.chainguard_analysis.size_mb

    @property
    def package_reduction(self) -> Optional[int]:
        """Calculate reduction in package count."""
        if not self.scan_successful or not self.alternative_analysis or not self.chainguard_analysis:
            return None

        return self.alternative_analysis.package_count - self.chainguard_analysis.package_count


@dataclass(frozen=True)
class KEVEntry:
    """
    Known Exploited Vulnerability catalog entry.

    Attributes:
        cve_id: CVE identifier
        vendor: Affected vendor
        product: Affected product
        vulnerability_name: Short description
        date_added: When added to KEV catalog
    """

    cve_id: str
    vendor: str
    product: str
    vulnerability_name: str
    date_added: str
