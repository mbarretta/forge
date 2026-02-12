"""
Tests for HTML generator, including new metrics calculations.
"""

import pytest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from forge_gauge.outputs.html_generator import HTMLGenerator
from forge_gauge.core.models import (
    ImageAnalysis,
    ImagePair,
    ScanResult,
    VulnerabilityCount,
    KEVEntry,
)
from forge_gauge.integrations.kev_catalog import KEVCatalog


class TestMetricsCalculations:
    """Test the new metrics calculations in HTML generator."""

    @pytest.fixture
    def html_generator(self, tmp_path):
        """Create an HTMLGenerator instance for testing."""
        return HTMLGenerator()

    def test_images_with_reduction_all_reduced(self, html_generator):
        """Test images_with_reduction when all images have fewer CVEs with Chainguard."""
        results = [
            ScanResult(
                pair=ImagePair(
                    alternative_image="python:3.12",
                    chainguard_image="cgr.dev/chainguard/python:latest"
                ),
                alternative_analysis=ImageAnalysis(
                    name="python:3.12",
                    size_mb=950.0,
                    package_count=427,
                    vulnerabilities=VulnerabilityCount(
                        total=100, critical=5, high=20, medium=30, low=40, negligible=5
                    ),
                    scan_timestamp=datetime.now(timezone.utc),
                    digest="sha256:abc123",
                ),
                chainguard_analysis=ImageAnalysis(
                    name="cgr.dev/chainguard/python:latest",
                    size_mb=45.0,
                    package_count=35,
                    vulnerabilities=VulnerabilityCount(
                        total=10, critical=0, high=2, medium=3, low=5, negligible=0
                    ),
                    scan_timestamp=datetime.now(timezone.utc),
                    digest="sha256:def456",
                ),
                scan_successful=True,
            ),
            ScanResult(
                pair=ImagePair(
                    alternative_image="nginx:1.25",
                    chainguard_image="cgr.dev/chainguard/nginx:latest"
                ),
                alternative_analysis=ImageAnalysis(
                    name="nginx:1.25",
                    size_mb=150.0,
                    package_count=200,
                    vulnerabilities=VulnerabilityCount(
                        total=50, critical=2, high=10, medium=15, low=20, negligible=3
                    ),
                    scan_timestamp=datetime.now(timezone.utc),
                    digest="sha256:ghi789",
                ),
                chainguard_analysis=ImageAnalysis(
                    name="cgr.dev/chainguard/nginx:latest",
                    size_mb=25.0,
                    package_count=30,
                    vulnerabilities=VulnerabilityCount(
                        total=5, critical=0, high=1, medium=2, low=2, negligible=0
                    ),
                    scan_timestamp=datetime.now(timezone.utc),
                    digest="sha256:jkl012",
                ),
                scan_successful=True,
            ),
        ]

        metrics = html_generator._calculate_metrics(results)

        assert metrics['images_scanned'] == 2
        assert metrics['images_with_reduction'] == 2
        assert metrics['total_customer_vulns'] == 142
        assert metrics['total_chainguard_vulns'] == 15
        assert metrics['total_reduction'] == 127
        assert metrics['average_reduction_per_image'] == 63.5

    def test_images_with_reduction_partial(self, html_generator):
        """Test images_with_reduction when only some images have reduction."""
        results = [
            ScanResult(
                pair=ImagePair(
                    alternative_image="python:3.12",
                    chainguard_image="cgr.dev/chainguard/python:latest"
                ),
                alternative_analysis=ImageAnalysis(
                    name="python:3.12",
                    size_mb=950.0,
                    package_count=427,
                    vulnerabilities=VulnerabilityCount(
                        total=100, critical=5, high=20, medium=30, low=40, negligible=5
                    ),
                    scan_timestamp=datetime.now(timezone.utc),
                    digest="sha256:abc123",
                ),
                chainguard_analysis=ImageAnalysis(
                    name="cgr.dev/chainguard/python:latest",
                    size_mb=45.0,
                    package_count=35,
                    vulnerabilities=VulnerabilityCount(
                        total=10, critical=0, high=2, medium=3, low=5, negligible=0
                    ),
                    scan_timestamp=datetime.now(timezone.utc),
                    digest="sha256:def456",
                ),
                scan_successful=True,
            ),
            # Second image has same number of vulnerabilities
            ScanResult(
                pair=ImagePair(
                    alternative_image="nginx:1.25",
                    chainguard_image="cgr.dev/chainguard/nginx:latest"
                ),
                alternative_analysis=ImageAnalysis(
                    name="nginx:1.25",
                    size_mb=150.0,
                    package_count=200,
                    vulnerabilities=VulnerabilityCount(
                        total=50, critical=2, high=10, medium=15, low=20, negligible=3
                    ),
                    scan_timestamp=datetime.now(timezone.utc),
                    digest="sha256:ghi789",
                ),
                chainguard_analysis=ImageAnalysis(
                    name="cgr.dev/chainguard/nginx:latest",
                    size_mb=25.0,
                    package_count=30,
                    vulnerabilities=VulnerabilityCount(
                        total=50, critical=2, high=10, medium=15, low=20, negligible=3
                    ),
                    scan_timestamp=datetime.now(timezone.utc),
                    digest="sha256:jkl012",
                ),
                scan_successful=True,
            ),
        ]

        metrics = html_generator._calculate_metrics(results)

        assert metrics['images_scanned'] == 2
        assert metrics['images_with_reduction'] == 1  # Only first image has reduction
        assert metrics['total_customer_vulns'] == 142
        assert metrics['total_chainguard_vulns'] == 57
        assert metrics['total_reduction'] == 85
        assert metrics['average_reduction_per_image'] == 42.5

    def test_images_with_reduction_none(self, html_generator):
        """Test images_with_reduction when no images have reduction."""
        results = [
            ScanResult(
                pair=ImagePair(
                    alternative_image="python:3.12",
                    chainguard_image="cgr.dev/chainguard/python:latest"
                ),
                alternative_analysis=ImageAnalysis(
                    name="python:3.12",
                    size_mb=950.0,
                    package_count=427,
                    vulnerabilities=VulnerabilityCount(
                        total=10, critical=0, high=2, medium=3, low=5, negligible=0
                    ),
                    scan_timestamp=datetime.now(timezone.utc),
                    digest="sha256:abc123",
                ),
                chainguard_analysis=ImageAnalysis(
                    name="cgr.dev/chainguard/python:latest",
                    size_mb=45.0,
                    package_count=35,
                    vulnerabilities=VulnerabilityCount(
                        total=10, critical=0, high=2, medium=3, low=5, negligible=0
                    ),
                    scan_timestamp=datetime.now(timezone.utc),
                    digest="sha256:def456",
                ),
                scan_successful=True,
            ),
        ]

        metrics = html_generator._calculate_metrics(results)

        assert metrics['images_scanned'] == 1
        assert metrics['images_with_reduction'] == 0
        assert metrics['total_reduction'] == 0
        assert metrics['average_reduction_per_image'] == 0.0

    def test_average_reduction_per_image_zero_images(self, html_generator):
        """Test average_reduction_per_image with zero images (edge case)."""
        results = []

        metrics = html_generator._calculate_metrics(results)

        assert metrics['images_scanned'] == 0
        assert metrics['images_with_reduction'] == 0
        assert metrics['average_reduction_per_image'] == 0.0

    def test_metrics_with_negative_reduction(self, html_generator):
        """Test metrics when Chainguard has more CVEs (negative reduction)."""
        results = [
            ScanResult(
                pair=ImagePair(
                    alternative_image="python:3.12",
                    chainguard_image="cgr.dev/chainguard/python:latest"
                ),
                alternative_analysis=ImageAnalysis(
                    name="python:3.12",
                    size_mb=950.0,
                    package_count=427,
                    vulnerabilities=VulnerabilityCount(
                        total=10, critical=0, high=2, medium=3, low=5, negligible=0
                    ),
                    scan_timestamp=datetime.now(timezone.utc),
                    digest="sha256:abc123",
                ),
                chainguard_analysis=ImageAnalysis(
                    name="cgr.dev/chainguard/python:latest",
                    size_mb=45.0,
                    package_count=35,
                    vulnerabilities=VulnerabilityCount(
                        total=50, critical=5, high=10, medium=15, low=18, negligible=2
                    ),
                    scan_timestamp=datetime.now(timezone.utc),
                    digest="sha256:def456",
                ),
                scan_successful=True,
            ),
        ]

        metrics = html_generator._calculate_metrics(results)

        assert metrics['images_scanned'] == 1
        assert metrics['images_with_reduction'] == 0  # Chainguard has MORE CVEs
        assert metrics['total_reduction'] == -38  # Negative reduction
        assert metrics['average_reduction_per_image'] == -38.0


