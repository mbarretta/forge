"""
Tests for version-aware image matching functionality.
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch, MagicMock

from forge_gauge.utils.version_matcher import (
    SemVer,
    VersionMatchResult,
    TagDiscoveryService,
    TagFreshnessChecker,
    VersionMatcher,
)


class TestSemVer:
    """Tests for SemVer parsing and comparison."""

    def test_parse_full_version(self):
        """Test parsing full semantic version."""
        semver = SemVer.parse("1.2.3")
        assert semver is not None
        assert semver.major == 1
        assert semver.minor == 2
        assert semver.patch == 3

    def test_parse_with_v_prefix(self):
        """Test parsing version with 'v' prefix."""
        semver = SemVer.parse("v1.2.3")
        assert semver is not None
        assert semver.major == 1
        assert semver.minor == 2
        assert semver.patch == 3

    def test_parse_with_V_prefix(self):
        """Test parsing version with uppercase 'V' prefix."""
        semver = SemVer.parse("V1.2.3")
        assert semver is not None
        assert semver.major == 1
        assert semver.minor == 2
        assert semver.patch == 3

    def test_parse_major_minor_only(self):
        """Test parsing version with only major.minor."""
        semver = SemVer.parse("1.2")
        assert semver is not None
        assert semver.major == 1
        assert semver.minor == 2
        assert semver.patch == 0

    def test_parse_major_only(self):
        """Test parsing version with only major."""
        semver = SemVer.parse("1")
        assert semver is not None
        assert semver.major == 1
        assert semver.minor == 0
        assert semver.patch == 0

    def test_parse_with_suffix(self):
        """Test parsing version with suffix like -slim."""
        semver = SemVer.parse("3.12-slim")
        assert semver is not None
        assert semver.major == 3
        assert semver.minor == 12
        assert semver.patch == 0

    def test_parse_with_alpine_suffix(self):
        """Test parsing version with -alpine suffix."""
        semver = SemVer.parse("1.27.0-alpine")
        assert semver is not None
        assert semver.major == 1
        assert semver.minor == 27
        assert semver.patch == 0

    def test_parse_invalid_returns_none(self):
        """Test that invalid versions return None."""
        assert SemVer.parse("latest") is None
        assert SemVer.parse("edge") is None
        assert SemVer.parse("alpine") is None
        assert SemVer.parse("") is None

    def test_parse_non_semver_returns_none(self):
        """Test that non-semver strings return None."""
        assert SemVer.parse("abc") is None
        assert SemVer.parse("1.2.3.4") is None
        assert SemVer.parse("-") is None

    def test_parse_with_rc_suffix(self):
        """Test that -rc suffix is stripped and version parses."""
        # -rc1 is stripped, leaving 1.2.3
        semver = SemVer.parse("1.2.3-rc1")
        assert semver is not None
        assert semver.major == 1
        assert semver.minor == 2
        assert semver.patch == 3

    def test_matches_minor_same(self):
        """Test matches_minor with same major.minor."""
        v1 = SemVer(1, 27, 0)
        v2 = SemVer(1, 27, 5)
        assert v1.matches_minor(v2) is True
        assert v2.matches_minor(v1) is True

    def test_matches_minor_different_minor(self):
        """Test matches_minor with different minor."""
        v1 = SemVer(1, 27, 0)
        v2 = SemVer(1, 28, 0)
        assert v1.matches_minor(v2) is False

    def test_matches_minor_different_major(self):
        """Test matches_minor with different major."""
        v1 = SemVer(1, 27, 0)
        v2 = SemVer(2, 27, 0)
        assert v1.matches_minor(v2) is False

    def test_comparison_operators(self):
        """Test SemVer comparison operators."""
        v1 = SemVer(1, 0, 0)
        v2 = SemVer(1, 1, 0)
        v3 = SemVer(1, 1, 1)
        v4 = SemVer(2, 0, 0)

        assert v1 < v2 < v3 < v4
        assert v4 > v3 > v2 > v1
        assert v1 == SemVer(1, 0, 0)
        assert v1 != v2

    def test_str_representation(self):
        """Test SemVer string representation."""
        semver = SemVer(1, 27, 5)
        assert str(semver) == "1.27.5"

    def test_sorting(self):
        """Test SemVer list sorting."""
        versions = [
            SemVer(1, 0, 0),
            SemVer(2, 1, 0),
            SemVer(1, 1, 0),
            SemVer(2, 0, 0),
        ]
        sorted_versions = sorted(versions, reverse=True)
        assert sorted_versions == [
            SemVer(2, 1, 0),
            SemVer(2, 0, 0),
            SemVer(1, 1, 0),
            SemVer(1, 0, 0),
        ]


class TestTagDiscoveryService:
    """Tests for TagDiscoveryService."""

    @pytest.fixture
    def tag_discovery(self):
        """Create a TagDiscoveryService instance."""
        return TagDiscoveryService()

    @patch("subprocess.run")
    def test_list_tags_success(self, mock_run, tag_discovery):
        """Test successful tag listing."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout='{"Tags": ["1.0.0", "1.1.0", "2.0.0", "latest"]}',
        )

        tags = tag_discovery.list_tags("cgr.dev/chainguard-private/nginx")

        assert tags == ["1.0.0", "1.1.0", "2.0.0", "latest"]
        # Called twice: once for skopeo version check, once for list-tags
        assert mock_run.call_count == 2

    @patch("subprocess.run")
    def test_list_tags_skopeo_failure(self, mock_run, tag_discovery):
        """Test handling of skopeo failure."""
        mock_run.return_value = Mock(
            returncode=1,
            stderr="error: image not found",
        )

        tags = tag_discovery.list_tags("cgr.dev/chainguard-private/nonexistent")

        assert tags == []

    @patch("subprocess.run")
    def test_list_tags_caching(self, mock_run, tag_discovery):
        """Test that tag listing results are cached."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout='{"Tags": ["1.0.0", "2.0.0"]}',
        )

        # First call
        tags1 = tag_discovery.list_tags("cgr.dev/chainguard-private/nginx")
        # Second call (should use cache)
        tags2 = tag_discovery.list_tags("cgr.dev/chainguard-private/nginx")

        assert tags1 == tags2
        # Should call skopeo twice: version check + list-tags (second call uses cache)
        assert mock_run.call_count == 2

    @patch("subprocess.run")
    def test_get_semver_tags(self, mock_run, tag_discovery):
        """Test getting semver-parseable tags."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout='{"Tags": ["1.0.0", "v1.1.0", "2.0.0", "latest", "edge", "1.2"]}',
        )

        semvers = tag_discovery.get_semver_tags("cgr.dev/chainguard-private/nginx")

        # Should be sorted descending
        assert semvers[0] == SemVer(2, 0, 0)
        assert SemVer(1, 2, 0) in semvers
        assert len(semvers) == 4  # Excludes "latest" and "edge"

    @patch("subprocess.run")
    def test_skopeo_not_available(self, mock_run, tag_discovery):
        """Test handling when skopeo is not available."""
        mock_run.side_effect = FileNotFoundError("skopeo not found")
        tag_discovery._skopeo_available = None  # Reset cached state

        tags = tag_discovery.list_tags("cgr.dev/chainguard-private/nginx")

        assert tags == []


