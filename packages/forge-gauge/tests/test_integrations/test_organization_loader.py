"""Tests for OrganizationImageLoader."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, Mock

from forge_gauge.integrations.organization_loader import (
    OrganizationImageLoader,
    is_support_identity,
    has_org_pull_access,
    get_support_identity_id,
    login_as_support,
    restore_normal_identity,
)
from forge_gauge.utils.chainctl_auth import (
    CHAINGUARD_SUPPORT_UIDP,
    clear_auth_status_cache,
    clear_token_cache,
)
from forge_gauge.core.models import ImagePair


@pytest.fixture(autouse=True)
def clear_chainctl_cache():
    """Clear chainctl auth caches before each test."""
    clear_auth_status_cache()
    clear_token_cache()
    yield
    clear_auth_status_cache()
    clear_token_cache()


class TestIsSupportIdentity:
    """Tests for is_support_identity() function."""

    def test_support_identity_detected(self):
        """Test detection when authenticated as support identity."""
        with patch('forge_gauge.utils.chainctl_auth.subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                returncode=0,
                stdout=json.dumps({
                    "identity": f"{CHAINGUARD_SUPPORT_UIDP}/e344969dd3872dbf",
                    "email": "user@example.com",
                }),
            )

            result = is_support_identity()

            assert result is True

    def test_normal_identity_not_detected(self):
        """Test that normal identities are not detected as support."""
        with patch('forge_gauge.utils.chainctl_auth.subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                returncode=0,
                stdout=json.dumps({
                    "identity": "f0cf7a000ed99dfa65d97a3874348e381c5edb0c",
                    "email": "user@example.com",
                }),
            )

            result = is_support_identity()

            assert result is False

    def test_chainctl_not_available(self):
        """Test handling when chainctl is not available."""
        with patch('forge_gauge.utils.chainctl_auth.shutil.which') as mock_which:
            mock_which.return_value = None

            result = is_support_identity()

            assert result is False

    def test_chainctl_auth_fails(self):
        """Test handling when chainctl auth status fails."""
        with patch('forge_gauge.utils.chainctl_auth.subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                returncode=1,
                stdout="",
                stderr="not authenticated",
            )

            result = is_support_identity()

            assert result is False

    def test_invalid_json_response(self):
        """Test handling of invalid JSON from chainctl."""
        with patch('forge_gauge.utils.chainctl_auth.subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                returncode=0,
                stdout="not json",
            )

            result = is_support_identity()

            assert result is False


class TestHasOrgPullAccess:
    """Tests for has_org_pull_access() function."""

    def test_has_access_with_viewer_role(self):
        """Test detection when user has viewer role on org."""
        with patch('forge_gauge.utils.chainctl_auth.subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                returncode=0,
                stdout=json.dumps({
                    "identity": "abc123",
                    "capabilities": {
                        "test-org": "viewer",
                        "other-org": "owner",
                    },
                }),
            )

            result = has_org_pull_access("test-org")

            assert result is True

    def test_has_access_with_owner_role(self):
        """Test detection when user has owner role on org."""
        with patch('forge_gauge.utils.chainctl_auth.subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                returncode=0,
                stdout=json.dumps({
                    "identity": "abc123",
                    "capabilities": {
                        "test-org": "owner",
                    },
                }),
            )

            result = has_org_pull_access("test-org")

            assert result is True

    def test_no_access_org_not_in_capabilities(self):
        """Test detection when org is not in user's capabilities."""
        with patch('forge_gauge.utils.chainctl_auth.subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                returncode=0,
                stdout=json.dumps({
                    "identity": "abc123",
                    "capabilities": {
                        "other-org": "viewer",
                    },
                }),
            )

            result = has_org_pull_access("test-org")

            assert result is False

    def test_no_access_empty_capabilities(self):
        """Test detection when user has no capabilities."""
        with patch('forge_gauge.utils.chainctl_auth.subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                returncode=0,
                stdout=json.dumps({
                    "identity": "abc123",
                    "capabilities": {},
                }),
            )

            result = has_org_pull_access("test-org")

            assert result is False

    def test_chainctl_fails(self):
        """Test handling when chainctl command fails."""
        with patch('forge_gauge.utils.chainctl_auth.subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                returncode=1,
                stdout="",
                stderr="error",
            )

            result = has_org_pull_access("test-org")

            assert result is False


