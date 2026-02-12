"""
Tests for DFC mappings integration.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, mock_open
from datetime import datetime, timedelta, timezone

from forge_gauge.integrations.dfc_mappings import DFCMappings


class TestDFCMappings:
    """Test DFC mappings loading and caching."""

    @pytest.fixture
    def mock_dfc_yaml(self):
        """Mock DFC mappings YAML content."""
        return """
images:
  alpine: chainguard-base:latest
  golang*: go
  nginx: nginx-fips:latest
  python*: python
  node*: node

packages:
  build-essential:
    - build-base
"""

    @pytest.fixture
    def dfc_mappings(self, tmp_path):
        """Create DFCMappings instance with temp cache dir."""
        return DFCMappings(cache_dir=tmp_path)

    def test_load_from_local_file(self, tmp_path, mock_dfc_yaml):
        """Test loading mappings from local file."""
        local_file = tmp_path / "local-mappings.yaml"
        local_file.write_text(mock_dfc_yaml)

        dfc = DFCMappings(local_file=local_file)
        mappings = dfc.load_mappings()

        assert len(mappings) == 5
        assert mappings["alpine"] == "chainguard-base:latest"
        assert mappings["nginx"] == "nginx-fips:latest"

    def test_exact_match(self, tmp_path, mock_dfc_yaml):
        """Test exact image matching."""
        local_file = tmp_path / "mappings.yaml"
        local_file.write_text(mock_dfc_yaml)

        dfc = DFCMappings(local_file=local_file)
        dfc.load_mappings()

        # Exact match
        match = dfc.match_image("alpine:latest")
        assert match == "cgr.dev/chainguard-private/chainguard-base:latest"

    def test_wildcard_match(self, tmp_path, mock_dfc_yaml):
        """Test wildcard pattern matching."""
        local_file = tmp_path / "mappings.yaml"
        local_file.write_text(mock_dfc_yaml)

        dfc = DFCMappings(local_file=local_file)
        dfc.load_mappings()

        # Wildcard matches
        assert dfc.match_image("golang:1.21") == "cgr.dev/chainguard-private/go:latest"
        assert dfc.match_image("python:3.12") == "cgr.dev/chainguard-private/python:latest"
        assert dfc.match_image("node:20") == "cgr.dev/chainguard-private/node:latest"

    def test_no_match(self, tmp_path, mock_dfc_yaml):
        """Test when no match is found."""
        local_file = tmp_path / "mappings.yaml"
        local_file.write_text(mock_dfc_yaml)

        dfc = DFCMappings(local_file=local_file)
        dfc.load_mappings()

        # No match
        assert dfc.match_image("nonexistent:latest") is None

    def test_extract_base_image(self, dfc_mappings):
        """Test base image extraction from full references."""
        assert dfc_mappings._extract_base_image("docker.io/library/python:3.12") == "python"
        assert dfc_mappings._extract_base_image("gcr.io/kaniko-project/executor:latest") == "executor"
        assert dfc_mappings._extract_base_image("nginx:1.25") == "nginx"
        assert dfc_mappings._extract_base_image("python") == "python"

    def test_normalize_chainguard_image(self, dfc_mappings):
        """Test Chainguard image normalization."""
        # Already has registry (preserve existing registry)
        assert dfc_mappings._normalize_chainguard_image("cgr.dev/chainguard/python:latest") == "cgr.dev/chainguard/python:latest"
        assert dfc_mappings._normalize_chainguard_image("cgr.dev/chainguard-private/python:latest") == "cgr.dev/chainguard-private/python:latest"

        # Missing registry - defaults to private registry
        assert dfc_mappings._normalize_chainguard_image("go") == "cgr.dev/chainguard-private/go:latest"
        assert dfc_mappings._normalize_chainguard_image("nginx-fips:latest") == "cgr.dev/chainguard-private/nginx-fips:latest"

    def test_cache_needs_refresh_no_cache(self, dfc_mappings):
        """Test cache refresh when cache doesn't exist."""
        assert dfc_mappings._cache_needs_refresh() is True

    def test_cache_needs_refresh_stale(self, dfc_mappings, tmp_path):
        """Test cache refresh when cache is stale."""
        # Create stale cache file
        cache_file = tmp_path / "dfc-mappings.yaml"
        cache_file.write_text("images: {}")

        # Set modification time to 2 days ago
        two_days_ago = datetime.now(timezone.utc) - timedelta(days=2)
        cache_file.touch()
        import os
        os.utime(cache_file, (two_days_ago.timestamp(), two_days_ago.timestamp()))

        dfc_mappings.cache_file = cache_file
        assert dfc_mappings._cache_needs_refresh() is True

    def test_cache_needs_refresh_fresh(self, dfc_mappings, tmp_path):
        """Test cache refresh when cache is fresh."""
        # Create fresh cache file
        cache_file = tmp_path / "dfc-mappings.yaml"
        cache_file.write_text("images: {}")
        cache_file.touch()

        dfc_mappings.cache_file = cache_file
        assert dfc_mappings._cache_needs_refresh() is False

    @patch('forge_gauge.integrations.dfc_mappings.requests.get')
    def test_fetch_and_cache(self, mock_get, dfc_mappings, mock_dfc_yaml):
        """Test fetching mappings from remote and caching."""
        # Mock successful response
        mock_response = Mock()
        mock_response.text = mock_dfc_yaml
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        dfc_mappings._fetch_and_cache()

        # Verify request was made
        mock_get.assert_called_once()

        # Verify cache was written
        assert dfc_mappings.cache_file.exists()
        assert mock_dfc_yaml in dfc_mappings.cache_file.read_text()

    @patch('forge_gauge.integrations.dfc_mappings.requests.get')
    def test_fetch_and_cache_network_error(self, mock_get, dfc_mappings):
        """Test handling of network errors during fetch."""
        import requests
        mock_get.side_effect = requests.RequestException("Network error")

        with pytest.raises(RuntimeError, match="Failed to fetch DFC mappings"):
            dfc_mappings._fetch_and_cache()

    def test_load_from_file_not_found(self, dfc_mappings, tmp_path):
        """Test error when loading from non-existent file."""
        nonexistent = tmp_path / "nonexistent.yaml"

        with pytest.raises(RuntimeError, match="Mappings file not found"):
            dfc_mappings._load_from_file(nonexistent)

    def test_wildcard_pattern_parsing(self, tmp_path, mock_dfc_yaml):
        """Test wildcard pattern extraction."""
        local_file = tmp_path / "mappings.yaml"
        local_file.write_text(mock_dfc_yaml)

        dfc = DFCMappings(local_file=local_file)
        dfc.load_mappings()

        # Should have 3 wildcard patterns
        assert len(dfc.wildcard_patterns) == 3
        assert ("golang*", "go") in dfc.wildcard_patterns
        assert ("python*", "python") in dfc.wildcard_patterns
        assert ("node*", "node") in dfc.wildcard_patterns
