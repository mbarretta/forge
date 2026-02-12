"""Tests for DHI-Compete data models."""

import pytest

from forge_gauge.plugins.dhi_compete.models import (
    ProvenanceType,
    VEXStatus,
    DebianCVEStatus,
    SBOMComponent,
    SBOMAnalysis,
    SBOMComparisonResult,
    VEXMismatch,
    VEXAnalysis,
    VEXComparisonResult,
    AttackSurfaceMetrics,
    AttackSurfaceComparisonResult,
    ImageComparisonResult,
)


class TestSBOMComponent:
    """Tests for SBOMComponent dataclass."""

    def test_create_component(self):
        """Test creating a basic SBOM component."""
        component = SBOMComponent(
            name="openssl",
            version="3.0.0",
            purl="pkg:apk/alpine/openssl@3.0.0",
            provenance=ProvenanceType.SOURCE_BUILT,
        )

        assert component.name == "openssl"
        assert component.version == "3.0.0"
        assert component.provenance == ProvenanceType.SOURCE_BUILT

    def test_component_is_frozen(self):
        """Test that SBOMComponent is immutable."""
        component = SBOMComponent(name="test", version="1.0")

        with pytest.raises(AttributeError):
            component.name = "changed"


class TestSBOMAnalysis:
    """Tests for SBOMAnalysis dataclass."""

    def test_source_built_percentage_calculation(self):
        """Test source-built percentage calculation."""
        analysis = SBOMAnalysis(
            image="test:latest",
            total_components=100,
            source_built_count=75,
            binary_ingested_count=20,
            unknown_count=5,
        )

        assert analysis.source_built_percentage == 75.0

    def test_source_built_percentage_empty(self):
        """Test source-built percentage with no components."""
        analysis = SBOMAnalysis(
            image="test:latest",
            total_components=0,
            source_built_count=0,
            binary_ingested_count=0,
            unknown_count=0,
        )

        assert analysis.source_built_percentage == 0.0


class TestVEXMismatch:
    """Tests for VEXMismatch dataclass."""

    def test_is_concerning_not_affected_vs_no_dsa(self):
        """Test concerning mismatch: vendor says not affected, Debian says no-dsa."""
        mismatch = VEXMismatch(
            cve_id="CVE-2024-1234",
            package="openssl",
            vendor_status=VEXStatus.NOT_AFFECTED,
            debian_status=DebianCVEStatus.NO_DSA,
            description="Test CVE",
        )

        assert mismatch.is_concerning is True

    def test_is_concerning_not_affected_vs_open(self):
        """Test concerning mismatch: vendor says not affected, Debian says open."""
        mismatch = VEXMismatch(
            cve_id="CVE-2024-1234",
            package="openssl",
            vendor_status=VEXStatus.NOT_AFFECTED,
            debian_status=DebianCVEStatus.OPEN,
            description="Test CVE",
        )

        assert mismatch.is_concerning is True

    def test_is_not_concerning_when_both_agree(self):
        """Test non-concerning when vendor and Debian agree."""
        mismatch = VEXMismatch(
            cve_id="CVE-2024-1234",
            package="openssl",
            vendor_status=VEXStatus.FIXED,
            debian_status=DebianCVEStatus.FIXED,
            description="Test CVE",
        )

        assert mismatch.is_concerning is False


class TestVEXAnalysis:
    """Tests for VEXAnalysis dataclass."""

    def test_concerning_mismatches_filter(self):
        """Test filtering for concerning mismatches only."""
        mismatches = (
            VEXMismatch(
                cve_id="CVE-1",
                package="pkg1",
                vendor_status=VEXStatus.NOT_AFFECTED,
                debian_status=DebianCVEStatus.NO_DSA,
                description="Concerning",
            ),
            VEXMismatch(
                cve_id="CVE-2",
                package="pkg2",
                vendor_status=VEXStatus.FIXED,
                debian_status=DebianCVEStatus.FIXED,
                description="Not concerning",
            ),
            VEXMismatch(
                cve_id="CVE-3",
                package="pkg3",
                vendor_status=VEXStatus.NOT_AFFECTED,
                debian_status=DebianCVEStatus.OPEN,
                description="Concerning",
            ),
        )

        analysis = VEXAnalysis(
            image="test:latest",
            total_cves=10,
            not_affected_count=5,
            affected_count=3,
            fixed_count=2,
            mismatches=mismatches,
        )

        concerning = analysis.concerning_mismatches
        assert len(concerning) == 2
        assert all(m.is_concerning for m in concerning)