class TestFallbackNoteGeneration:
    """Test the _generate_fallback_note helper method."""

    @pytest.fixture
    def html_generator(self, tmp_path):
        """Create an HTMLGenerator instance for testing."""
        return HTMLGenerator()

    def test_generate_fallback_note_with_fallback(self, html_generator):
        """Test fallback note generation when fallback is used."""
        note = html_generator._generate_fallback_note(has_fallback=True, margin_top="20px")

        assert note != ""
        assert "margin-top: 20px" in note
        assert ":latest" in note
        assert "30 days" in note
        assert "*" in note

    def test_generate_fallback_note_without_fallback(self, html_generator):
        """Test fallback note generation when no fallback is used."""
        note = html_generator._generate_fallback_note(has_fallback=False)

        assert note == ""

    def test_generate_fallback_note_custom_margin(self, html_generator):
        """Test fallback note with custom margin."""
        note = html_generator._generate_fallback_note(has_fallback=True, margin_top="10px")

        assert "margin-top: 10px" in note


class TestKEVSectionGeneration:
    """Test KEV section generation in HTML reports."""

    @pytest.fixture
    def html_generator(self):
        """Create an HTMLGenerator instance for testing."""
        return HTMLGenerator()

    @pytest.fixture
    def mock_kev_catalog(self):
        """Create a mock KEV catalog."""
        catalog = Mock(spec=KEVCatalog)
        catalog.get_kev_entry.side_effect = lambda cve: KEVEntry(
            cve_id=cve,
            vendor="Test Vendor",
            product="Test Product",
            vulnerability_name=f"{cve} Vulnerability",
            date_added="2024-01-01"
        ) if cve.startswith("CVE-") else None
        return catalog

    @pytest.fixture
    def results_with_kevs(self):
        """Create scan results with KEVs."""
        return [
            ScanResult(
                pair=ImagePair(
                    alternative_image="python:3.12",
                    chainguard_image="cgr.dev/chainguard/python:latest"
                ),
                alternative_analysis=ImageAnalysis(
                    name="python:3.12",
                    size_mb=950.0,
                    package_count=427,
                    vulnerabilities=VulnerabilityCount(
                        total=100, critical=5, high=20, medium=30, low=40, negligible=5
                    ),
                    scan_timestamp=datetime.now(timezone.utc),
                    digest="sha256:abc123",
                    kev_count=2,
                    kev_cves=["CVE-2021-44228", "CVE-2022-1234"],
                ),
                chainguard_analysis=ImageAnalysis(
                    name="cgr.dev/chainguard/python:latest",
                    size_mb=45.0,
                    package_count=35,
                    vulnerabilities=VulnerabilityCount(
                        total=0, critical=0, high=0, medium=0, low=0, negligible=0
                    ),
                    scan_timestamp=datetime.now(timezone.utc),
                    digest="sha256:def456",
                    kev_count=0,
                    kev_cves=[],
                ),
                scan_successful=True,
            ),
        ]

    @pytest.fixture
    def results_without_kevs(self):
        """Create scan results without KEVs."""
        return [
            ScanResult(
                pair=ImagePair(
                    alternative_image="python:3.12",
                    chainguard_image="cgr.dev/chainguard/python:latest"
                ),
                alternative_analysis=ImageAnalysis(
                    name="python:3.12",
                    size_mb=950.0,
                    package_count=427,
                    vulnerabilities=VulnerabilityCount(
                        total=100, critical=5, high=20, medium=30, low=40, negligible=5
                    ),
                    scan_timestamp=datetime.now(timezone.utc),
                    digest="sha256:abc123",
                    kev_count=0,
                    kev_cves=[],
                ),
                chainguard_analysis=ImageAnalysis(
                    name="cgr.dev/chainguard/python:latest",
                    size_mb=45.0,
                    package_count=35,
                    vulnerabilities=VulnerabilityCount(
                        total=0, critical=0, high=0, medium=0, low=0, negligible=0
                    ),
                    scan_timestamp=datetime.now(timezone.utc),
                    digest="sha256:def456",
                    kev_count=0,
                    kev_cves=[],
                ),
                scan_successful=True,
            ),
        ]

    def test_kev_section_not_shown_when_catalog_not_provided(self, html_generator, results_with_kevs):
        """Test KEV section is not shown when kev_catalog is None."""
        section = html_generator._build_kev_section_if_needed(results_with_kevs, kev_catalog=None)
        assert section == ""

    def test_kev_section_shown_with_no_kevs_message(self, html_generator, results_without_kevs, mock_kev_catalog):
        """Test KEV section shows 'No KEVs found' message when no KEVs detected."""
        section = html_generator._build_kev_section_if_needed(results_without_kevs, mock_kev_catalog)

        assert section != ""
        assert "Known Exploited Vulnerabilities (KEV)" in section
        assert "No Known Exploited Vulnerabilities found" in section
        assert "✓" in section
        assert "colspan=\"6\"" in section

    def test_kev_section_shown_with_kevs(self, html_generator, results_with_kevs, mock_kev_catalog):
        """Test KEV section shows KEV details when KEVs are found."""
        section = html_generator._build_kev_section_if_needed(results_with_kevs, mock_kev_catalog)

        assert section != ""
        assert "Known Exploited Vulnerabilities (KEV)" in section
        assert "CVE-2021-44228" in section
        assert "CVE-2022-1234" in section
        assert "python:3.12" in section
        assert "https://www.cisa.gov/known-exploited-vulnerabilities-catalog?search_api_fulltext=" in section
        assert "No Known Exploited Vulnerabilities found" not in section

    def test_kev_section_includes_cve_and_kev_links(self, html_generator, results_with_kevs, mock_kev_catalog):
        """Test KEV section includes links to both CVE.org and CISA KEV catalog."""
        section = html_generator._build_kev_section_if_needed(results_with_kevs, mock_kev_catalog)

        # CVE ID links to CVE.org
        assert 'href="https://www.cve.org/CVERecord?id=CVE-2021-44228"' in section
        assert 'href="https://www.cve.org/CVERecord?id=CVE-2022-1234"' in section

        # Vulnerability name links to CISA KEV catalog
        assert 'href="https://www.cisa.gov/known-exploited-vulnerabilities-catalog?search_api_fulltext=CVE-2021-44228"' in section
        assert 'href="https://www.cisa.gov/known-exploited-vulnerabilities-catalog?search_api_fulltext=CVE-2022-1234"' in section

        # Both should open in new tabs
        assert 'target="_blank"' in section
        assert 'class="kev-link"' in section

    def test_kev_section_includes_all_kev_details(self, html_generator, results_with_kevs, mock_kev_catalog):
        """Test KEV section includes all KEV entry details."""
        section = html_generator._build_kev_section_if_needed(results_with_kevs, mock_kev_catalog)

        # Should include all columns from KEVEntry
        assert "Test Vendor" in section
        assert "Test Product" in section
        assert "Vulnerability" in section
        assert "2024-01-01" in section
