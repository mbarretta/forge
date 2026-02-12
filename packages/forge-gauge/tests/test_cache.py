"""
Tests for ScanCache - digest-based caching for scan results.

Verifies cache hit/miss behavior, requirement matching (CHPS/KEV),
corruption handling, and cache statistics.
"""

import json
import pytest
from datetime import datetime, timezone
from pathlib import Path

from forge_gauge.core.cache import ScanCache
from forge_gauge.core.models import ImageAnalysis, VulnerabilityCount, CHPSScore


@pytest.fixture
def cache_dir(tmp_path):
    """Temporary cache directory."""
    return tmp_path / "scan_cache"


@pytest.fixture
def enabled_cache(cache_dir):
    """Cache instance with caching enabled."""
    return ScanCache(cache_dir=cache_dir, enabled=True)


@pytest.fixture
def disabled_cache(cache_dir):
    """Cache instance with caching disabled."""
    return ScanCache(cache_dir=cache_dir, enabled=False)


@pytest.fixture
def sample_analysis():
    """Sample ImageAnalysis for testing."""
    return ImageAnalysis(
        name="nginx:1.25",
        size_mb=150.0,
        package_count=100,
        vulnerabilities=VulnerabilityCount(
            total=25,
            critical=2,
            high=5,
            medium=10,
            low=5,
            negligible=3,
        ),
        scan_timestamp=datetime.now(timezone.utc),
        digest="sha256:abc123def456",
        cache_hit=False,
    )


@pytest.fixture
def sample_analysis_with_chps():
    """Sample ImageAnalysis with CHPS score."""
    return ImageAnalysis(
        name="nginx:1.25",
        size_mb=150.0,
        package_count=100,
        vulnerabilities=VulnerabilityCount(
            total=25,
            critical=2,
            high=5,
            medium=10,
            low=5,
            negligible=3,
        ),
        scan_timestamp=datetime.now(timezone.utc),
        digest="sha256:abc123def456",
        cache_hit=False,
        chps_score=CHPSScore(score=85.0, grade="B", details={"test": "value"}),
    )


@pytest.fixture
def sample_analysis_with_kevs():
    """Sample ImageAnalysis with KEV data."""
    return ImageAnalysis(
        name="nginx:1.25",
        size_mb=150.0,
        package_count=100,
        vulnerabilities=VulnerabilityCount(
            total=25,
            critical=2,
            high=5,
            medium=10,
            low=5,
            negligible=3,
        ),
        scan_timestamp=datetime.now(timezone.utc),
        digest="sha256:abc123def456",
        cache_hit=False,
        kev_count=2,
        kev_cves=["CVE-2023-1234", "CVE-2023-5678"],
    )


class TestCacheDisabled:
    """Tests for disabled cache behavior."""

    def test_cache_disabled_returns_none(self, disabled_cache):
        """Verify cache miss when disabled."""
        result = disabled_cache.get(
            image_name="nginx:1.25",
            digest="sha256:abc123",
        )
        assert result is None
        assert disabled_cache.misses == 1
        assert disabled_cache.hits == 0

    def test_cache_disabled_put_does_nothing(self, disabled_cache, sample_analysis):
        """Verify put operation is no-op when disabled."""
        disabled_cache.put(sample_analysis)
        # No files should be created
        assert not disabled_cache.cache_dir.exists()

    def test_cache_summary_disabled(self, disabled_cache):
        """Summary when disabled returns appropriate message."""
        assert disabled_cache.summary() == "Cache disabled"


