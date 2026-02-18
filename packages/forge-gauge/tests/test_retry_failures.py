"""
Tests for --retry-failures functionality.
"""

import argparse
import json
import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

from forge_core.plugin import ResultStatus

from forge_gauge.core.models import ImagePair, ScanResult, ImageAnalysis, VulnerabilityCount
from forge_gauge.core.persistence import ScanResultPersistence


@pytest.fixture
def sample_image_pair():
    """Create a sample image pair."""
    return ImagePair(
        chainguard_image="cgr.dev/chainguard/python:latest",
        alternative_image="python:3.12",
    )


@pytest.fixture
def sample_failed_result(sample_image_pair):
    """Create a sample failed scan result."""
    return ScanResult(
        pair=sample_image_pair,
        chainguard_analysis=None,
        alternative_analysis=None,
        scan_successful=False,
        error_message="Connection timeout",
    )


@pytest.fixture
def sample_auth_failed_result():
    """Create a sample auth failure result."""
    return ScanResult(
        pair=ImagePair(
            chainguard_image="cgr.dev/chainguard/private:latest",
            alternative_image="private.registry.io/app:v1",
        ),
        chainguard_analysis=None,
        alternative_analysis=None,
        scan_successful=False,
        error_message="unauthorized: authentication required",
    )


@pytest.fixture
def sample_not_found_result():
    """Create a sample not found result."""
    return ScanResult(
        pair=ImagePair(
            chainguard_image="cgr.dev/chainguard/missing:latest",
            alternative_image="docker.io/missing/image:v1",
        ),
        chainguard_analysis=None,
        alternative_analysis=None,
        scan_successful=False,
        error_message="manifest unknown: image not found",
    )


@pytest.fixture
def sample_successful_result():
    """Create a sample successful scan result."""
    vuln_count = VulnerabilityCount(total=10, critical=1, high=2, medium=3, low=4)
    return ScanResult(
        pair=ImagePair(
            chainguard_image="cgr.dev/chainguard/nginx:latest",
            alternative_image="nginx:latest",
        ),
        chainguard_analysis=ImageAnalysis(
            name="cgr.dev/chainguard/nginx:latest",
            size_mb=50.0,
            package_count=20,
            vulnerabilities=VulnerabilityCount(total=0),
            scan_timestamp=datetime.now(),
        ),
        alternative_analysis=ImageAnalysis(
            name="nginx:latest",
            size_mb=100.0,
            package_count=100,
            vulnerabilities=vuln_count,
            scan_timestamp=datetime.now(),
        ),
        scan_successful=True,
        error_message=None,
    )


