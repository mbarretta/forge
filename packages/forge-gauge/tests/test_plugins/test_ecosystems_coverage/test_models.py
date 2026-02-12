"""Tests for ecosystems_coverage models module."""

import pytest

from forge_gauge.plugins.ecosystems_coverage.models import (
    CoverageResult,
    CoverageSummary,
    Ecosystem,
    PackageCoverage,
    PackageStatus,
    PythonTarget,
)


class TestCoverageSummary:
    """Tests for CoverageSummary model."""

    def test_coverage_summary_coverage_percent(self):
        """Test basic coverage percentage calculation."""
        summary = CoverageSummary(
            total=10,
            available=8,
            not_available=1,
            not_on_source=1,
            errors=0,
        )
        assert summary.coverage_percent == 80.0

    def test_coverage_summary_coverage_percent_all_available(self):
        """Test coverage percentage when all packages are available."""
        summary = CoverageSummary(
            total=5,
            available=5,
            not_available=0,
            not_on_source=0,
            errors=0,
        )
        assert summary.coverage_percent == 100.0

    def test_coverage_summary_coverage_percent_none_available(self):
        """Test coverage percentage when no packages are available."""
        summary = CoverageSummary(
            total=5,
            available=0,
            not_available=5,
            not_on_source=0,
            errors=0,
        )
        assert summary.coverage_percent == 0.0

    def test_coverage_summary_zero_total(self):
        """Test coverage percentage when total is zero (avoid division by zero)."""
        summary = CoverageSummary(
            total=0,
            available=0,
            not_available=0,
            not_on_source=0,
            errors=0,
        )
        assert summary.coverage_percent == 0.0

    def test_coverage_summary_partial_coverage(self):
        """Test coverage percentage with partial coverage."""
        summary = CoverageSummary(
            total=3,
            available=1,
            not_available=1,
            not_on_source=1,
            errors=0,
        )
        assert abs(summary.coverage_percent - 33.333333) < 0.001


class TestCoverageResult:
    """Tests for CoverageResult model."""

    def test_coverage_result_has_error_true(self):
        """Test has_error property when error is set."""
        result = CoverageResult(
            input_file="requirements.txt",
            ecosystem=Ecosystem.PYTHON,
            summary=CoverageSummary(0, 0, 0, 0, 1),
            error="Something went wrong",
        )
        assert result.has_error is True

    def test_coverage_result_has_error_false(self):
        """Test has_error property when no error."""
        result = CoverageResult(
            input_file="requirements.txt",
            ecosystem=Ecosystem.PYTHON,
            summary=CoverageSummary(5, 3, 1, 1, 0),
        )
        assert result.has_error is False

    def test_coverage_result_missing_packages(self):
        """Test missing_packages property filters correctly."""
        packages = (
            PackageCoverage(
                name="available-pkg",
                requested_version="1.0.0",
                status=PackageStatus.AVAILABLE,
            ),
            PackageCoverage(
                name="missing-pkg",
                requested_version="2.0.0",
                status=PackageStatus.NOT_AVAILABLE,
            ),
            PackageCoverage(
                name="not-on-source-pkg",
                requested_version="3.0.0",
                status=PackageStatus.NOT_ON_SOURCE,
            ),
        )
        result = CoverageResult(
            input_file="requirements.txt",
            ecosystem=Ecosystem.PYTHON,
            summary=CoverageSummary(3, 1, 1, 1, 0),
            packages=packages,
        )
        missing = result.missing_packages
        assert len(missing) == 2
        assert missing[0].name == "missing-pkg"
        assert missing[1].name == "not-on-source-pkg"

    def test_coverage_result_available_packages(self):
        """Test available_packages property filters correctly."""
        packages = (
            PackageCoverage(
                name="available-pkg",
                requested_version="1.0.0",
                status=PackageStatus.AVAILABLE,
            ),
            PackageCoverage(
                name="missing-pkg",
                requested_version="2.0.0",
                status=PackageStatus.NOT_AVAILABLE,
            ),
        )
        result = CoverageResult(
            input_file="requirements.txt",
            ecosystem=Ecosystem.PYTHON,
            summary=CoverageSummary(2, 1, 1, 0, 0),
            packages=packages,
        )
        available = result.available_packages
        assert len(available) == 1
        assert available[0].name == "available-pkg"

    def test_coverage_result_empty_packages(self):
        """Test with no packages."""
        result = CoverageResult(
            input_file="requirements.txt",
            ecosystem=Ecosystem.PYTHON,
            summary=CoverageSummary(0, 0, 0, 0, 0),
        )
        assert result.missing_packages == ()
        assert result.available_packages == ()