class TestAttackSurfaceMetrics:
    """Tests for AttackSurfaceMetrics dataclass."""

    def test_attack_surface_score_minimal(self):
        """Test attack surface score for minimal/secure image."""
        metrics = AttackSurfaceMetrics(
            image="secure:latest",
            runs_as_root=False,
            has_shell=False,
            has_package_manager=False,
            total_packages=10,
        )

        # Only 10 packages = 0 points (10 // 100 = 0)
        assert metrics.attack_surface_score == 0

    def test_attack_surface_score_root(self):
        """Test attack surface score impact of running as root."""
        metrics = AttackSurfaceMetrics(
            image="test:latest",
            runs_as_root=True,
            has_shell=False,
            has_package_manager=False,
        )

        assert metrics.attack_surface_score == 50

    def test_attack_surface_score_full(self):
        """Test attack surface score with multiple risk factors."""
        metrics = AttackSurfaceMetrics(
            image="risky:latest",
            runs_as_root=True,  # +50
            has_shell=True,  # +20
            has_package_manager=True,  # +10
            exposed_ports=(80, 443),  # +10
            setuid_binaries=("/usr/bin/sudo",),  # +10
            capabilities=("CAP_NET_ADMIN",),  # +15
            total_packages=250,  # +2
        )

        expected = 50 + 20 + 10 + 10 + 10 + 15 + 2
        assert metrics.attack_surface_score == expected


class TestAttackSurfaceComparisonResult:
    """Tests for AttackSurfaceComparisonResult dataclass."""

    def test_score_improvement_positive(self):
        """Test score improvement when Chainguard is better."""
        alt_metrics = AttackSurfaceMetrics(
            image="alt:latest",
            runs_as_root=True,
            has_shell=True,
            has_package_manager=True,
        )
        cg_metrics = AttackSurfaceMetrics(
            image="cg:latest",
            runs_as_root=False,
            has_shell=False,
            has_package_manager=False,
        )

        comparison = AttackSurfaceComparisonResult(
            alternative=alt_metrics,
            chainguard=cg_metrics,
        )

        assert comparison.score_improvement == 80  # 80 - 0
        assert comparison.score_improvement_percentage == 100.0

    def test_score_improvement_negative(self):
        """Test score improvement when alternative is better (rare case)."""
        alt_metrics = AttackSurfaceMetrics(
            image="alt:latest",
            runs_as_root=False,
            has_shell=False,
            has_package_manager=False,
        )
        cg_metrics = AttackSurfaceMetrics(
            image="cg:latest",
            runs_as_root=True,
            has_shell=False,
            has_package_manager=False,
        )

        comparison = AttackSurfaceComparisonResult(
            alternative=alt_metrics,
            chainguard=cg_metrics,
        )

        assert comparison.score_improvement == -50  # 0 - 50


class TestImageComparisonResult:
    """Tests for ImageComparisonResult dataclass."""

    def test_has_error(self):
        """Test has_error property."""
        result_ok = ImageComparisonResult(
            alternative_image="alt:latest",
            chainguard_image="cg:latest",
        )
        assert result_ok.has_error is False

        result_error = ImageComparisonResult(
            alternative_image="alt:latest",
            chainguard_image="cg:latest",
            error="Something went wrong",
        )
        assert result_error.has_error is True

    def test_overall_recommendation_with_improvement(self):
        """Test recommendation when Chainguard shows improvement."""
        alt_metrics = AttackSurfaceMetrics(
            image="alt:latest",
            runs_as_root=True,
            has_shell=True,
            has_package_manager=True,
        )
        cg_metrics = AttackSurfaceMetrics(
            image="cg:latest",
            runs_as_root=False,
            has_shell=False,
            has_package_manager=False,
        )

        result = ImageComparisonResult(
            alternative_image="alt:latest",
            chainguard_image="cg:latest",
            attack_surface_comparison=AttackSurfaceComparisonResult(
                alternative=alt_metrics,
                chainguard=cg_metrics,
            ),
        )

        assert "Chainguard image recommended" in result.overall_recommendation
        assert "Attack surface reduced" in result.overall_recommendation

    def test_overall_recommendation_with_error(self):
        """Test recommendation when there's an error."""
        result = ImageComparisonResult(
            alternative_image="alt:latest",
            chainguard_image="cg:latest",
            error="Failed to pull image",
        )

        assert "incomplete" in result.overall_recommendation.lower()