class TestTagFreshnessChecker:
    """Tests for TagFreshnessChecker."""

    @pytest.fixture
    def freshness_checker(self):
        """Create a TagFreshnessChecker instance."""
        return TagFreshnessChecker()

    def test_get_created_date_with_injected_function(self):
        """Test get_created_date with injected label function."""
        def mock_get_label(image, label):
            return "2025-01-20T12:00:00Z"

        checker = TagFreshnessChecker(get_label_func=mock_get_label)
        created = checker.get_created_date("cgr.dev/chainguard-private/nginx:1.27.0")

        assert created is not None
        assert created.year == 2025
        assert created.month == 1
        assert created.day == 20

    def test_get_created_date_with_timezone(self):
        """Test parsing timestamps with timezone info."""
        def mock_get_label(image, label):
            return "2025-01-20T12:00:00+00:00"

        checker = TagFreshnessChecker(get_label_func=mock_get_label)
        created = checker.get_created_date("cgr.dev/chainguard-private/nginx:1.27.0")

        assert created is not None
        assert created.tzinfo is not None

    def test_get_created_date_invalid(self):
        """Test handling of invalid timestamps."""
        def mock_get_label(image, label):
            return "not-a-date"

        checker = TagFreshnessChecker(get_label_func=mock_get_label)
        created = checker.get_created_date("cgr.dev/chainguard-private/nginx:1.27.0")

        assert created is None

    def test_get_created_date_missing(self):
        """Test handling of missing label."""
        def mock_get_label(image, label):
            return None

        checker = TagFreshnessChecker(get_label_func=mock_get_label)
        created = checker.get_created_date("cgr.dev/chainguard-private/nginx:1.27.0")

        assert created is None

    def test_is_fresh_recent_image(self):
        """Test is_fresh with a recently built image."""
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(days=3)).isoformat()

        def mock_get_label(image, label):
            return recent

        checker = TagFreshnessChecker(get_label_func=mock_get_label)
        is_fresh = checker.is_fresh("cgr.dev/chainguard-private/nginx:1.27.0", threshold_days=7)

        assert is_fresh is True

    def test_is_fresh_stale_image(self):
        """Test is_fresh with a stale image."""
        now = datetime.now(timezone.utc)
        old = (now - timedelta(days=30)).isoformat()

        def mock_get_label(image, label):
            return old

        checker = TagFreshnessChecker(get_label_func=mock_get_label)
        is_fresh = checker.is_fresh("cgr.dev/chainguard-private/nginx:1.27.0", threshold_days=7)

        assert is_fresh is False

    def test_is_fresh_unknown_date_assumes_fresh(self):
        """Test that unknown creation date assumes fresh."""
        def mock_get_label(image, label):
            return None

        checker = TagFreshnessChecker(get_label_func=mock_get_label)
        is_fresh = checker.is_fresh("cgr.dev/chainguard-private/nginx:1.27.0")

        # Should assume fresh when date is unknown
        assert is_fresh is True

    def test_caching(self):
        """Test that freshness check results are cached."""
        call_count = 0

        def mock_get_label(image, label):
            nonlocal call_count
            call_count += 1
            return "2025-01-20T12:00:00Z"

        checker = TagFreshnessChecker(get_label_func=mock_get_label)

        # Call twice
        checker.get_created_date("cgr.dev/chainguard-private/nginx:1.27.0")
        checker.get_created_date("cgr.dev/chainguard-private/nginx:1.27.0")

        # Should only call the underlying function once
        assert call_count == 1


