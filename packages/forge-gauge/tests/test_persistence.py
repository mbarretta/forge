"""
Tests for ScanResultPersistence - checkpoint/resume functionality.

Verifies save/load operations, atomic writes, version handling, and failure recovery.
"""

import json
import pytest
from datetime import datetime, timezone
from pathlib import Path

from forge_gauge.core.persistence import ScanResultPersistence
from forge_gauge.core.models import (
    ImageAnalysis,
    ImagePair,
    ScanResult,
    VulnerabilityCount,
    CHPSScore,
)
from forge_gauge.core.exceptions import CacheException


@pytest.fixture
def persistence(tmp_path):
    """Persistence manager with temp checkpoint path."""
    return ScanResultPersistence(checkpoint_path=tmp_path / "checkpoint.json")


@pytest.fixture
def sample_pair():
    """Sample image pair."""
    return ImagePair(
        chainguard_image="cgr.dev/chainguard/python:latest",
        alternative_image="python:3.12",
    )


@pytest.fixture
def sample_analysis():
    """Sample ImageAnalysis."""
    return ImageAnalysis(
        name="python:3.12",
        size_mb=950.0,
        package_count=427,
        vulnerabilities=VulnerabilityCount(
            total=100,
            critical=5,
            high=20,
            medium=40,
            low=25,
            negligible=10,
        ),
        scan_timestamp=datetime.now(timezone.utc),
        digest="sha256:abc123",
        cache_hit=False,
    )


@pytest.fixture
def sample_chainguard_analysis():
    """Sample Chainguard ImageAnalysis with CHPS score."""
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
        chps_score=CHPSScore(score=95.0, grade="A+", details={"provenance": True}),
    )


@pytest.fixture
def sample_scan_result(sample_pair, sample_analysis, sample_chainguard_analysis):
    """Sample successful scan result."""
    return ScanResult(
        pair=sample_pair,
        alternative_analysis=sample_analysis,
        chainguard_analysis=sample_chainguard_analysis,
        scan_successful=True,
    )


@pytest.fixture
def sample_failed_result(sample_pair):
    """Sample failed scan result."""
    return ScanResult(
        pair=sample_pair,
        alternative_analysis=None,
        chainguard_analysis=None,
        scan_successful=False,
        error_message="Connection timeout",
    )


class TestSaveAndLoad:
    """Tests for save and load operations."""

    def test_save_and_load_round_trip(self, persistence, sample_scan_result):
        """Full serialization cycle preserves data."""
        persistence.save_results([sample_scan_result])

        results, metadata = persistence.load_results()

        assert len(results) == 1
        result = results[0]
        assert result.pair.chainguard_image == sample_scan_result.pair.chainguard_image
        assert result.pair.alternative_image == sample_scan_result.pair.alternative_image
        assert result.scan_successful is True

    def test_save_and_load_preserves_analysis(self, persistence, sample_scan_result):
        """Analysis data is preserved through serialization."""
        persistence.save_results([sample_scan_result])

        results, _ = persistence.load_results()
        result = results[0]

        alt = result.alternative_analysis
        assert alt.name == "python:3.12"
        assert alt.size_mb == 950.0
        assert alt.package_count == 427
        assert alt.vulnerabilities.total == 100
        assert alt.vulnerabilities.critical == 5

    def test_save_and_load_preserves_chps(self, persistence, sample_scan_result):
        """CHPS score is preserved through serialization."""
        persistence.save_results([sample_scan_result])

        results, _ = persistence.load_results()
        cgr = results[0].chainguard_analysis

        assert cgr.chps_score is not None
        assert cgr.chps_score.score == 95.0
        assert cgr.chps_score.grade == "A+"
        assert cgr.chps_score.details == {"provenance": True}

    def test_save_and_load_multiple_results(
        self, persistence, sample_scan_result, sample_failed_result
    ):
        """Multiple results are saved and loaded correctly."""
        persistence.save_results([sample_scan_result, sample_failed_result])

        results, _ = persistence.load_results()

        assert len(results) == 2
        successful = [r for r in results if r.scan_successful]
        failed = [r for r in results if not r.scan_successful]
        assert len(successful) == 1
        assert len(failed) == 1

    def test_save_with_metadata(self, persistence, sample_scan_result):
        """Metadata is preserved through save/load."""
        metadata = {"scan_params": {"with_chps": True}, "version": "2.0"}
        persistence.save_results([sample_scan_result], metadata=metadata)

        _, loaded_metadata = persistence.load_results()

        assert loaded_metadata == metadata