class TestPackageCoverage:
    """Tests for PackageCoverage model."""

    def test_package_coverage_is_available_true(self):
        """Test is_available property when status is AVAILABLE."""
        pkg = PackageCoverage(
            name="test-pkg",
            requested_version="1.0.0",
            status=PackageStatus.AVAILABLE,
        )
        assert pkg.is_available is True

    def test_package_coverage_is_available_false_not_available(self):
        """Test is_available property when status is NOT_AVAILABLE."""
        pkg = PackageCoverage(
            name="test-pkg",
            requested_version="1.0.0",
            status=PackageStatus.NOT_AVAILABLE,
        )
        assert pkg.is_available is False

    def test_package_coverage_is_available_false_not_on_source(self):
        """Test is_available property when status is NOT_ON_SOURCE."""
        pkg = PackageCoverage(
            name="test-pkg",
            requested_version="1.0.0",
            status=PackageStatus.NOT_ON_SOURCE,
        )
        assert pkg.is_available is False

    def test_package_coverage_is_available_false_error(self):
        """Test is_available property when status is ERROR."""
        pkg = PackageCoverage(
            name="test-pkg",
            requested_version="1.0.0",
            status=PackageStatus.ERROR,
        )
        assert pkg.is_available is False

    def test_package_coverage_with_available_versions(self):
        """Test PackageCoverage with available_versions populated."""
        pkg = PackageCoverage(
            name="test-pkg",
            requested_version=">=1.0.0",
            status=PackageStatus.AVAILABLE,
            available_versions=("1.0.0", "1.1.0", "1.2.0"),
            resolved_version="1.2.0",
        )
        assert pkg.available_versions == ("1.0.0", "1.1.0", "1.2.0")
        assert pkg.resolved_version == "1.2.0"


class TestPythonTarget:
    """Tests for PythonTarget model."""

    def test_python_target_defaults(self):
        """Test default values for PythonTarget."""
        target = PythonTarget()
        assert target.python_version == "3.12"
        assert target.arch == "amd64"
        assert target.manylinux == "2_28"

    def test_python_target_custom_values(self):
        """Test PythonTarget with custom values."""
        target = PythonTarget(
            python_version="3.11",
            arch="arm64",
            manylinux="2_39",
        )
        assert target.python_version == "3.11"
        assert target.arch == "arm64"
        assert target.manylinux == "2_39"


class TestEcosystem:
    """Tests for Ecosystem enum."""

    def test_ecosystem_values(self):
        """Test that all ecosystem values are correct."""
        assert Ecosystem.PYTHON.value == "python"
        assert Ecosystem.JAVASCRIPT.value == "javascript"
        assert Ecosystem.JAVA.value == "java"

    def test_ecosystem_from_string(self):
        """Test creating Ecosystem from string value."""
        assert Ecosystem("python") == Ecosystem.PYTHON
        assert Ecosystem("javascript") == Ecosystem.JAVASCRIPT
        assert Ecosystem("java") == Ecosystem.JAVA


class TestPackageStatus:
    """Tests for PackageStatus enum."""

    def test_package_status_values(self):
        """Test that all package status values are correct."""
        assert PackageStatus.AVAILABLE.value == "available"
        assert PackageStatus.NOT_AVAILABLE.value == "not_available"
        assert PackageStatus.NOT_ON_SOURCE.value == "not_on_source"
        assert PackageStatus.ERROR.value == "error"
