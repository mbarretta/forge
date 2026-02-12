"""Tests for image classifier."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from forge_gauge.core.models import ImageTier
from forge_gauge.utils.image_classifier import ImageClassifier
from forge_gauge.integrations.github_metadata import GitHubMetadataClient


class TestImageClassifierInitialization:
    """Tests for ImageClassifier initialization and token handling."""

    def test_explicit_token_creates_github_client(self):
        """Test that explicit token creates GitHub client."""
        classifier = ImageClassifier(github_token="explicit_token", auto_update=False)

        assert classifier.github_client is not None
        assert classifier.github_client.token == "explicit_token"

    @patch("integrations.github_metadata.get_github_token_from_gh_cli")
    def test_no_explicit_token_still_creates_github_client(self, mock_gh_cli):
        """Test that passing None for token still creates client (which will try to get token)."""
        mock_gh_cli.return_value = "cli_token"

        with patch.dict("os.environ", {}, clear=True):
            import os
            if "GITHUB_TOKEN" in os.environ:
                del os.environ["GITHUB_TOKEN"]

            classifier = ImageClassifier(github_token=None, auto_update=False)

            # Should create client even with None token
            assert classifier.github_client is not None
            assert classifier.github_client.token == "cli_token"

    @patch("integrations.github_metadata.get_github_token_from_gh_cli")
    @patch.dict("os.environ", {"GITHUB_TOKEN": "env_token"})
    def test_none_token_uses_env_var(self, mock_gh_cli):
        """Test that None token allows GitHubMetadataClient to use env var."""
        mock_gh_cli.return_value = None

        classifier = ImageClassifier(github_token=None, auto_update=False)

        assert classifier.github_client is not None
        assert classifier.github_client.token == "env_token"

    @patch("integrations.github_metadata.get_github_token_from_gh_cli")
    def test_none_token_uses_gh_cli(self, mock_gh_cli):
        """Test that None token allows GitHubMetadataClient to use gh CLI."""
        mock_gh_cli.return_value = "from_gh_cli"

        with patch.dict("os.environ", {}, clear=True):
            import os
            if "GITHUB_TOKEN" in os.environ:
                del os.environ["GITHUB_TOKEN"]

            classifier = ImageClassifier(github_token=None, auto_update=False)

            assert classifier.github_client is not None
            assert classifier.github_client.token == "from_gh_cli"


class TestImageClassifierTokenPassing:
    """Tests for token passing through the classification stack."""

    @patch("integrations.github_metadata.get_github_token_from_gh_cli")
    def test_token_flows_through_stack(self, mock_gh_cli):
        """Test that token properly flows from CLI -> ImageClassifier -> GitHubMetadataClient."""
        mock_gh_cli.return_value = "test_token"

        with patch.dict("os.environ", {}, clear=True):
            import os
            if "GITHUB_TOKEN" in os.environ:
                del os.environ["GITHUB_TOKEN"]

            # Simulate what happens in CLI
            # 1. Early validation creates a client to check auth
            validation_client = GitHubMetadataClient()
            assert validation_client.token == "test_token"

            # 2. Later, we create ImageClassifier with None (expecting it to get token)
            classifier = ImageClassifier(github_token=None, auto_update=False)
            assert classifier.github_client is not None
            assert classifier.github_client.token == "test_token"

    def test_explicit_token_overrides_all_sources(self):
        """Test that explicit token takes precedence over all other sources."""
        with patch.dict("os.environ", {"GITHUB_TOKEN": "env_token"}):
            with patch("integrations.github_metadata.get_github_token_from_gh_cli", return_value="cli_token"):
                classifier = ImageClassifier(github_token="explicit_token", auto_update=False)

                assert classifier.github_client.token == "explicit_token"


class TestImageClassifierGitHubFallback:
    """Tests for GitHub fallback behavior."""

    @patch("integrations.github_metadata.get_github_token_from_gh_cli")
    def test_get_tier_fails_without_token_and_auto_update(self, mock_gh_cli):
        """Test that get_image_tier fails gracefully when no token and auto_update enabled."""
        mock_gh_cli.return_value = None

        with patch.dict("os.environ", {}, clear=True):
            import os
            if "GITHUB_TOKEN" in os.environ:
                del os.environ["GITHUB_TOKEN"]

            classifier = ImageClassifier(github_token=None, auto_update=True)

            # Should fail because no token available
            with pytest.raises(ValueError) as exc_info:
                classifier.get_image_tier("unknown-image")

            assert "no github token provided" in str(exc_info.value).lower()

    def test_get_tier_fails_without_token_when_disabled(self):
        """Test that get_image_tier fails when auto_update disabled and image not in cache."""
        with patch("integrations.github_metadata.get_github_token_from_gh_cli", return_value=None):
            with patch.dict("os.environ", {}, clear=True):
                import os
                if "GITHUB_TOKEN" in os.environ:
                    del os.environ["GITHUB_TOKEN"]

                classifier = ImageClassifier(github_token=None, auto_update=False)

                # Should fail because auto_update is disabled
                with pytest.raises(ValueError) as exc_info:
                    classifier.get_image_tier("unknown-image")

                assert "not found in tier mappings" in str(exc_info.value)
                assert "auto_update is disabled" in str(exc_info.value)