class TestGetSupportIdentityId:
    """Tests for get_support_identity_id() function."""

    def test_support_identity_found(self):
        """Test successful lookup of support identity."""
        with patch('forge_gauge.utils.chainctl_auth.subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                returncode=0,
                stdout=f"{CHAINGUARD_SUPPORT_UIDP}/abc123def456\n",
                stderr="",
            )

            result = get_support_identity_id("test-org")

            assert result == f"{CHAINGUARD_SUPPORT_UIDP}/abc123def456"
            # Verify correct command was called
            call_args = mock_run.call_args[0][0]
            assert "chainctl" in call_args
            assert "--name=test-org support identity" in call_args

    def test_support_identity_not_found(self):
        """Test when no support identity exists for org."""
        with patch('forge_gauge.utils.chainctl_auth.subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                returncode=1,
                stdout="",
                stderr="No folder found",
            )

            result = get_support_identity_id("unknown-org")

            assert result is None

    def test_chainctl_not_available(self):
        """Test handling when chainctl is not installed."""
        with patch('forge_gauge.utils.chainctl_auth.subprocess.run') as mock_run:
            mock_run.side_effect = FileNotFoundError()

            result = get_support_identity_id("test-org")

            assert result is None


class TestLoginAsSupport:
    """Tests for login_as_support() function."""

    def test_login_success(self):
        """Test successful login as support identity."""
        with patch('forge_gauge.utils.chainctl_auth.subprocess.run') as mock_run:
            mock_run.side_effect = [
                # get_support_identity_id call
                Mock(returncode=0, stdout=f"{CHAINGUARD_SUPPORT_UIDP}/abc123\n", stderr=""),
                # login call
                Mock(returncode=0, stdout="Successfully logged in", stderr=""),
            ]

            result = login_as_support("test-org")

            assert result is True
            assert mock_run.call_count == 2

    def test_login_no_support_identity(self):
        """Test login fails when no support identity exists."""
        with patch('forge_gauge.utils.chainctl_auth.subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                returncode=1,
                stdout="",
                stderr="No folder found",
            )

            result = login_as_support("unknown-org")

            assert result is False

    def test_login_auth_fails(self):
        """Test handling when login command fails."""
        with patch('forge_gauge.utils.chainctl_auth.subprocess.run') as mock_run:
            mock_run.side_effect = [
                # get_support_identity_id call succeeds
                Mock(returncode=0, stdout=f"{CHAINGUARD_SUPPORT_UIDP}/abc123\n", stderr=""),
                # login call fails
                Mock(returncode=1, stdout="", stderr="Authentication failed"),
            ]

            result = login_as_support("test-org")

            assert result is False


class TestRestoreNormalIdentity:
    """Tests for restore_normal_identity() function."""

    def test_restore_success(self):
        """Test successful identity restoration."""
        with patch('forge_gauge.utils.chainctl_auth.subprocess.run') as mock_run:
            mock_run.side_effect = [
                # logout call
                Mock(returncode=0, stdout="Logged out", stderr=""),
                # login call
                Mock(returncode=0, stdout="Successfully logged in", stderr=""),
            ]

            result = restore_normal_identity()

            assert result is True
            assert mock_run.call_count == 2

    def test_restore_login_fails(self):
        """Test handling when re-login fails."""
        with patch('forge_gauge.utils.chainctl_auth.subprocess.run') as mock_run:
            mock_run.side_effect = [
                # logout call succeeds
                Mock(returncode=0, stdout="Logged out", stderr=""),
                # login call fails
                Mock(returncode=1, stdout="", stderr="Login failed"),
            ]

            result = restore_normal_identity()

            assert result is False