class TestGetFailedPairs:
    """Test get_failed_pairs method."""

    def test_extracts_failed_pairs(self, tmp_path, sample_failed_result, sample_successful_result):
        """Test that only failed pairs are extracted."""
        checkpoint_file = tmp_path / "checkpoint.json"
        persistence = ScanResultPersistence(checkpoint_file)

        # Save mixed results
        persistence.save_results([sample_failed_result, sample_successful_result])

        # Get failed pairs
        failed_pairs = persistence.get_failed_pairs()

        assert len(failed_pairs) == 1
        assert failed_pairs[0].alternative_image == "python:3.12"

    def test_returns_empty_when_all_successful(self, tmp_path, sample_successful_result):
        """Test that empty list is returned when all scans succeeded."""
        checkpoint_file = tmp_path / "checkpoint.json"
        persistence = ScanResultPersistence(checkpoint_file)

        persistence.save_results([sample_successful_result])

        failed_pairs = persistence.get_failed_pairs()

        assert len(failed_pairs) == 0

    def test_skip_permanent_auth_failures(
        self, tmp_path, sample_failed_result, sample_auth_failed_result
    ):
        """Test that auth failures are skipped with skip_permanent=True."""
        checkpoint_file = tmp_path / "checkpoint.json"
        persistence = ScanResultPersistence(checkpoint_file)

        persistence.save_results([sample_failed_result, sample_auth_failed_result])

        # Without skip_permanent - should get both
        failed_pairs = persistence.get_failed_pairs(skip_permanent=False)
        assert len(failed_pairs) == 2

        # With skip_permanent - should skip auth failure
        failed_pairs = persistence.get_failed_pairs(skip_permanent=True)
        assert len(failed_pairs) == 1
        assert failed_pairs[0].alternative_image == "python:3.12"

    def test_skip_permanent_not_found_failures(
        self, tmp_path, sample_failed_result, sample_not_found_result
    ):
        """Test that not found failures are skipped with skip_permanent=True."""
        checkpoint_file = tmp_path / "checkpoint.json"
        persistence = ScanResultPersistence(checkpoint_file)

        persistence.save_results([sample_failed_result, sample_not_found_result])

        # With skip_permanent - should skip not found failure
        failed_pairs = persistence.get_failed_pairs(skip_permanent=True)
        assert len(failed_pairs) == 1
        assert failed_pairs[0].alternative_image == "python:3.12"

    def test_skip_permanent_various_error_patterns(self, tmp_path):
        """Test that various permanent error patterns are recognized."""
        checkpoint_file = tmp_path / "checkpoint.json"
        persistence = ScanResultPersistence(checkpoint_file)

        # Create results with various permanent error patterns
        permanent_errors = [
            "unauthorized: access denied",
            "forbidden: 403 Forbidden",
            "manifest unknown",
            "name unknown: repository not found",
            "authentication required",
            "404 Not Found",
        ]

        results = []
        for i, error in enumerate(permanent_errors):
            results.append(ScanResult(
                pair=ImagePair(
                    chainguard_image=f"cgr.dev/chainguard/img{i}:latest",
                    alternative_image=f"docker.io/img{i}:latest",
                ),
                chainguard_analysis=None,
                alternative_analysis=None,
                scan_successful=False,
                error_message=error,
            ))

        # Add one transient failure
        results.append(ScanResult(
            pair=ImagePair(
                chainguard_image="cgr.dev/chainguard/transient:latest",
                alternative_image="docker.io/transient:latest",
            ),
            chainguard_analysis=None,
            alternative_analysis=None,
            scan_successful=False,
            error_message="Connection reset by peer",
        ))

        persistence.save_results(results)

        # With skip_permanent - should only get the transient failure
        failed_pairs = persistence.get_failed_pairs(skip_permanent=True)
        assert len(failed_pairs) == 1
        assert failed_pairs[0].alternative_image == "docker.io/transient:latest"


class TestMergeRetryResults:
    """Test merge_retry_results method."""

    def test_merges_retry_results(
        self, tmp_path, sample_failed_result, sample_successful_result
    ):
        """Test that retry results replace failed results."""
        checkpoint_file = tmp_path / "checkpoint.json"
        persistence = ScanResultPersistence(checkpoint_file)

        # Save initial results with one failure
        persistence.save_results([sample_failed_result, sample_successful_result])

        # Create a successful retry result for the failed pair
        vuln_count = VulnerabilityCount(total=5, critical=0, high=1, medium=2, low=2)
        retry_result = ScanResult(
            pair=sample_failed_result.pair,
            chainguard_analysis=ImageAnalysis(
                name="cgr.dev/chainguard/python:latest",
                size_mb=40.0,
                package_count=15,
                vulnerabilities=VulnerabilityCount(total=0),
                scan_timestamp=datetime.now(),
            ),
            alternative_analysis=ImageAnalysis(
                name="python:3.12",
                size_mb=80.0,
                package_count=200,
                vulnerabilities=vuln_count,
                scan_timestamp=datetime.now(),
            ),
            scan_successful=True,
            error_message=None,
        )

        # Merge
        merged = persistence.merge_retry_results([retry_result])

        # Should have 2 results
        assert len(merged) == 2

        # The failed result should be replaced
        python_result = next(
            r for r in merged if r.pair.alternative_image == "python:3.12"
        )
        assert python_result.scan_successful is True

        # The successful result should be unchanged
        nginx_result = next(
            r for r in merged if r.pair.alternative_image == "nginx:latest"
        )
        assert nginx_result.scan_successful is True

    def test_merge_preserves_order(self, tmp_path):
        """Test that merged results maintain original order."""
        checkpoint_file = tmp_path / "checkpoint.json"
        persistence = ScanResultPersistence(checkpoint_file)

        # Create multiple results
        pairs = [
            ("img1", "alt1"),
            ("img2", "alt2"),
            ("img3", "alt3"),
        ]
        results = []
        for cg, alt in pairs:
            results.append(ScanResult(
                pair=ImagePair(
                    chainguard_image=f"cgr.dev/chainguard/{cg}:latest",
                    alternative_image=f"docker.io/{alt}:latest",
                ),
                chainguard_analysis=None,
                alternative_analysis=None,
                scan_successful=False,
                error_message="timeout",
            ))

        persistence.save_results(results)

        # Retry only the middle one
        retry_result = ScanResult(
            pair=results[1].pair,
            chainguard_analysis=ImageAnalysis(
                name="cgr.dev/chainguard/img2:latest",
                size_mb=40.0,
                package_count=15,
                vulnerabilities=VulnerabilityCount(total=0),
                scan_timestamp=datetime.now(),
            ),
            alternative_analysis=ImageAnalysis(
                name="docker.io/alt2:latest",
                size_mb=80.0,
                package_count=200,
                vulnerabilities=VulnerabilityCount(total=5),
                scan_timestamp=datetime.now(),
            ),
            scan_successful=True,
            error_message=None,
        )

        merged = persistence.merge_retry_results([retry_result])

        # Order should be preserved
        assert merged[0].pair.alternative_image == "docker.io/alt1:latest"
        assert merged[1].pair.alternative_image == "docker.io/alt2:latest"
        assert merged[2].pair.alternative_image == "docker.io/alt3:latest"

        # Only middle one should be successful
        assert merged[0].scan_successful is False
        assert merged[1].scan_successful is True
        assert merged[2].scan_successful is False


