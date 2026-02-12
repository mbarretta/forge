"""
Tests for KEV (Known Exploited Vulnerabilities) integration.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timezone

from forge_gauge.integrations.kev_catalog import KEVCatalog
from forge_gauge.core.scanner import VulnerabilityScanner
from forge_gauge.core.cache import ScanCache
from forge_gauge.core.models import ImageAnalysis, VulnerabilityCount, KEVEntry
from forge_gauge.utils.docker_utils import DockerClient


class TestKEVCatalog:
    """Test KEV catalog functionality."""

    def test_kev_catalog_initialization(self):
        """Test KEV catalog can be initialized."""
        catalog = KEVCatalog()
        assert catalog.vulnerabilities == []

    def test_is_kev_returns_false_for_empty_catalog(self):
        """Test is_kev returns False when catalog is empty."""
        catalog = KEVCatalog()
        assert catalog.is_kev("CVE-2021-44228") is False

    def test_is_kev_returns_true_for_known_cve(self):
        """Test is_kev returns True for CVE in catalog."""
        catalog = KEVCatalog()
        catalog.vulnerabilities = [
            KEVEntry(
                cve_id="CVE-2021-44228",
                vendor="Apache",
                product="Log4j",
                vulnerability_name="Log4Shell",
                date_added="2021-12-10"
            )
        ]
        catalog.cve_ids = {"CVE-2021-44228"}
        assert catalog.is_kev("CVE-2021-44228") is True
        assert catalog.is_kev("CVE-9999-9999") is False

    def test_get_kev_entry(self):
        """Test retrieving KEV entry details."""
        catalog = KEVCatalog()
        entry = KEVEntry(
            cve_id="CVE-2021-44228",
            vendor="Apache",
            product="Log4j",
            vulnerability_name="Log4Shell",
            date_added="2021-12-10"
        )
        catalog.vulnerabilities = [entry]
        catalog._entries_by_id = {entry.cve_id: entry}

        result = catalog.get_kev_entry("CVE-2021-44228")
        assert result == entry
        assert result.cve_id == "CVE-2021-44228"
        assert result.product == "Log4j"


class TestScannerWithKEV:
    """Test scanner integration with KEV catalog."""

    @pytest.fixture
    def mock_cache(self, tmp_path):
        """Create a mock cache."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        return ScanCache(cache_dir=cache_dir, enabled=True)

    @pytest.fixture
    def mock_docker_client(self):
        """Create a mock Docker client."""
        client = Mock(spec=DockerClient)
        client.ensure_fresh_image.return_value = ("test:latest", False, True, "none")
        client.get_image_digest.return_value = "sha256:abc123"
        client.get_image_size_mb.return_value = 100.0
        return client

    @pytest.fixture
    def mock_kev_catalog(self):
        """Create a mock KEV catalog."""
        catalog = Mock(spec=KEVCatalog)
        catalog.is_kev.side_effect = lambda cve: cve in ["CVE-2021-44228", "CVE-2022-1234"]
        return catalog

    @pytest.fixture
    def scanner_with_kev(self, mock_cache, mock_docker_client, mock_kev_catalog):
        """Create a scanner with KEV catalog."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0)
            scanner = VulnerabilityScanner(
                cache=mock_cache,
                docker_client=mock_docker_client,
                max_workers=2,
                check_fresh_images=True,
                with_chps=False,
                kev_catalog=mock_kev_catalog,
            )
        return scanner

    @pytest.fixture
    def scanner_without_kev(self, mock_cache, mock_docker_client):
        """Create a scanner without KEV catalog."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0)
            scanner = VulnerabilityScanner(
                cache=mock_cache,
                docker_client=mock_docker_client,
                max_workers=2,
                check_fresh_images=True,
                with_chps=False,
                kev_catalog=None,
            )
        return scanner

    def test_scanner_detects_kevs(self, scanner_with_kev):
        """Test scanner detects KEVs when catalog is provided."""
        with patch('subprocess.run') as mock_run:
            # Mock Syft output
            syft_result = Mock(
                returncode=0,
                stdout='{"artifacts": [{"name": "pkg1"}]}'
            )
            # Mock Grype output with KEV
            grype_result = Mock(
                returncode=0,
                stdout='{"matches": [{"vulnerability": {"id": "CVE-2021-44228", "severity": "Critical"}}, {"vulnerability": {"id": "CVE-2023-9999", "severity": "High"}}]}'
            )
            mock_run.side_effect = [syft_result, grype_result]

            result = scanner_with_kev.scan_image("python:3.12")

            assert result.kev_count == 1
            assert "CVE-2021-44228" in result.kev_cves
            assert result.vulnerabilities.total == 2

    def test_scanner_no_kevs_without_catalog(self, scanner_without_kev):
        """Test scanner doesn't check KEVs when catalog is not provided."""
        with patch('subprocess.run') as mock_run:
            # Mock Syft output
            syft_result = Mock(
                returncode=0,
                stdout='{"artifacts": [{"name": "pkg1"}]}'
            )
            # Mock Grype output
            grype_result = Mock(
                returncode=0,
                stdout='{"matches": [{"vulnerability": {"id": "CVE-2021-44228", "severity": "Critical"}}]}'
            )
            mock_run.side_effect = [syft_result, grype_result]

            result = scanner_without_kev.scan_image("python:3.12")

            assert result.kev_count == 0
            assert result.kev_cves == []

    def test_scanner_with_multiple_kevs(self, scanner_with_kev):
        """Test scanner correctly counts multiple KEVs."""
        with patch('subprocess.run') as mock_run:
            # Mock Syft output
            syft_result = Mock(
                returncode=0,
                stdout='{"artifacts": [{"name": "pkg1"}]}'
            )
            # Mock Grype output with multiple KEVs
            grype_result = Mock(
                returncode=0,
                stdout='{"matches": [{"vulnerability": {"id": "CVE-2021-44228", "severity": "Critical"}}, {"vulnerability": {"id": "CVE-2022-1234", "severity": "High"}}, {"vulnerability": {"id": "CVE-2023-5678", "severity": "Medium"}}]}'
            )
            mock_run.side_effect = [syft_result, grype_result]

            result = scanner_with_kev.scan_image("python:3.12")

            assert result.kev_count == 2
            assert "CVE-2021-44228" in result.kev_cves
            assert "CVE-2022-1234" in result.kev_cves
            assert "CVE-2023-5678" not in result.kev_cves