class TestOrganizationImageLoader:
    """Tests for OrganizationImageLoader class."""

    def test_init_creates_cache_dir(self, tmp_path):
        """Test that initialization creates cache directory."""
        cache_dir = tmp_path / "test_cache"
        loader = OrganizationImageLoader(
            organization="test-org",
            cache_dir=cache_dir,
        )

        assert cache_dir.exists()
        assert loader.organization == "test-org"
        assert loader.cache_dir == cache_dir

    def test_chainctl_not_available(self, tmp_path):
        """Test error when chainctl is not installed."""
        with patch("shutil.which", return_value=None):
            loader = OrganizationImageLoader(
                organization="test-org",
                cache_dir=tmp_path,
            )

            with pytest.raises(RuntimeError, match="chainctl not found"):
                loader._list_entitled_images()

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_list_entitled_images_success(self, mock_run, mock_which, tmp_path):
        """Test successful listing of entitled images."""
        mock_which.return_value = "/usr/bin/chainctl"

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "items": [
                    {"name": "nginx"},
                    {"name": "python"},
                    {"name": "postgres"},
                ]
            }),
        )

        loader = OrganizationImageLoader(
            organization="test-org",
            cache_dir=tmp_path,
        )

        images = loader._list_entitled_images()

        assert images == ["nginx", "postgres", "python"]  # Sorted
        mock_run.assert_called_once()
        assert "chainctl" in mock_run.call_args[0][0]
        assert "--parent" in mock_run.call_args[0][0]
        assert "test-org" in mock_run.call_args[0][0]

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_list_entitled_images_cached(self, mock_run, mock_which, tmp_path):
        """Test that cached results are used when fresh."""
        mock_which.return_value = "/usr/bin/chainctl"

        # Create a fresh cache file
        import time
        cache_file = tmp_path / "org_catalog_test-org.json"
        cache_data = {
            "timestamp": time.time(),
            "images": ["cached-image-1", "cached-image-2"],
        }
        with open(cache_file, "w") as f:
            json.dump(cache_data, f)

        loader = OrganizationImageLoader(
            organization="test-org",
            cache_dir=tmp_path,
        )

        images = loader._list_entitled_images()

        assert images == ["cached-image-1", "cached-image-2"]
        mock_run.assert_not_called()  # Should use cache

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_list_entitled_images_expired_cache(self, mock_run, mock_which, tmp_path):
        """Test that expired cache is refreshed."""
        mock_which.return_value = "/usr/bin/chainctl"

        # Create an expired cache file
        cache_file = tmp_path / "org_catalog_test-org.json"
        cache_data = {
            "timestamp": 0,  # Very old timestamp
            "images": ["old-image"],
        }
        with open(cache_file, "w") as f:
            json.dump(cache_data, f)

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "items": [{"name": "new-image"}]
            }),
        )

        loader = OrganizationImageLoader(
            organization="test-org",
            cache_dir=tmp_path,
        )

        images = loader._list_entitled_images()

        assert images == ["new-image"]
        mock_run.assert_called_once()  # Should fetch fresh

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_chainctl_failure(self, mock_run, mock_which, tmp_path):
        """Test error handling when chainctl fails."""
        mock_which.return_value = "/usr/bin/chainctl"
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr="error: authentication required",
        )

        loader = OrganizationImageLoader(
            organization="test-org",
            cache_dir=tmp_path,
        )

        with pytest.raises(RuntimeError, match="chainctl failed"):
            loader._list_entitled_images()

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_chainctl_no_folder_found_error(self, mock_run, mock_which, tmp_path):
        """Test helpful error message when user doesn't have access to organization."""
        mock_which.return_value = "/usr/bin/chainctl"
        # Simulate the actual error output from chainctl
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr='Opening browser to https://issuer.enforce.dev/oauth?...\n{"message":"No folder found for \\"cbp.gov\\"","code":4}',
        )

        loader = OrganizationImageLoader(
            organization="cbp.gov",
            cache_dir=tmp_path,
        )

        with pytest.raises(RuntimeError) as exc_info:
            loader._list_entitled_images()

        error_msg = str(exc_info.value)
        assert "don't have access to organization" in error_msg
        assert "cbp.gov" in error_msg
        assert "chainctl auth login --identity=" in error_msg
        assert "chainguard-support" in error_msg
        assert "support identity" in error_msg
        assert "organization owner" in error_msg.lower()

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_chainctl_code_4_error(self, mock_run, mock_which, tmp_path):
        """Test helpful error message when chainctl returns code 4 error."""
        mock_which.return_value = "/usr/bin/chainctl"
        # Alternative format that just has the code
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr='{"message":"some error","code":4}',
        )

        loader = OrganizationImageLoader(
            organization="test-org",
            cache_dir=tmp_path,
        )

        with pytest.raises(RuntimeError) as exc_info:
            loader._list_entitled_images()

        error_msg = str(exc_info.value)
        assert "don't have access" in error_msg
        assert "chainctl auth login --identity=" in error_msg
        assert "chainguard-support" in error_msg

    def test_get_alternative_image_with_aliases(self, tmp_path):
        """Test getting alternative image from metadata with aliases."""
        loader = OrganizationImageLoader(
            organization="test-org",
            cache_dir=tmp_path,
        )

        mock_client = MagicMock()
        mock_client.get_image_metadata.return_value = {
            "name": "nginx",
            "aliases": ["nginx:alpine", "nginx:latest"],
            "tier": "APPLICATION",
        }
        loader._github_client = mock_client

        alternative = loader._get_alternative_image("nginx")

        assert alternative == "nginx:alpine"
        mock_client.get_image_metadata.assert_called_once_with("nginx")

    def test_get_alternative_image_no_aliases(self, tmp_path):
        """Test getting alternative image when no aliases exist."""
        loader = OrganizationImageLoader(
            organization="test-org",
            cache_dir=tmp_path,
        )

        mock_client = MagicMock()
        mock_client.get_image_metadata.return_value = {
            "name": "custom-image",
            "aliases": [],
            "tier": "APPLICATION",
        }
        loader._github_client = mock_client

        alternative = loader._get_alternative_image("custom-image")

        # Empty string indicates metadata exists but no aliases
        assert alternative == ""

    def test_get_alternative_image_no_metadata(self, tmp_path):
        """Test getting alternative image when metadata not found."""
        loader = OrganizationImageLoader(
            organization="test-org",
            cache_dir=tmp_path,
        )

        mock_client = MagicMock()
        mock_client.get_image_metadata.return_value = None
        loader._github_client = mock_client

        alternative = loader._get_alternative_image("unknown-image")

        assert alternative is None

    def test_get_alternative_image_metadata_error(self, tmp_path):
        """Test getting alternative image when metadata fetch fails."""
        loader = OrganizationImageLoader(
            organization="test-org",
            cache_dir=tmp_path,
        )

        mock_client = MagicMock()
        mock_client.get_image_metadata.side_effect = Exception("API error")
        loader._github_client = mock_client

        alternative = loader._get_alternative_image("failing-image")

        assert alternative is None

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_load_image_pairs_success(self, mock_run, mock_which, tmp_path):
        """Test successful loading of image pairs."""
        mock_which.return_value = "/usr/bin/chainctl"
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "items": [
                    {"name": "nginx"},
                    {"name": "python"},
                ]
            }),
        )

        loader = OrganizationImageLoader(
            organization="test-org",
            cache_dir=tmp_path,
        )

        mock_client = MagicMock()
        mock_client.get_image_metadata.side_effect = [
            {"name": "nginx", "aliases": ["nginx:alpine"]},
            {"name": "python", "aliases": ["python:3.12"]},
        ]
        loader._github_client = mock_client

        pairs = loader.load_image_pairs()

        assert len(pairs) == 2
        assert all(isinstance(p, ImagePair) for p in pairs)

        # Check first pair
        assert pairs[0].alternative_image == "nginx:alpine"
        assert pairs[0].chainguard_image == "cgr.dev/test-org/nginx:latest"

        # Check second pair
        assert pairs[1].alternative_image == "python:3.12"
        assert pairs[1].chainguard_image == "cgr.dev/test-org/python:latest"

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_load_image_pairs_skips_missing_metadata(self, mock_run, mock_which, tmp_path):
        """Test that images without metadata are skipped."""
        mock_which.return_value = "/usr/bin/chainctl"
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "items": [
                    {"name": "nginx"},
                    {"name": "unknown-image"},
                ]
            }),
        )

        loader = OrganizationImageLoader(
            organization="test-org",
            cache_dir=tmp_path,
        )

        mock_client = MagicMock()
        mock_client.get_image_metadata.side_effect = [
            {"name": "nginx", "aliases": ["nginx:alpine"]},
            None,  # No metadata for unknown-image
        ]
        loader._github_client = mock_client

        pairs = loader.load_image_pairs()

        assert len(pairs) == 1
        assert pairs[0].chainguard_image == "cgr.dev/test-org/nginx:latest"

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_load_image_pairs_skips_empty_aliases(self, mock_run, mock_which, tmp_path):
        """Test that images with empty aliases are skipped."""
        mock_which.return_value = "/usr/bin/chainctl"
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "items": [
                    {"name": "nginx"},
                    {"name": "no-alias-image"},
                ]
            }),
        )

        loader = OrganizationImageLoader(
            organization="test-org",
            cache_dir=tmp_path,
        )

        mock_client = MagicMock()
        mock_client.get_image_metadata.side_effect = [
            {"name": "nginx", "aliases": ["nginx:alpine"]},
            {"name": "no-alias-image", "aliases": []},  # Empty aliases
        ]
        loader._github_client = mock_client

        pairs = loader.load_image_pairs()

        assert len(pairs) == 1
        assert pairs[0].chainguard_image == "cgr.dev/test-org/nginx:latest"


