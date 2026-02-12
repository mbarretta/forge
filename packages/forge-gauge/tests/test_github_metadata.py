"""Tests for GitHub metadata integration."""

import pytest
import subprocess
from unittest.mock import patch, MagicMock

from forge_gauge.integrations.github_metadata import (
    get_github_token_from_gh_cli,
    GitHubMetadataClient,
)


class TestGitHubTokenRetrieval:
    """Tests for get_github_token_from_gh_cli function."""

    @patch("subprocess.run")
    def test_successful_token_retrieval(self, mock_run):
        """Test successful token retrieval from gh CLI."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="gho_test_token_1234567890\n",
        )

        token = get_github_token_from_gh_cli()

        assert token == "gho_test_token_1234567890"
        mock_run.assert_called_once_with(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=5,
        )

    @patch("subprocess.run")
    def test_gh_not_installed(self, mock_run):
        """Test when gh CLI is not installed."""
        mock_run.side_effect = FileNotFoundError()

        token = get_github_token_from_gh_cli()

        assert token is None

    @patch("subprocess.run")
    def test_gh_not_authenticated(self, mock_run):
        """Test when gh CLI is installed but not authenticated."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
        )

        token = get_github_token_from_gh_cli()

        assert token is None

    @patch("subprocess.run")
    def test_gh_timeout(self, mock_run):
        """Test when gh CLI times out."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["gh"], timeout=5)

        token = get_github_token_from_gh_cli()

        assert token is None

    @patch("subprocess.run")
    def test_empty_token(self, mock_run):
        """Test when gh CLI returns empty token."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
        )

        token = get_github_token_from_gh_cli()

        assert token is None

    @patch("subprocess.run")
    def test_whitespace_only_token(self, mock_run):
        """Test when gh CLI returns only whitespace."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="   \n\t  ",
        )

        token = get_github_token_from_gh_cli()

        assert token is None


class TestGitHubMetadataClient:
    """Tests for GitHubMetadataClient class."""

    def test_explicit_token_takes_priority(self):
        """Test that explicitly provided token takes priority."""
        client = GitHubMetadataClient(github_token="explicit_token")

        assert client.token == "explicit_token"
        assert "Authorization" in client.headers
        assert client.headers["Authorization"] == "token explicit_token"

    @patch.dict("os.environ", {"GITHUB_TOKEN": "env_token"})
    @patch("forge_gauge.integrations.github_metadata.get_github_token_from_gh_cli")
    def test_env_var_token_second_priority(self, mock_gh_cli):
        """Test that env var token is used if no explicit token."""
        mock_gh_cli.return_value = "cli_token"

        client = GitHubMetadataClient()

        assert client.token == "env_token"

    @patch.dict("os.environ", {}, clear=True)
    @patch("forge_gauge.integrations.github_metadata.get_github_token_from_gh_cli")
    def test_gh_cli_token_third_priority(self, mock_gh_cli):
        """Test that gh CLI token is used if no explicit or env var token."""
        mock_gh_cli.return_value = "cli_token"

        # Ensure GITHUB_TOKEN not in env
        import os
        if "GITHUB_TOKEN" in os.environ:
            del os.environ["GITHUB_TOKEN"]

        client = GitHubMetadataClient()

        assert client.token == "cli_token"
        mock_gh_cli.assert_called_once()

    @patch.dict("os.environ", {}, clear=True)
    @patch("forge_gauge.integrations.github_metadata.get_github_token_from_gh_cli")
    def test_no_token_available(self, mock_gh_cli, caplog):
        """Test behavior when no token is available."""
        mock_gh_cli.return_value = None

        # Ensure GITHUB_TOKEN not in env
        import os
        if "GITHUB_TOKEN" in os.environ:
            del os.environ["GITHUB_TOKEN"]

        client = GitHubMetadataClient()

        assert client.token is None
        assert "Authorization" not in client.headers

        # Check that warning was logged
        assert any("No GitHub token found" in record.message for record in caplog.records)
        assert any("gh auth login" in record.message for record in caplog.records)

    def test_headers_with_token(self):
        """Test that headers are correctly set with token."""
        client = GitHubMetadataClient(github_token="test_token")

        assert client.headers["Accept"] == "application/vnd.github.v3.raw"
        assert client.headers["Authorization"] == "token test_token"

    def test_headers_without_token(self):
        """Test that Authorization header is not set without token."""
        with patch("forge_gauge.integrations.github_metadata.get_github_token_from_gh_cli", return_value=None):
            with patch.dict("os.environ", {}, clear=True):
                import os
                if "GITHUB_TOKEN" in os.environ:
                    del os.environ["GITHUB_TOKEN"]

                client = GitHubMetadataClient()

                assert client.headers["Accept"] == "application/vnd.github.v3.raw"
                assert "Authorization" not in client.headers

    @patch("forge_gauge.integrations.github_metadata.get_github_token_from_gh_cli")
    def test_token_fallback_chain(self, mock_gh_cli):
        """Test complete token fallback chain."""
        mock_gh_cli.return_value = "cli_fallback"

        # Test 1: Explicit token wins
        client = GitHubMetadataClient(github_token="explicit")
        assert client.token == "explicit"

        # Test 2: Env var wins over gh CLI
        with patch.dict("os.environ", {"GITHUB_TOKEN": "from_env"}):
            client = GitHubMetadataClient()
            assert client.token == "from_env"

        # Test 3: gh CLI used when nothing else available
        with patch.dict("os.environ", {}, clear=True):
            import os
            if "GITHUB_TOKEN" in os.environ:
                del os.environ["GITHUB_TOKEN"]

            client = GitHubMetadataClient()
            assert client.token == "cli_fallback"