class TestOrchestratorRetryMode:
    """Test orchestrator retry-failures mode integration."""

    def test_retry_mode_scans_only_failed_pairs(self, tmp_path):
        """Test that retry mode only scans failed pairs."""
        from forge_gauge.core.orchestrator import GaugeOrchestrator

        # Create checkpoint with mixed results
        checkpoint_file = tmp_path / "checkpoint.json"
        persistence = ScanResultPersistence(checkpoint_file)

        vuln_count = VulnerabilityCount(total=5, critical=1, high=1, medium=2, low=1)
        successful = ScanResult(
            pair=ImagePair(
                chainguard_image="cgr.dev/chainguard/nginx:latest",
                alternative_image="nginx:latest",
            ),
            chainguard_analysis=ImageAnalysis(
                name="cgr.dev/chainguard/nginx:latest",
                size_mb=50.0,
                package_count=20,
                vulnerabilities=VulnerabilityCount(total=0),
                scan_timestamp=datetime.now(),
            ),
            alternative_analysis=ImageAnalysis(
                name="nginx:latest",
                size_mb=100.0,
                package_count=100,
                vulnerabilities=vuln_count,
                scan_timestamp=datetime.now(),
            ),
            scan_successful=True,
        )

        failed = ScanResult(
            pair=ImagePair(
                chainguard_image="cgr.dev/chainguard/python:latest",
                alternative_image="python:3.12",
            ),
            chainguard_analysis=None,
            alternative_analysis=None,
            scan_successful=False,
            error_message="timeout",
        )

        persistence.save_results([successful, failed], metadata={"platform": "linux/amd64"})

        # Mock the orchestrator and scanner
        args = argparse.Namespace(
            retry_failures=True,
            resume=False,
            skip_permanent_failures=False,
            checkpoint_file=checkpoint_file,
            input=None,
            organization=None,
        )

        with patch.object(GaugeOrchestrator, '_initialize_components'), \
             patch.object(GaugeOrchestrator, '_load_image_pairs', return_value=[]):

            orchestrator = GaugeOrchestrator(args)
            orchestrator.scanner = Mock()

            # Return a successful retry result
            retry_result = ScanResult(
                pair=failed.pair,
                chainguard_analysis=ImageAnalysis(
                    name="cgr.dev/chainguard/python:latest",
                    size_mb=40.0,
                    package_count=15,
                    vulnerabilities=VulnerabilityCount(total=0),
                    scan_timestamp=datetime.now(),
                ),
                alternative_analysis=ImageAnalysis(
                    name="python:3.12",
                    size_mb=80.0,
                    package_count=200,
                    vulnerabilities=vuln_count,
                    scan_timestamp=datetime.now(),
                ),
                scan_successful=True,
            )
            orchestrator.scanner.scan_image_pairs_parallel = Mock(return_value=[retry_result])

            results = orchestrator._execute_scans()

            # Scanner should have been called with only the failed pair
            orchestrator.scanner.scan_image_pairs_parallel.assert_called_once()
            call_args = orchestrator.scanner.scan_image_pairs_parallel.call_args[0][0]
            assert len(call_args) == 1
            assert call_args[0].alternative_image == "python:3.12"

            # Results should have both entries, with the failed one now successful
            assert len(results) == 2
            python_result = next(r for r in results if r.pair.alternative_image == "python:3.12")
            assert python_result.scan_successful is True

    def test_retry_mode_no_failures(self, tmp_path):
        """Test that retry mode handles no failures gracefully."""
        from forge_gauge.core.orchestrator import GaugeOrchestrator

        # Create checkpoint with only successful results
        checkpoint_file = tmp_path / "checkpoint.json"
        persistence = ScanResultPersistence(checkpoint_file)

        vuln_count = VulnerabilityCount(total=5, critical=1, high=1, medium=2, low=1)
        successful = ScanResult(
            pair=ImagePair(
                chainguard_image="cgr.dev/chainguard/nginx:latest",
                alternative_image="nginx:latest",
            ),
            chainguard_analysis=ImageAnalysis(
                name="cgr.dev/chainguard/nginx:latest",
                size_mb=50.0,
                package_count=20,
                vulnerabilities=VulnerabilityCount(total=0),
                scan_timestamp=datetime.now(),
            ),
            alternative_analysis=ImageAnalysis(
                name="nginx:latest",
                size_mb=100.0,
                package_count=100,
                vulnerabilities=vuln_count,
                scan_timestamp=datetime.now(),
            ),
            scan_successful=True,
        )

        persistence.save_results([successful])

        args = argparse.Namespace(
            retry_failures=True,
            resume=False,
            skip_permanent_failures=False,
            checkpoint_file=checkpoint_file,
            input=None,
            organization=None,
        )

        with patch.object(GaugeOrchestrator, '_initialize_components'), \
             patch.object(GaugeOrchestrator, '_load_image_pairs', return_value=[]):

            orchestrator = GaugeOrchestrator(args)
            orchestrator.scanner = Mock()

            results = orchestrator._execute_scans()

            # Scanner should NOT have been called
            orchestrator.scanner.scan_image_pairs_parallel.assert_not_called()

            # Results should be the original successful results
            assert len(results) == 1
            assert results[0].scan_successful is True


