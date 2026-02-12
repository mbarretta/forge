"""Tests for core data models."""

import pytest
from datetime import datetime

from forge_gauge.core.models import (
    VulnerabilityCount,
    ImageAnalysis,
    ImagePair,
    ScanResult,
    SeverityLevel,
    CHPSScore,
)


class TestVulnerabilityCount:
    """Tests for VulnerabilityCount model."""

    def test_create_empty(self):
        """Test creating empty vulnerability count."""
        vc = VulnerabilityCount()
        assert vc.total == 0
        assert vc.critical == 0
        assert vc.high == 0
        assert vc.medium == 0
        assert vc.low == 0
        assert vc.negligible == 0

    def test_create_with_values(self, sample_vuln_count):
        """Test creating with specific values."""
        assert sample_vuln_count.total == 150
        assert sample_vuln_count.critical == 5
        assert sample_vuln_count.high == 20

    def test_to_list(self, sample_vuln_count):
        """Test conversion to list."""
        result = sample_vuln_count.to_list()
        assert result == [150, 5, 20, 50, 60, 15]

    def test_to_dict(self, sample_vuln_count):
        """Test conversion to dictionary."""
        result = sample_vuln_count.to_dict()
        assert result == {
            "total": 150,
            "critical": 5,
            "high": 20,
            "medium": 50,
            "low": 60,
            "negligible": 15,
        }

    def test_immutable(self, sample_vuln_count):
        """Test that VulnerabilityCount is immutable."""
        with pytest.raises(AttributeError):
            sample_vuln_count.total = 999


class TestImageAnalysis:
    """Tests for ImageAnalysis model."""

    def test_create_minimal(self):
        """Test creating with minimal required fields."""
        analysis = ImageAnalysis(
            name="test:latest",
            size_mb=100.0,
            package_count=50,
            vulnerabilities=VulnerabilityCount(),
        )
        assert analysis.name == "test:latest"
        assert analysis.size_mb == 100.0
        assert analysis.package_count == 50
        assert analysis.cache_hit is False
        assert analysis.chps_score is None

    def test_with_chps_score(self):
        """Test creating with CHPS score."""
        chps = CHPSScore(score=95.0, grade="A+", details={})
        analysis = ImageAnalysis(
            name="test:latest",
            size_mb=100.0,
            package_count=50,
            vulnerabilities=VulnerabilityCount(),
            chps_score=chps,
        )
        assert analysis.chps_score.score == 95.0
        assert analysis.chps_score.grade == "A+"

    def test_immutable(self, sample_alternative_analysis):
        """Test that ImageAnalysis is immutable."""
        with pytest.raises(AttributeError):
            sample_alternative_analysis.name = "other:tag"


class TestImagePair:
    """Tests for ImagePair model."""

    def test_create(self):
        """Test creating image pair."""
        pair = ImagePair(
            chainguard_image="cgr.dev/chainguard/python:latest",
            alternative_image="python:3.12",
        )
        assert pair.chainguard_image == "cgr.dev/chainguard/python:latest"
        assert pair.alternative_image == "python:3.12"

    def test_string_representation(self, sample_image_pair):
        """Test string representation."""
        result = str(sample_image_pair)
        assert "cgr.dev/chainguard/python:latest" in result
        assert "python:3.12" in result


class TestScanResult:
    """Tests for ScanResult model."""

    def test_successful_result(self, sample_scan_result):
        """Test successful scan result."""
        assert sample_scan_result.scan_successful is True
        assert sample_scan_result.alternative_analysis is not None
        assert sample_scan_result.chainguard_analysis is not None
        assert sample_scan_result.error_message is None

    def test_failed_result(self, sample_failed_scan_result):
        """Test failed scan result."""
        assert sample_failed_scan_result.scan_successful is False
        assert sample_failed_scan_result.alternative_analysis is None
        assert sample_failed_scan_result.chainguard_analysis is None
        assert sample_failed_scan_result.error_message == "Connection timeout"


class TestSeverityLevel:
    """Tests for SeverityLevel enum."""

    def test_ordered_levels(self):
        """Test ordered severity levels."""
        levels = SeverityLevel.ordered_levels()
        assert levels == [
            "Critical",
            "High",
            "Medium",
            "Low",
            "Negligible",
            "Unknown",
        ]

    def test_enum_values(self):
        """Test enum value access."""
        assert SeverityLevel.CRITICAL.value == "Critical"
        assert SeverityLevel.HIGH.value == "High"
        assert SeverityLevel.MEDIUM.value == "Medium"