class TestVersionMatcher:
    """Tests for VersionMatcher."""

    @pytest.fixture
    def mock_tag_discovery(self):
        """Create a mock TagDiscoveryService."""
        mock = Mock(spec=TagDiscoveryService)
        mock.get_semver_tags.return_value = [
            SemVer(1, 27, 5),
            SemVer(1, 27, 4),
            SemVer(1, 27, 3),
            SemVer(1, 26, 2),
            SemVer(1, 26, 1),
        ]
        return mock

    @pytest.fixture
    def mock_freshness_checker(self):
        """Create a mock TagFreshnessChecker that always returns fresh."""
        mock = Mock(spec=TagFreshnessChecker)
        mock.is_fresh.return_value = True
        return mock

    @pytest.fixture
    def version_matcher(self, mock_tag_discovery, mock_freshness_checker):
        """Create a VersionMatcher with mocked dependencies."""
        return VersionMatcher(
            tag_discovery=mock_tag_discovery,
            freshness_checker=mock_freshness_checker,
        )

    def test_resolve_latest_passthrough(self, version_matcher):
        """Test that 'latest' tag passes through unchanged."""
        result = version_matcher.resolve(
            "nginx:latest",
            "cgr.dev/chainguard-private/nginx"
        )

        assert result.resolved_tag == "latest"
        assert result.is_eol_fallback is False

    def test_resolve_empty_tag_uses_latest(self, version_matcher):
        """Test that empty tag resolves to 'latest'."""
        result = version_matcher.resolve(
            "nginx",
            "cgr.dev/chainguard-private/nginx"
        )

        assert result.resolved_tag == "latest"

    def test_resolve_digest_reference_uses_latest(self, version_matcher):
        """Test that digest references resolve to 'latest'."""
        result = version_matcher.resolve(
            "nginx@sha256:abc123",
            "cgr.dev/chainguard-private/nginx"
        )

        assert result.resolved_tag == "latest"

    def test_resolve_non_semver_uses_latest(self, version_matcher):
        """Test that non-semver tags resolve to 'latest'."""
        result = version_matcher.resolve(
            "alpine:edge",
            "cgr.dev/chainguard-private/alpine"
        )

        assert result.resolved_tag == "latest"

    def test_resolve_matches_major_minor(self, version_matcher, mock_tag_discovery):
        """Test resolution to latest patch of matching major.minor."""
        result = version_matcher.resolve(
            "nginx:1.27.0",
            "cgr.dev/chainguard-private/nginx"
        )

        # Should match to 1.27.5 (latest 1.27.x)
        assert result.resolved_tag == "1.27.5"
        assert result.source_version == SemVer(1, 27, 0)
        assert result.matched_version == SemVer(1, 27, 5)
        assert result.is_eol_fallback is False

    def test_resolve_matches_older_minor(self, version_matcher, mock_tag_discovery):
        """Test resolution with older minor version."""
        result = version_matcher.resolve(
            "nginx:1.26.0",
            "cgr.dev/chainguard-private/nginx"
        )

        # Should match to 1.26.2 (latest 1.26.x)
        assert result.resolved_tag == "1.26.2"
        assert result.is_eol_fallback is False

    def test_resolve_eol_fallback_when_no_minor_match(self, version_matcher, mock_tag_discovery):
        """Test EOL fallback when source major.minor doesn't exist."""
        result = version_matcher.resolve(
            "nginx:1.25.0",  # 1.25 doesn't exist in mock
            "cgr.dev/chainguard-private/nginx"
        )

        # Should fallback to latest (1.27.5)
        assert result.resolved_tag == "1.27.5"
        assert result.is_eol_fallback is True

    def test_resolve_eol_fallback_when_stale(self, version_matcher, mock_tag_discovery, mock_freshness_checker):
        """Test EOL fallback when matched version is stale."""
        # Make 1.27.x stale, but 1.26.x fresh
        def is_fresh_side_effect(image_ref, threshold_days=7):
            if "1.27" in image_ref:
                return False
            return True

        mock_freshness_checker.is_fresh.side_effect = is_fresh_side_effect

        result = version_matcher.resolve(
            "nginx:1.27.0",
            "cgr.dev/chainguard-private/nginx"
        )

        # Should have tried 1.27.5, found it stale, and fallen back to 1.26.2
        assert result.resolved_tag == "1.26.2"
        assert result.is_eol_fallback is True

    def test_resolve_no_semver_tags_available(self, version_matcher, mock_tag_discovery):
        """Test when no semver tags are available on cgr.dev."""
        mock_tag_discovery.get_semver_tags.return_value = []

        result = version_matcher.resolve(
            "nginx:1.27.0",
            "cgr.dev/chainguard-private/nginx"
        )

        assert result.resolved_tag == "latest"
        assert result.source_version == SemVer(1, 27, 0)

    def test_resolve_with_v_prefix(self, version_matcher):
        """Test resolution with v-prefixed source version."""
        result = version_matcher.resolve(
            "nginx:v1.27.0",
            "cgr.dev/chainguard-private/nginx"
        )

        assert result.resolved_tag == "1.27.5"
        assert result.source_version == SemVer(1, 27, 0)

    def test_resolve_with_suffix(self, version_matcher):
        """Test resolution with suffixed source version."""
        result = version_matcher.resolve(
            "python:3.12-slim",
            "cgr.dev/chainguard-private/python"
        )

        # Should parse 3.12 from 3.12-slim
        assert result.source_version == SemVer(3, 12, 0)

    def test_extract_tag_from_full_reference(self, version_matcher):
        """Test tag extraction from various image references."""
        assert version_matcher._extract_tag("nginx:1.27.0") == "1.27.0"
        assert version_matcher._extract_tag("docker.io/library/nginx:1.27.0") == "1.27.0"
        assert version_matcher._extract_tag("cgr.dev/chainguard-private/nginx:latest") == "latest"
        assert version_matcher._extract_tag("localhost:5000/nginx:1.0") == "1.0"
        assert version_matcher._extract_tag("nginx") is None


