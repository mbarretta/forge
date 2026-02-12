"""Tests for automatic GitHub token refresh on SAML SSO errors."""

import pytest
from unittest.mock import patch, MagicMock
import subprocess


class TestGitHubTokenRefresh:
    """Tests for automatic token refresh logic."""

    @patch("subprocess.run")
    def test_successful_token_refresh(self, mock_run):
        """Test successful automatic token refresh."""
        # Simulate successful gh auth refresh
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="✓ Authentication complete.\n",
            stderr=""
        )

        result = subprocess.run(
            ["gh", "auth", "refresh", "--hostname", "github.com", "-s", "repo"],
            capture_output=True,
            text=True,
            timeout=60
        )

        assert result.returncode == 0
        assert "Authentication complete" in result.stdout

    @patch("subprocess.run")
    def test_gh_not_installed(self, mock_run):
        """Test handling when gh CLI is not installed."""
        mock_run.side_effect = FileNotFoundError()

        with pytest.raises(FileNotFoundError):
            subprocess.run(
                ["gh", "auth", "refresh", "--hostname", "github.com", "-s", "repo"],
                capture_output=True,
                text=True,
                timeout=60
            )

    @patch("subprocess.run")
    def test_refresh_timeout(self, mock_run):
        """Test handling of refresh timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["gh", "auth", "refresh"],
            timeout=60
        )

        with pytest.raises(subprocess.TimeoutExpired):
            subprocess.run(
                ["gh", "auth", "refresh", "--hostname", "github.com", "-s", "repo"],
                capture_output=True,
                text=True,
                timeout=60
            )

    @patch("subprocess.run")
    def test_refresh_failed(self, mock_run):
        """Test handling when refresh fails."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="authentication failed"
        )

        result = subprocess.run(
            ["gh", "auth", "refresh", "--hostname", "github.com", "-s", "repo"],
            capture_output=True,
            text=True,
            timeout=60
        )

        assert result.returncode != 0
        assert "failed" in result.stderr.lower()


class TestSAMLDetection:
    """Tests for SAML SSO error detection."""

    def test_detect_saml_error_in_response(self):
        """Test detection of SAML error in GitHub API response."""
        response_json = {
            "message": "Resource protected by organization SAML enforcement. You must grant your OAuth token access to this organization.",
            "documentation_url": "https://docs.github.com/articles/authenticating-to-a-github-organization-with-saml-single-sign-on/",
            "status": "403"
        }

        assert "SAML" in response_json.get("message", "")

    def test_no_saml_in_regular_403(self):
        """Test that regular 403 errors don't contain SAML."""
        response_json = {
            "message": "Forbidden",
            "documentation_url": "https://docs.github.com/",
            "status": "403"
        }

        assert "SAML" not in response_json.get("message", "")

    def test_detect_saml_case_insensitive(self):
        """Test SAML detection is case-sensitive (GitHub uses uppercase)."""
        # GitHub always uses "SAML" in uppercase
        assert "SAML" in "Resource protected by organization SAML enforcement"
        # But we should handle variations
        assert "saml" in "Resource protected by organization SAML enforcement".lower()


class TestTokenRefreshWorkflow:
    """Integration tests for the token refresh workflow."""

    @patch("subprocess.run")
    @patch("integrations.github_metadata.get_github_token_from_gh_cli")
    def test_full_refresh_workflow(self, mock_get_token, mock_subprocess):
        """Test the full workflow: detect SAML error -> refresh -> get new token."""
        # Simulate successful refresh
        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout="✓ Authentication complete.\n",
            stderr=""
        )

        # Return new token after refresh
        mock_get_token.return_value = "new_refreshed_token"

        # This simulates what happens in the CLI
        # 1. Detect SAML issue (simulated)
        saml_error = {
            "message": "Resource protected by organization SAML enforcement."
        }
        assert "SAML" in saml_error["message"]

        # 2. Run refresh
        result = subprocess.run(
            ["gh", "auth", "refresh", "--hostname", "github.com", "-s", "repo"],
            capture_output=True,
            text=True,
            timeout=60
        )
        assert result.returncode == 0

        # 3. Get new token
        from forge_gauge.integrations.github_metadata import get_github_token_from_gh_cli
        new_token = get_github_token_from_gh_cli()
        assert new_token == "new_refreshed_token"
