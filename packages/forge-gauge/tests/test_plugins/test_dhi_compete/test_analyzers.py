"""Tests for DHI-Compete analyzers."""

import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from forge_gauge.plugins.dhi_compete.sbom_analyzer import SBOMExtractor, SBOMAnalyzer
from forge_gauge.plugins.dhi_compete.vex_analyzer import VEXExtractor, VEXAnalyzer, DebianSecurityTracker
from forge_gauge.plugins.dhi_compete.attack_surface import AttackSurfaceAnalyzer
from forge_gauge.plugins.dhi_compete.models import (
    ProvenanceType,
    DebianCVEStatus,
    VEXStatus,
)


class TestSBOMExtractor:
    """Tests for SBOMExtractor class."""

    def test_syft_not_available(self):
        """Test behavior when syft is not available."""
        with patch("shutil.which", return_value=None):
            extractor = SBOMExtractor()
            assert extractor.syft_available is False

            result = extractor.extract("nginx:latest")
            assert result is None

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_extract_success(self, mock_run, mock_which):
        """Test successful SBOM extraction."""
        mock_which.return_value = "/usr/bin/syft"

        sbom_data = {
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package-1",
                    "name": "openssl",
                    "versionInfo": "3.0.0",
                }
            ]
        }
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(sbom_data),
        )

        extractor = SBOMExtractor()
        result = extractor.extract("nginx:latest")

        assert result is not None
        assert "packages" in result

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_extract_failure(self, mock_run, mock_which):
        """Test SBOM extraction failure."""
        mock_which.return_value = "/usr/bin/syft"
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr="Error: image not found",
        )

        extractor = SBOMExtractor()
        result = extractor.extract("nonexistent:latest")

        assert result is None


class TestSBOMAnalyzer:
    """Tests for SBOMAnalyzer class."""

    @patch.object(SBOMExtractor, "extract")
    def test_analyze_parses_components(self, mock_extract):
        """Test that analyze correctly parses SBOM components."""
        mock_extract.return_value = {
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package-1",
                    "name": "openssl",
                    "versionInfo": "3.0.0",
                    "supplier": "Chainguard",
                },
                {
                    "SPDXID": "SPDXRef-Package-2",
                    "name": "curl",
                    "versionInfo": "8.0.0",
                },
            ]
        }

        analyzer = SBOMAnalyzer()
        result = analyzer.analyze("test:latest")

        assert result is not None
        assert result.total_components == 2
        assert result.image == "test:latest"

    @patch.object(SBOMExtractor, "extract")
    def test_analyze_classifies_provenance(self, mock_extract):
        """Test provenance classification."""
        mock_extract.return_value = {
            "packages": [
                {
                    "SPDXID": "SPDXRef-1",
                    "name": "pkg1",
                    "versionInfo": "1.0",
                    "supplier": "Chainguard Inc",
                },
                {
                    "SPDXID": "SPDXRef-2",
                    "name": "pkg2",
                    "versionInfo": "1.0",
                    "externalRefs": [
                        {"referenceType": "purl", "referenceLocator": "pkg:apk/alpine/pkg2@1.0"}
                    ],
                },
            ]
        }

        analyzer = SBOMAnalyzer()
        result = analyzer.analyze("test:latest")

        assert result.source_built_count >= 1  # Chainguard supplier

    @patch.object(SBOMExtractor, "extract")
    def test_compare_calculates_diff(self, mock_extract):
        """Test SBOM comparison calculates package differences."""
        # Return different SBOMs for each call
        mock_extract.side_effect = [
            # Alternative image SBOM
            {
                "packages": [
                    {"SPDXID": "SPDXRef-1", "name": "pkg-common", "versionInfo": "1.0"},
                    {"SPDXID": "SPDXRef-2", "name": "pkg-alt-only", "versionInfo": "1.0"},
                ]
            },
            # Chainguard image SBOM
            {
                "packages": [
                    {"SPDXID": "SPDXRef-1", "name": "pkg-common", "versionInfo": "1.0"},
                    {"SPDXID": "SPDXRef-2", "name": "pkg-cg-only", "versionInfo": "1.0"},
                ]
            },
        ]

        analyzer = SBOMAnalyzer()
        result = analyzer.compare("alt:latest", "cg:latest")

        assert result is not None
        assert "pkg-common" in result.common_packages
        assert "pkg-alt-only" in result.only_in_alternative
        assert "pkg-cg-only" in result.only_in_chainguard


class TestDebianSecurityTracker:
    """Tests for DebianSecurityTracker class."""

    @patch("requests.get")
    def test_get_cve_status_fixed(self, mock_get):
        """Test getting fixed CVE status."""
        tracker_data = {
            "openssl": {
                "CVE-2024-1234": {
                    "releases": {
                        "bookworm": {"status": "resolved", "urgency": "high"}
                    }
                }
            }
        }
        mock_get.return_value = MagicMock(
            json=MagicMock(return_value=tracker_data)
        )

        tracker = DebianSecurityTracker()
        status = tracker.get_cve_status("CVE-2024-1234", "openssl")

        assert status == DebianCVEStatus.FIXED

    @patch("requests.get")
    def test_get_cve_status_open(self, mock_get):
        """Test getting open CVE status."""
        tracker_data = {
            "openssl": {
                "CVE-2024-1234": {
                    "releases": {
                        "bookworm": {"status": "open", "urgency": "high"}
                    }
                }
            }
        }
        mock_get.return_value = MagicMock(
            json=MagicMock(return_value=tracker_data)
        )

        tracker = DebianSecurityTracker()
        status = tracker.get_cve_status("CVE-2024-1234", "openssl")

        assert status == DebianCVEStatus.OPEN

    @patch("requests.get")
    def test_get_cve_status_unknown(self, mock_get):
        """Test getting unknown CVE status for missing package."""
        tracker_data = {}
        mock_get.return_value = MagicMock(
            json=MagicMock(return_value=tracker_data)
        )

        tracker = DebianSecurityTracker()
        status = tracker.get_cve_status("CVE-2024-1234", "nonexistent")

        assert status == DebianCVEStatus.UNKNOWN