class TestCacheMiss:
    """Tests for cache miss scenarios."""

    def test_cache_miss_no_digest(self, enabled_cache):
        """Verify miss when digest is None."""
        result = enabled_cache.get(
            image_name="nginx:1.25",
            digest=None,
        )
        assert result is None
        assert enabled_cache.misses == 1

    def test_cache_miss_file_not_found(self, enabled_cache):
        """Verify miss when cache file doesn't exist."""
        result = enabled_cache.get(
            image_name="nginx:1.25",
            digest="sha256:nonexistent",
        )
        assert result is None
        assert enabled_cache.misses == 1

    def test_cache_digest_mismatch(self, enabled_cache, sample_analysis):
        """Miss when digest doesn't match file content."""
        # Store analysis
        enabled_cache.put(sample_analysis)

        # Manually corrupt the digest in the cached file
        cache_path = enabled_cache._get_cache_path(sample_analysis.digest)
        data = json.loads(cache_path.read_text())
        data["digest"] = "sha256:different_digest"
        cache_path.write_text(json.dumps(data))

        # Try to retrieve with original digest
        result = enabled_cache.get(
            image_name="nginx:1.25",
            digest=sample_analysis.digest,
        )
        assert result is None
        assert enabled_cache.misses == 1

    def test_cache_chps_requirement_mismatch_needs_chps(
        self, enabled_cache, sample_analysis
    ):
        """Miss when CHPS required but cached result has none."""
        # Store analysis without CHPS
        enabled_cache.put(sample_analysis)

        # Request with CHPS requirement
        result = enabled_cache.get(
            image_name="nginx:1.25",
            digest=sample_analysis.digest,
            require_chps=True,
        )
        assert result is None
        assert enabled_cache.misses == 1

    def test_cache_chps_requirement_mismatch_has_chps(
        self, enabled_cache, sample_analysis_with_chps
    ):
        """Miss when CHPS not required but cached result has it."""
        # Store analysis with CHPS
        enabled_cache.put(sample_analysis_with_chps)

        # Request without CHPS requirement
        result = enabled_cache.get(
            image_name="nginx:1.25",
            digest=sample_analysis_with_chps.digest,
            require_chps=False,
        )
        assert result is None
        assert enabled_cache.misses == 1

    def test_cache_kevs_requirement_mismatch_needs_kevs(
        self, enabled_cache, sample_analysis
    ):
        """Miss when KEV data required but cached result has none."""
        # Store analysis without KEV data
        enabled_cache.put(sample_analysis)

        # Request with KEV requirement
        result = enabled_cache.get(
            image_name="nginx:1.25",
            digest=sample_analysis.digest,
            require_kevs=True,
        )
        assert result is None
        assert enabled_cache.misses == 1

    def test_cache_kevs_requirement_mismatch_has_kevs(
        self, enabled_cache, sample_analysis_with_kevs
    ):
        """Miss when KEV data not required but cached result has it."""
        # Store analysis with KEV data
        enabled_cache.put(sample_analysis_with_kevs)

        # Request without KEV requirement
        result = enabled_cache.get(
            image_name="nginx:1.25",
            digest=sample_analysis_with_kevs.digest,
            require_kevs=False,
        )
        assert result is None
        assert enabled_cache.misses == 1


class TestCacheHit:
    """Tests for successful cache retrieval."""

    def test_cache_hit_basic(self, enabled_cache, sample_analysis):
        """Successful cache retrieval."""
        enabled_cache.put(sample_analysis)

        result = enabled_cache.get(
            image_name="nginx:1.25",
            digest=sample_analysis.digest,
        )

        assert result is not None
        assert result.name == sample_analysis.name
        assert result.digest == sample_analysis.digest
        assert result.cache_hit is True
        assert enabled_cache.hits == 1

    def test_cache_put_and_get(self, enabled_cache, sample_analysis):
        """Round-trip store and retrieve."""
        enabled_cache.put(sample_analysis)

        result = enabled_cache.get(
            image_name="nginx:1.25",
            digest=sample_analysis.digest,
        )

        assert result is not None
        assert result.size_mb == sample_analysis.size_mb
        assert result.package_count == sample_analysis.package_count
        assert result.vulnerabilities.total == sample_analysis.vulnerabilities.total
        assert result.vulnerabilities.critical == sample_analysis.vulnerabilities.critical

    def test_cache_hit_with_chps(self, enabled_cache, sample_analysis_with_chps):
        """Cache hit preserves CHPS score."""
        enabled_cache.put(sample_analysis_with_chps)

        result = enabled_cache.get(
            image_name="nginx:1.25",
            digest=sample_analysis_with_chps.digest,
            require_chps=True,
        )

        assert result is not None
        assert result.chps_score is not None
        assert result.chps_score.score == 85.0
        assert result.chps_score.grade == "B"
        assert result.chps_score.details == {"test": "value"}

    def test_cache_hit_with_kevs(self, enabled_cache, sample_analysis_with_kevs):
        """Cache hit preserves KEV data."""
        enabled_cache.put(sample_analysis_with_kevs)

        result = enabled_cache.get(
            image_name="nginx:1.25",
            digest=sample_analysis_with_kevs.digest,
            require_kevs=True,
        )

        assert result is not None
        assert result.kev_count == 2
        assert result.kev_cves == ["CVE-2023-1234", "CVE-2023-5678"]