class TestVersionMatcherIntegration:
    """Integration tests for VersionMatcher with realistic scenarios."""

    def test_elasticsearch_eol_fallback(self):
        """Test elasticsearch 7.x EOL fallback to 8.x."""
        mock_discovery = Mock(spec=TagDiscoveryService)
        mock_discovery.get_semver_tags.return_value = [
            SemVer(8, 19, 11),
            SemVer(8, 19, 10),
            SemVer(8, 18, 0),
            # Note: no 7.x versions
        ]

        mock_freshness = Mock(spec=TagFreshnessChecker)
        mock_freshness.is_fresh.return_value = True

        matcher = VersionMatcher(
            tag_discovery=mock_discovery,
            freshness_checker=mock_freshness,
        )

        result = matcher.resolve(
            "elasticsearch:7.17.29",
            "cgr.dev/chainguard-private/elasticsearch"
        )

        # Should fallback to latest 8.x since 7.x doesn't exist
        assert result.resolved_tag == "8.19.11"
        assert result.is_eol_fallback is True

    def test_python_version_matching(self):
        """Test Python version matching with suffix handling."""
        mock_discovery = Mock(spec=TagDiscoveryService)
        mock_discovery.get_semver_tags.return_value = [
            SemVer(3, 13, 1),
            SemVer(3, 13, 0),
            SemVer(3, 12, 8),
            SemVer(3, 12, 7),
            SemVer(3, 11, 10),
        ]

        mock_freshness = Mock(spec=TagFreshnessChecker)
        mock_freshness.is_fresh.return_value = True

        matcher = VersionMatcher(
            tag_discovery=mock_discovery,
            freshness_checker=mock_freshness,
        )

        result = matcher.resolve(
            "python:3.12-slim-bookworm",
            "cgr.dev/chainguard-private/python"
        )

        # Should extract 3.12 and match to 3.12.8
        assert result.resolved_tag == "3.12.8"
        assert result.source_version == SemVer(3, 12, 0)
        assert result.is_eol_fallback is False