class TestVEXExtractor:
    """Tests for VEXExtractor class."""

    def test_grype_not_available(self):
        """Test behavior when grype is not available."""
        with patch("shutil.which", return_value=None):
            extractor = VEXExtractor()
            assert extractor.grype_available is False

            result = extractor.extract_vulnerabilities("nginx:latest")
            assert result == []


class TestVEXAnalyzer:
    """Tests for VEXAnalyzer class."""

    @patch.object(VEXExtractor, "extract_vulnerabilities")
    @patch.object(DebianSecurityTracker, "get_cve_status")
    def test_analyze_counts_vulnerabilities(self, mock_debian, mock_extract):
        """Test vulnerability counting."""
        mock_extract.return_value = [
            {
                "vulnerability": {
                    "id": "CVE-2024-0001",
                    "fix": {"state": "fixed"},
                    "severity": "High",
                },
                "artifact": {"name": "openssl"},
            },
            {
                "vulnerability": {
                    "id": "CVE-2024-0002",
                    "fix": {"state": "not-affected"},
                    "severity": "Medium",
                },
                "artifact": {"name": "curl"},
            },
        ]
        mock_debian.return_value = DebianCVEStatus.FIXED

        analyzer = VEXAnalyzer()
        result = analyzer.analyze("test:latest")

        assert result is not None
        assert result.total_cves == 2
        assert result.fixed_count == 1
        assert result.not_affected_count == 1

    @patch.object(VEXExtractor, "extract_vulnerabilities")
    @patch.object(DebianSecurityTracker, "get_cve_status")
    def test_analyze_detects_mismatches(self, mock_debian, mock_extract):
        """Test VEX mismatch detection."""
        mock_extract.return_value = [
            {
                "vulnerability": {
                    "id": "CVE-2024-0001",
                    "fix": {"state": "not-affected"},
                    "severity": "High",
                    "description": "A vulnerability",
                },
                "artifact": {"name": "openssl"},
            },
        ]
        # Debian says it's open (no-dsa), vendor says not-affected
        mock_debian.return_value = DebianCVEStatus.NO_DSA

        analyzer = VEXAnalyzer()
        result = analyzer.analyze("test:latest")

        assert len(result.mismatches) == 1
        assert result.mismatches[0].cve_id == "CVE-2024-0001"
        assert result.mismatches[0].is_concerning is True


class TestAttackSurfaceAnalyzer:
    """Tests for AttackSurfaceAnalyzer class."""

    @patch.object(AttackSurfaceAnalyzer, "_get_image_config")
    @patch.object(AttackSurfaceAnalyzer, "_analyze_filesystem")
    def test_analyze_detects_root(self, mock_fs, mock_config):
        """Test detection of root user."""
        mock_config.return_value = {
            "config": {"User": ""},  # Empty means root
        }
        mock_fs.return_value = None

        analyzer = AttackSurfaceAnalyzer()
        result = analyzer.analyze("test:latest")

        assert result.runs_as_root is True

    @patch.object(AttackSurfaceAnalyzer, "_get_image_config")
    @patch.object(AttackSurfaceAnalyzer, "_analyze_filesystem")
    def test_analyze_detects_non_root(self, mock_fs, mock_config):
        """Test detection of non-root user."""
        mock_config.return_value = {
            "config": {"User": "nobody"},
        }
        mock_fs.return_value = None

        analyzer = AttackSurfaceAnalyzer()
        result = analyzer.analyze("test:latest")

        assert result.runs_as_root is False

    @patch.object(AttackSurfaceAnalyzer, "_get_image_config")
    @patch.object(AttackSurfaceAnalyzer, "_analyze_filesystem")
    def test_analyze_extracts_ports(self, mock_fs, mock_config):
        """Test extraction of exposed ports."""
        mock_config.return_value = {
            "config": {
                "User": "nginx",
                "ExposedPorts": {"80/tcp": {}, "443/tcp": {}},
            },
        }
        mock_fs.return_value = None

        analyzer = AttackSurfaceAnalyzer()
        result = analyzer.analyze("test:latest")

        assert 80 in result.exposed_ports
        assert 443 in result.exposed_ports

    @patch.object(AttackSurfaceAnalyzer, "_get_image_config")
    @patch.object(AttackSurfaceAnalyzer, "_analyze_filesystem")
    def test_compare_calculates_improvement(self, mock_fs, mock_config):
        """Test comparison calculates score improvement."""
        # Alternative image: root + shell
        # Chainguard image: non-root, no shell
        configs = [
            {"config": {"User": "root"}, "Config": {}},  # Alternative
            {"config": {"User": "nobody"}, "Config": {}},  # Chainguard
        ]
        mock_config.side_effect = configs
        mock_fs.side_effect = [
            {"has_shell": True, "has_package_manager": True, "setuid_binaries": [], "total_packages": 100},
            {"has_shell": False, "has_package_manager": False, "setuid_binaries": [], "total_packages": 20},
        ]

        analyzer = AttackSurfaceAnalyzer()
        result = analyzer.compare("alt:latest", "cg:latest")

        # Alternative: 50 (root) + 20 (shell) + 10 (pkg mgr) + 1 (100 pkgs) = 81
        # Chainguard: 0
        assert result.score_improvement > 0
        assert result.alternative.attack_surface_score > result.chainguard.attack_surface_score
