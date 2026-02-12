"""
Pytest fixtures and configuration for Gauge tests.

Provides shared fixtures and test utilities across the test suite.
"""

import pytest
from datetime import datetime, timezone
from pathlib import Path

from forge_gauge.core.models import (
    ImageAnalysis,
    ImagePair,
    ScanResult,
    VulnerabilityCount,
    CHPSScore,
)


@pytest.fixture
def sample_vuln_count():
    """Sample vulnerability count for testing."""
    return VulnerabilityCount(
        total=150,
        critical=5,
        high=20,
        medium=50,
        low=60,
        negligible=15,
    )


@pytest.fixture
def sample_alternative_analysis(sample_vuln_count):
    """Sample analysis for alternative (non-Chainguard) image."""
    return ImageAnalysis(
        name="python:3.12",
        size_mb=950.0,
        package_count=427,
        vulnerabilities=sample_vuln_count,
        scan_timestamp=datetime.now(timezone.utc),
        digest="sha256:abc123",
        cache_hit=False,
    )


@pytest.fixture
def sample_chainguard_analysis():
    """Sample analysis for Chainguard image."""
    return ImageAnalysis(
        name="cgr.dev/chainguard/python:latest",
        size_mb=45.0,
        package_count=35,
        vulnerabilities=VulnerabilityCount(
            total=0,
            critical=0,
            high=0,
            medium=0,
            low=0,
            negligible=0,
        ),
        scan_timestamp=datetime.now(timezone.utc),
        digest="sha256:def456",
        cache_hit=False,
        chps_score=CHPSScore(score=95.0, grade="A+", details={}),
    )


@pytest.fixture
def sample_image_pair():
    """Sample image pair for testing."""
    return ImagePair(
        chainguard_image="cgr.dev/chainguard/python:latest",
        alternative_image="python:3.12",
    )


@pytest.fixture
def sample_scan_result(
    sample_image_pair,
    sample_alternative_analysis,
    sample_chainguard_analysis,
):
    """Sample successful scan result."""
    return ScanResult(
        pair=sample_image_pair,
        alternative_analysis=sample_alternative_analysis,
        chainguard_analysis=sample_chainguard_analysis,
        scan_successful=True,
    )


@pytest.fixture
def sample_failed_scan_result(sample_image_pair):
    """Sample failed scan result."""
    return ScanResult(
        pair=sample_image_pair,
        alternative_analysis=None,
        chainguard_analysis=None,
        scan_successful=False,
        error_message="Connection timeout",
    )


@pytest.fixture
def temp_cache_dir(tmp_path):
    """Temporary cache directory for testing."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    return cache_dir


@pytest.fixture
def sample_csv_content():
    """Sample CSV content for testing."""
    return """alternative_image,chainguard_image
python:3.12,cgr.dev/chainguard/python:latest
nginx:1.25,cgr.dev/chainguard/nginx:latest
node:20,cgr.dev/chainguard/node:latest
"""


@pytest.fixture
def temp_csv_file(tmp_path, sample_csv_content):
    """Temporary CSV file for testing."""
    csv_file = tmp_path / "test_images.csv"
    csv_file.write_text(sample_csv_content)
    return csv_file
