"""
Tests for retry queue functionality.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch

from forge_gauge.core.retry_queue import RetryQueue, FailedImagePull
from forge_gauge.core.scanner import VulnerabilityScanner
from forge_gauge.core.cache import ScanCache
from forge_gauge.core.models import ImagePair
from forge_gauge.utils.docker_utils import DockerClient


class TestRetryQueue:
    """Test retry queue basic operations."""

    def test_empty_queue(self):
        """Test empty queue operations."""
        queue = RetryQueue()
        assert queue.is_empty()
        assert queue.size() == 0
        assert queue.get_all() == []

    def test_add_failed_pull(self):
        """Test adding failed pull to queue."""
        queue = RetryQueue()
        queue.add(
            image="python:3.12",
            platform="linux/amd64",
            error_message="rate limit exceeded",
            error_type="rate_limit",
            context="alternative",
            pair_index=0
        )

        assert not queue.is_empty()
        assert queue.size() == 1

        failed_pulls = queue.get_all()
        assert len(failed_pulls) == 1
        assert failed_pulls[0].image == "python:3.12"
        assert failed_pulls[0].platform == "linux/amd64"
        assert failed_pulls[0].error_message == "rate limit exceeded"
        assert failed_pulls[0].error_type == "rate_limit"
        assert failed_pulls[0].context == "alternative"
        assert failed_pulls[0].pair_index == 0

    def test_multiple_failed_pulls(self):
        """Test adding multiple failed pulls."""
        queue = RetryQueue()

        queue.add(
            image="python:3.12",
            platform="linux/amd64",
            error_message="not found",
            error_type="not_found",
            context="alternative",
            pair_index=0
        )
        queue.add(
            image="node:20",
            platform="linux/amd64",
            error_message="timeout",
            error_type="timeout",
            context="chainguard",
            pair_index=1
        )

        assert queue.size() == 2

        failed_pulls = queue.get_all()
        assert len(failed_pulls) == 2
        assert failed_pulls[0].image == "python:3.12"
        assert failed_pulls[1].image == "node:20"

    def test_clear_queue(self):
        """Test clearing the queue."""
        queue = RetryQueue()
        queue.add("python:3.12", "linux/amd64", "error", "unknown", "alternative")
        queue.add("node:20", "linux/amd64", "error", "unknown", "chainguard")

        assert queue.size() == 2

        queue.clear()

        assert queue.is_empty()
        assert queue.size() == 0

    def test_get_all_returns_copy(self):
        """Test that get_all returns a copy, not the original list."""
        queue = RetryQueue()
        queue.add("python:3.12", "linux/amd64", "error", "unknown", "alternative")

        failed_pulls_1 = queue.get_all()
        failed_pulls_2 = queue.get_all()

        # Should be different list objects
        assert failed_pulls_1 is not failed_pulls_2
        # But should have the same content
        assert len(failed_pulls_1) == len(failed_pulls_2)


class TestScannerRetryIntegration:
    """Test retry queue integration with scanner."""

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
        client.runtime = "docker"
        return client

    @pytest.fixture
    def scanner(self, mock_cache, mock_docker_client):
        """Create a scanner instance with mocked dependencies."""
        with patch('subprocess.run') as mock_run:
            # Mock syft and grype version checks
            mock_run.return_value = Mock(returncode=0)
            scanner = VulnerabilityScanner(
                cache=mock_cache,
                docker_client=mock_docker_client,
                max_workers=2,
                check_fresh_images=True,
                with_chps=False,
            )
        return scanner

    def test_failed_pull_adds_to_retry_queue(self, scanner, mock_docker_client):
        """Test that failed pulls are added to retry queue."""
        # Mock ensure_fresh_image to fail
        mock_docker_client.ensure_fresh_image.return_value = (
            "python:3.12",
            False,
            False,  # pull_successful = False
            "not_found"
        )

        # Attempt to scan image with context
        with pytest.raises(RuntimeError, match="Failed to pull image"):
            scanner.scan_image("python:3.12", context="alternative", pair_index=0)

        # Verify the image was added to retry queue
        assert scanner.retry_queue.size() == 1
        failed_pulls = scanner.retry_queue.get_all()
        assert failed_pulls[0].image == "python:3.12"
        assert failed_pulls[0].context == "alternative"
        assert failed_pulls[0].pair_index == 0

    def test_successful_pull_does_not_add_to_retry_queue(self, scanner, mock_docker_client):
        """Test that successful pulls are not added to retry queue."""
        # Mock successful pull and scan
        mock_docker_client.ensure_fresh_image.return_value = (
            "python:3.12",
            False,
            True,  # pull_successful = True
            "none"
        )
        mock_docker_client.get_image_digest.return_value = "sha256:abc123"
        mock_docker_client.get_image_size_mb.return_value = 100.0

        with patch('subprocess.run') as mock_run:
            # Mock Syft
            syft_result = Mock(
                returncode=0,
                stdout='{"artifacts": [{"name": "test"}]}'
            )
            # Mock Grype
            grype_result = Mock(
                returncode=0,
                stdout='{"matches": []}'
            )
            mock_run.side_effect = [syft_result, grype_result]

            scanner.scan_image("python:3.12", context="alternative", pair_index=0)

        # Verify no images in retry queue
        assert scanner.retry_queue.is_empty()

    def test_retry_queue_integration_with_pairs(self, scanner, mock_docker_client):
        """Test retry queue with parallel pair scanning."""
        pairs = [
            ImagePair(
                alternative_image="python:3.12",
                chainguard_image="cgr.dev/chainguard/python:latest"
            )
        ]

        # Mock first scan to fail
        mock_docker_client.ensure_fresh_image.side_effect = [
            ("python:3.12", False, False, "not_found"),  # First call fails
            ("cgr.dev/chainguard/python:latest", False, True, "none"),  # Second call succeeds
        ]

        # Mock subsequent retry to succeed
        mock_docker_client.pull_image_with_fallback.return_value = (
            "python:3.12",
            False,
            True,
            "none"
        )

        mock_docker_client.get_image_digest.return_value = "sha256:abc123"
        mock_docker_client.get_image_size_mb.return_value = 100.0

        with patch('subprocess.run') as mock_run:
            # Mock successful scans
            syft_result = Mock(
                returncode=0,
                stdout='{"artifacts": [{"name": "test"}]}'
            )
            grype_result = Mock(
                returncode=0,
                stdout='{"matches": []}'
            )
            mock_run.side_effect = [syft_result, grype_result] * 10  # Enough for retries

            results = scanner.scan_image_pairs_parallel(pairs)

        # Should have 1 failed image added to retry queue
        # (This test verifies integration but actual retry logic depends on mocking)
        assert len(results) == 1

    def test_retry_without_context_does_not_add_to_queue(self, scanner, mock_docker_client):
        """Test that failed pulls without context are not added to queue."""
        # Mock ensure_fresh_image to fail
        mock_docker_client.ensure_fresh_image.return_value = (
            "python:3.12",
            False,
            False,  # pull_successful = False
            "not_found"
        )

        # Attempt to scan image WITHOUT context
        with pytest.raises(RuntimeError, match="Failed to pull image"):
            scanner.scan_image("python:3.12")  # No context parameter

        # Verify the image was NOT added to retry queue (no context provided)
        assert scanner.retry_queue.is_empty()