class TestGitHubMetadataClientGetImageMetadata:
    """Tests for GitHubMetadataClient.get_image_metadata method."""

    def test_get_image_metadata_success(self, tmp_path):
        """Test successful metadata fetch."""
        from forge_gauge.integrations.github_metadata import GitHubMetadataClient

        client = GitHubMetadataClient(
            github_token="test-token",
            cache_dir=tmp_path,
        )

        with patch("requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.text = """
name: nginx
image: cgr.dev/chainguard/nginx
aliases:
  - nginx:alpine
  - nginx:latest
tier: APPLICATION
"""
            mock_get.return_value = mock_response

            metadata = client.get_image_metadata("nginx")

            assert metadata is not None
            assert metadata["name"] == "nginx"
            assert "nginx:alpine" in metadata["aliases"]
            assert metadata["tier"] == "APPLICATION"

    def test_get_image_metadata_not_found(self, tmp_path):
        """Test metadata fetch when image not found."""
        from forge_gauge.integrations.github_metadata import GitHubMetadataClient
        import requests

        client = GitHubMetadataClient(
            github_token="test-token",
            cache_dir=tmp_path,
        )

        with patch("requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_response.raise_for_status.side_effect = requests.HTTPError(
                response=mock_response
            )
            mock_get.return_value = mock_response

            metadata = client.get_image_metadata("nonexistent")

            assert metadata is None

    def test_get_image_metadata_strips_image_ref(self, tmp_path):
        """Test that full image refs are stripped to image name."""
        from forge_gauge.integrations.github_metadata import GitHubMetadataClient

        client = GitHubMetadataClient(
            github_token="test-token",
            cache_dir=tmp_path,
        )

        with patch("requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.text = "name: nginx\naliases: []\n"
            mock_get.return_value = mock_response

            # Full image reference should be stripped
            client.get_image_metadata("cgr.dev/chainguard-private/nginx:latest")

            # Verify the URL was called with just "nginx"
            call_url = mock_get.call_args[0][0]
            assert "images/nginx/metadata.yaml" in call_url