class TestCLIValidation:
    """Test argument validation for --retry-failures in GaugePlugin._run_scan()."""

    def test_retry_and_resume_mutually_exclusive(self, tmp_path):
        """--retry-failures and --resume are mutually exclusive."""
        from forge_gauge.plugin import GaugePlugin

        checkpoint = tmp_path / "checkpoint.json"
        checkpoint.write_text('{"version": "2.0", "results": []}')

        plugin = GaugePlugin()
        ctx = MagicMock()
        result = plugin._run_scan(
            {
                "retry_failures": True,
                "resume": True,
                "checkpoint_file": str(checkpoint),
                "with_all": False,
            },
            ctx,
        )
        assert result.status == ResultStatus.FAILURE

    def test_skip_permanent_requires_retry_failures(self):
        """--skip-permanent-failures requires --retry-failures."""
        from forge_gauge.plugin import GaugePlugin

        plugin = GaugePlugin()
        ctx = MagicMock()
        result = plugin._run_scan(
            {"retry_failures": False, "skip_permanent_failures": True, "with_all": False},
            ctx,
        )
        assert result.status == ResultStatus.FAILURE

    def test_retry_failures_requires_checkpoint(self, tmp_path):
        """--retry-failures requires checkpoint file to exist."""
        from forge_gauge.plugin import GaugePlugin

        plugin = GaugePlugin()
        ctx = MagicMock()
        result = plugin._run_scan(
            {
                "retry_failures": True,
                "resume": False,
                "checkpoint_file": str(tmp_path / "nonexistent.json"),
                "with_all": False,
            },
            ctx,
        )
        assert result.status == ResultStatus.FAILURE