class TestLoadNonexistent:
    """Tests for loading when checkpoint doesn't exist."""

    def test_load_nonexistent_file(self, persistence):
        """Returns empty results when file doesn't exist."""
        results, metadata = persistence.load_results()

        assert results == []
        assert metadata == {}

    def test_exists_returns_false(self, persistence):
        """exists() returns False when checkpoint doesn't exist."""
        assert persistence.exists() is False

    def test_exists_returns_true_after_save(self, persistence, sample_scan_result):
        """exists() returns True after saving."""
        persistence.save_results([sample_scan_result])
        assert persistence.exists() is True


class TestAtomicWrite:
    """Tests for atomic write behavior."""

    def test_save_atomic_write(self, persistence, sample_scan_result):
        """Temp file rename pattern is used."""
        persistence.save_results([sample_scan_result])

        # Final file should exist
        assert persistence.checkpoint_path.exists()

        # No temp files should remain
        temp_files = list(persistence.checkpoint_path.parent.glob("*.tmp"))
        assert len(temp_files) == 0

    def test_save_creates_valid_json(self, persistence, sample_scan_result):
        """Saved file is valid JSON."""
        persistence.save_results([sample_scan_result])

        # Should be valid JSON
        data = json.loads(persistence.checkpoint_path.read_text())
        assert "version" in data
        assert "results" in data
        assert "timestamp" in data


class TestVersionHandling:
    """Tests for checkpoint version handling."""

    def test_load_version_mismatch_warning(self, persistence, tmp_path, caplog):
        """Version mismatch logs a warning."""
        # Create checkpoint with old version
        old_checkpoint = {
            "version": "1.0",
            "timestamp": datetime.now().isoformat(),
            "metadata": {},
            "results": [],
        }
        persistence.checkpoint_path.write_text(json.dumps(old_checkpoint))

        import logging
        with caplog.at_level(logging.WARNING):
            results, _ = persistence.load_results()

        assert "version mismatch" in caplog.text.lower()

    def test_load_current_version_no_warning(self, persistence, sample_scan_result, caplog):
        """Current version doesn't log warning."""
        persistence.save_results([sample_scan_result])

        import logging
        with caplog.at_level(logging.WARNING):
            persistence.load_results()

        assert "version mismatch" not in caplog.text.lower()


class TestGetMetadata:
    """Tests for metadata retrieval."""

    def test_get_metadata_nonexistent(self, persistence):
        """Returns None for missing file."""
        metadata = persistence.get_metadata()
        assert metadata is None

    def test_get_metadata_returns_metadata(self, persistence, sample_scan_result):
        """Returns metadata without loading full results."""
        saved_metadata = {"scan_type": "full", "images": 10}
        persistence.save_results([sample_scan_result], metadata=saved_metadata)

        loaded_metadata = persistence.get_metadata()

        assert loaded_metadata == saved_metadata

    def test_get_metadata_corrupted_file(self, persistence):
        """Returns None for corrupted file."""
        persistence.checkpoint_path.write_text("not valid json")

        metadata = persistence.get_metadata()
        assert metadata is None


class TestClear:
    """Tests for checkpoint clearing."""

    def test_clear_removes_file(self, persistence, sample_scan_result):
        """clear() removes checkpoint file."""
        persistence.save_results([sample_scan_result])
        assert persistence.exists()

        persistence.clear()

        assert not persistence.exists()

    def test_clear_nonexistent_no_error(self, persistence):
        """clear() on nonexistent file doesn't raise."""
        persistence.clear()  # Should not raise


class TestFailedPairs:
    """Tests for extracting failed pairs."""

    def test_get_failed_pairs(self, persistence, sample_failed_result):
        """Extracts failed pairs from results."""
        persistence.save_results([sample_failed_result])

        failed = persistence.get_failed_pairs()

        assert len(failed) == 1
        assert failed[0].alternative_image == "python:3.12"

    def test_get_failed_pairs_excludes_successful(
        self, persistence, sample_scan_result, sample_failed_result
    ):
        """Only returns failed results."""
        persistence.save_results([sample_scan_result, sample_failed_result])

        failed = persistence.get_failed_pairs()

        assert len(failed) == 1

    def test_get_failed_pairs_skip_permanent(self, persistence):
        """Skips permanent failures when requested."""
        auth_failure = ScanResult(
            pair=ImagePair(
                chainguard_image="cgr.dev/chainguard/private:latest",
                alternative_image="private.registry.io/app:1.0",
            ),
            alternative_analysis=None,
            chainguard_analysis=None,
            scan_successful=False,
            error_message="unauthorized: authentication required",
        )
        timeout_failure = ScanResult(
            pair=ImagePair(
                chainguard_image="cgr.dev/chainguard/nginx:latest",
                alternative_image="nginx:1.25",
            ),
            alternative_analysis=None,
            chainguard_analysis=None,
            scan_successful=False,
            error_message="Connection timeout",
        )
        persistence.save_results([auth_failure, timeout_failure])

        # Without skip_permanent
        all_failed = persistence.get_failed_pairs(skip_permanent=False)
        assert len(all_failed) == 2

        # With skip_permanent
        retryable = persistence.get_failed_pairs(skip_permanent=True)
        assert len(retryable) == 1
        assert retryable[0].alternative_image == "nginx:1.25"