class TestKEVCaching:
    """Test that KEV data is properly cached."""

    @pytest.fixture
    def cache_dir(self, tmp_path):
        """Create temporary cache directory."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        return cache_dir

    def test_kev_data_stored_in_cache(self, cache_dir):
        """Test KEV data is stored when caching."""
        cache = ScanCache(cache_dir=cache_dir, enabled=True)

        analysis = ImageAnalysis(
            name="python:3.12",
            size_mb=950.0,
            package_count=427,
            vulnerabilities=VulnerabilityCount(
                total=10, critical=2, high=3, medium=3, low=2, negligible=0
            ),
            scan_timestamp=datetime.now(timezone.utc),
            digest="sha256:abc123",
            kev_count=2,
            kev_cves=["CVE-2021-44228", "CVE-2022-1234"],
        )

        cache.put(analysis)

        # Retrieve from cache - must specify require_kevs=True to match cached data
        cached = cache.get("python:3.12", "sha256:abc123", require_kevs=True)

        assert cached is not None
        assert cached.kev_count == 2
        assert cached.kev_cves == ["CVE-2021-44228", "CVE-2022-1234"]

    def test_cached_analysis_without_kev_defaults(self, cache_dir):
        """Test cached analysis without KEV data defaults to zero."""
        cache = ScanCache(cache_dir=cache_dir, enabled=True)

        # Create analysis without KEV data (simulating old cache format)
        analysis = ImageAnalysis(
            name="nginx:latest",
            size_mb=150.0,
            package_count=200,
            vulnerabilities=VulnerabilityCount(
                total=5, critical=0, high=1, medium=2, low=2, negligible=0
            ),
            scan_timestamp=datetime.now(timezone.utc),
            digest="sha256:def456",
            kev_count=0,
            kev_cves=[],
        )

        cache.put(analysis)
        cached = cache.get("nginx:latest", "sha256:def456")

        assert cached is not None
        assert cached.kev_count == 0
        assert cached.kev_cves == []

    def test_cache_invalidation_when_kev_required(self, cache_dir):
        """Test cache miss when KEV data is required but not present."""
        cache = ScanCache(cache_dir=cache_dir, enabled=True)

        # Store analysis without KEV data (old cache entry)
        analysis = ImageAnalysis(
            name="nginx:1.25",
            size_mb=150.0,
            package_count=200,
            vulnerabilities=VulnerabilityCount(
                total=5, critical=0, high=1, medium=2, low=2, negligible=0
            ),
            scan_timestamp=datetime.now(timezone.utc),
            digest="sha256:oldcache",
            kev_count=0,
            kev_cves=[],
        )

        cache.put(analysis)

        # Request with require_kevs=False should return cached result
        cached = cache.get("nginx:1.25", "sha256:oldcache", require_kevs=False)
        assert cached is not None
        assert cached.kev_count == 0

        # Request with require_kevs=True should return None (cache miss)
        cached_with_kev_required = cache.get("nginx:1.25", "sha256:oldcache", require_kevs=True)
        assert cached_with_kev_required is None

    def test_cache_hit_when_kev_data_present(self, cache_dir):
        """Test cache hit when KEV data is required and present."""
        cache = ScanCache(cache_dir=cache_dir, enabled=True)

        # Store analysis WITH KEV data
        analysis = ImageAnalysis(
            name="nginx:1.25",
            size_mb=150.0,
            package_count=200,
            vulnerabilities=VulnerabilityCount(
                total=5, critical=0, high=1, medium=2, low=2, negligible=0
            ),
            scan_timestamp=datetime.now(timezone.utc),
            digest="sha256:withkev",
            kev_count=2,
            kev_cves=["CVE-2023-44487", "CVE-2025-27363"],
        )

        cache.put(analysis)

        # Request with require_kevs=True should return cached result
        cached = cache.get("nginx:1.25", "sha256:withkev", require_kevs=True)
        assert cached is not None
        assert cached.kev_count == 2
        assert cached.kev_cves == ["CVE-2023-44487", "CVE-2025-27363"]