class TestCacheCorruption:
    """Tests for handling corrupted cache files."""

    def test_cache_corrupted_file_invalid_json(self, enabled_cache, sample_analysis):
        """Handles corrupted JSON gracefully."""
        enabled_cache.put(sample_analysis)

        # Corrupt the file with invalid JSON
        cache_path = enabled_cache._get_cache_path(sample_analysis.digest)
        cache_path.write_text("not valid json {{{")

        result = enabled_cache.get(
            image_name="nginx:1.25",
            digest=sample_analysis.digest,
        )

        assert result is None
        assert enabled_cache.misses == 1
        # Corrupted file should be removed
        assert not cache_path.exists()

    def test_cache_corrupted_file_missing_keys(self, enabled_cache, sample_analysis):
        """Handles JSON with missing required keys."""
        enabled_cache.put(sample_analysis)

        # Write JSON with missing keys
        cache_path = enabled_cache._get_cache_path(sample_analysis.digest)
        cache_path.write_text(json.dumps({"digest": sample_analysis.digest}))

        result = enabled_cache.get(
            image_name="nginx:1.25",
            digest=sample_analysis.digest,
        )

        # Should handle gracefully (missing vulnerabilities key)
        assert result is None or result.vulnerabilities is not None


class TestCacheClear:
    """Tests for cache clearing."""

    def test_cache_clear(self, enabled_cache, sample_analysis):
        """Clears all entries."""
        # Add multiple entries
        for i in range(3):
            analysis = ImageAnalysis(
                name=f"image{i}:latest",
                size_mb=100.0,
                package_count=50,
                vulnerabilities=VulnerabilityCount(total=10),
                scan_timestamp=datetime.now(timezone.utc),
                digest=f"sha256:digest{i}",
            )
            enabled_cache.put(analysis)

        # Verify files exist
        cache_files = list(enabled_cache.cache_dir.glob("*.json"))
        assert len(cache_files) == 3

        # Clear cache
        deleted = enabled_cache.clear()

        assert deleted == 3
        cache_files = list(enabled_cache.cache_dir.glob("*.json"))
        assert len(cache_files) == 0

    def test_cache_clear_empty(self, enabled_cache):
        """Clear on empty cache returns 0."""
        deleted = enabled_cache.clear()
        assert deleted == 0

    def test_cache_clear_disabled(self, disabled_cache):
        """Clear when disabled returns 0."""
        deleted = disabled_cache.clear()
        assert deleted == 0


class TestCacheStatistics:
    """Tests for cache statistics."""

    def test_cache_hit_rate_calculation(self, enabled_cache, sample_analysis):
        """hit_rate property calculates correctly."""
        enabled_cache.put(sample_analysis)

        # 1 hit
        enabled_cache.get("nginx:1.25", sample_analysis.digest)
        # 1 miss
        enabled_cache.get("other:latest", "sha256:nonexistent")

        assert enabled_cache.hits == 1
        assert enabled_cache.misses == 1
        assert enabled_cache.hit_rate == 50.0

    def test_cache_hit_rate_no_activity(self, enabled_cache):
        """hit_rate returns 0 when no activity."""
        assert enabled_cache.hit_rate == 0.0

    def test_cache_summary_no_activity(self, enabled_cache):
        """Summary with no hits/misses."""
        assert enabled_cache.summary() == "No cache activity"

    def test_cache_summary_with_activity(self, enabled_cache, sample_analysis):
        """Summary with activity shows stats."""
        enabled_cache.put(sample_analysis)
        enabled_cache.get("nginx:1.25", sample_analysis.digest)
        enabled_cache.get("other:latest", "sha256:nonexistent")

        summary = enabled_cache.summary()
        assert "1 hits" in summary
        assert "1 misses" in summary
        assert "50.0%" in summary


class TestCacheAtomicWrite:
    """Tests for atomic write behavior."""

    def test_cache_atomic_write(self, enabled_cache, sample_analysis):
        """Temp file rename pattern is used."""
        enabled_cache.put(sample_analysis)

        # Check that final file exists and no temp files remain
        cache_path = enabled_cache._get_cache_path(sample_analysis.digest)
        assert cache_path.exists()

        temp_files = list(enabled_cache.cache_dir.glob("*.tmp"))
        assert len(temp_files) == 0

    def test_cache_file_path_sanitization(self, enabled_cache):
        """Cache key is sanitized for filesystem."""
        # Test with characters that need sanitization
        path = enabled_cache._get_cache_path("sha256:abc/def:ghi#jkl")
        assert "/" not in path.name
        assert ":" not in path.name
        assert "#" not in path.name


class TestCacheSetup:
    """Tests for cache initialization."""

    def test_cache_creates_directory(self, tmp_path):
        """Cache creates directory if it doesn't exist."""
        cache_dir = tmp_path / "new_cache_dir"
        assert not cache_dir.exists()

        cache = ScanCache(cache_dir=cache_dir, enabled=True)

        assert cache_dir.exists()
        assert cache.enabled is True

    def test_cache_handles_directory_creation_failure(self, tmp_path):
        """Cache disables itself if directory creation fails."""
        # Create a file where directory should be
        blocker = tmp_path / "blocked"
        blocker.write_text("blocking")

        cache = ScanCache(cache_dir=blocker / "cache", enabled=True)

        # Should disable itself gracefully
        assert cache.enabled is False