class TestMergeRetryResults:
    """Tests for merging retry results."""

    def test_merge_retry_results(self, persistence, sample_failed_result):
        """Retry results replace existing failures."""
        persistence.save_results([sample_failed_result])

        # Create successful retry result
        retry_success = ScanResult(
            pair=sample_failed_result.pair,
            alternative_analysis=ImageAnalysis(
                name="python:3.12",
                size_mb=950.0,
                package_count=427,
                vulnerabilities=VulnerabilityCount(total=100),
                scan_timestamp=datetime.now(timezone.utc),
            ),
            chainguard_analysis=ImageAnalysis(
                name="cgr.dev/chainguard/python:latest",
                size_mb=45.0,
                package_count=35,
                vulnerabilities=VulnerabilityCount(total=0),
                scan_timestamp=datetime.now(timezone.utc),
            ),
            scan_successful=True,
        )

        merged = persistence.merge_retry_results([retry_success])

        assert len(merged) == 1
        assert merged[0].scan_successful is True

    def test_merge_preserves_unrelated_results(
        self, persistence, sample_scan_result, sample_failed_result
    ):
        """Unrelated results are preserved during merge."""
        # Create a different failed result
        other_failed = ScanResult(
            pair=ImagePair(
                chainguard_image="cgr.dev/chainguard/nginx:latest",
                alternative_image="nginx:1.25",
            ),
            alternative_analysis=None,
            chainguard_analysis=None,
            scan_successful=False,
            error_message="timeout",
        )
        persistence.save_results([sample_scan_result, other_failed])

        # Retry only the nginx failure
        retry_nginx = ScanResult(
            pair=other_failed.pair,
            alternative_analysis=ImageAnalysis(
                name="nginx:1.25",
                size_mb=150.0,
                package_count=100,
                vulnerabilities=VulnerabilityCount(total=20),
                scan_timestamp=datetime.now(timezone.utc),
            ),
            chainguard_analysis=ImageAnalysis(
                name="cgr.dev/chainguard/nginx:latest",
                size_mb=30.0,
                package_count=25,
                vulnerabilities=VulnerabilityCount(total=0),
                scan_timestamp=datetime.now(timezone.utc),
            ),
            scan_successful=True,
        )

        merged = persistence.merge_retry_results([retry_nginx])

        assert len(merged) == 2
        # Original successful result preserved
        python_result = next(
            r for r in merged if "python" in r.pair.alternative_image
        )
        assert python_result.scan_successful is True
        # Failed nginx now successful
        nginx_result = next(
            r for r in merged if "nginx" in r.pair.alternative_image
        )
        assert nginx_result.scan_successful is True


class TestErrorHandling:
    """Tests for error handling."""

    def test_load_invalid_json_raises(self, persistence):
        """Invalid JSON raises CacheException."""
        persistence.checkpoint_path.write_text("not valid json {{{")

        with pytest.raises(CacheException, match="Invalid checkpoint"):
            persistence.load_results()

    def test_save_handles_unserializable(self, persistence, sample_scan_result):
        """Save handles datetime serialization."""
        # This should not raise - datetime should be serializable
        persistence.save_results([sample_scan_result])
        assert persistence.exists()


class TestDefaultCheckpointPath:
    """Tests for default checkpoint path."""

    def test_default_path(self):
        """Default path is .gauge_checkpoint.json."""
        persistence = ScanResultPersistence()
        assert persistence.checkpoint_path == Path(".gauge_checkpoint.json")

    def test_custom_path(self, tmp_path):
        """Custom path is respected."""
        custom_path = tmp_path / "custom" / "checkpoint.json"
        persistence = ScanResultPersistence(checkpoint_path=custom_path)
        assert persistence.checkpoint_path == custom_path
