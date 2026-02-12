"""
Tests for Docker utilities including fallback strategies.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
import subprocess
import re

from forge_gauge.utils.docker_utils import DockerClient


class TestDockerClientFallback:
    """Test fallback scenarios for Docker image pulling."""

    @pytest.fixture
    def docker_client(self):
        """Create a DockerClient instance for testing."""
        with patch.object(DockerClient, '_detect_runtime', return_value='docker'):
            return DockerClient()

    def test_pull_image_with_fallback_success_on_first_try(self, docker_client):
        """Test successful pull on first attempt without fallback."""
        with patch('subprocess.run') as mock_run:
            # Simulate successful pull
            mock_run.return_value = Mock(returncode=0, stderr="", stdout="")

            image, used_fallback, pull_successful, error_type = docker_client.pull_image_with_fallback(
                "python:3.12", "linux/amd64"
            )

            assert image == "python:3.12"
            assert used_fallback is False
            assert pull_successful is True
            assert error_type == "none"
            assert mock_run.call_count == 1

    def test_pull_image_with_fallback_mirror_gcr_for_dockerhub(self, docker_client):
        """Test fallback to mirror.gcr.io for Docker Hub images."""
        with patch('subprocess.run') as mock_run:
            # First call (original) fails with not found
            # Second call (mirror.gcr.io) succeeds
            mock_run.side_effect = [
                Mock(returncode=1, stderr="manifest unknown: not found", stdout=""),
                Mock(returncode=0, stderr="", stdout=""),  # mirror.gcr.io success
            ]

            image, used_fallback, pull_successful, error_type = docker_client.pull_image_with_fallback(
                "python:3.12", "linux/amd64"
            )

            assert image == "mirror.gcr.io/library/python:3.12"
            assert used_fallback is True
            assert pull_successful is True
            assert error_type == "none"
            assert mock_run.call_count == 2

    def test_pull_image_with_fallback_latest_tag(self, docker_client):
        """Test fallback to :latest tag when image not found."""
        with patch('subprocess.run') as mock_run:
            # First call (original) fails with not found
            # Second call (mirror.gcr.io) - skipped for non-dockerhub
            # Third call (:latest) succeeds
            mock_run.side_effect = [
                Mock(returncode=1, stderr="not found", stdout=""),
                Mock(returncode=0, stderr="", stdout=""),  # :latest success
            ]

            image, used_fallback, pull_successful, error_type = docker_client.pull_image_with_fallback(
                "cgr.dev/chainguard/python:3.12", "linux/amd64"
            )

            assert image == "cgr.dev/chainguard/python:latest"
            assert used_fallback is True
            assert pull_successful is True
            assert error_type == "none"

    def test_pull_image_with_fallback_all_fail(self, docker_client):
        """Test when all fallback strategies fail."""
        with patch('subprocess.run') as mock_run:
            # All attempts fail
            mock_run.return_value = Mock(returncode=1, stderr="not found", stdout="")

            image, used_fallback, pull_successful, error_type = docker_client.pull_image_with_fallback(
                "python:3.12", "linux/amd64"
            )

            assert image == "python:3.12"  # Returns original image
            assert used_fallback is False
            assert pull_successful is False
            assert error_type == "not_found"

    def test_pull_image_with_fallback_rate_limit(self, docker_client):
        """Test fallback triggers on rate limit error."""
        with patch('subprocess.run') as mock_run:
            # First call fails with rate limit
            # Second call (mirror.gcr.io) succeeds
            mock_run.side_effect = [
                Mock(returncode=1, stderr="toomanyrequests: rate limit exceeded", stdout=""),
                Mock(returncode=0, stderr="", stdout=""),  # mirror.gcr.io success
            ]

            image, used_fallback, pull_successful, error_type = docker_client.pull_image_with_fallback(
                "ubuntu:20.04", "linux/amd64"
            )

            assert image == "mirror.gcr.io/library/ubuntu:20.04"
            assert used_fallback is True
            assert pull_successful is True
            assert error_type == "none"

    def test_pull_image_with_fallback_timeout(self, docker_client):
        """Test timeout handling in pull_image_with_fallback."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("docker", 300)

            image, used_fallback, pull_successful, error_type = docker_client.pull_image_with_fallback(
                "python:3.12", "linux/amd64"
            )

            assert image == "python:3.12"
            assert used_fallback is False
            assert pull_successful is False
            assert error_type == "timeout"

    def test_has_registry_prefix(self, docker_client):
        """Test registry prefix detection."""
        assert docker_client._has_registry_prefix("gcr.io/my/image:tag") is True
        assert docker_client._has_registry_prefix("registry.example.com:5000/image") is True
        assert docker_client._has_registry_prefix("cgr.dev/chainguard/python") is True
        assert docker_client._has_registry_prefix("python:3.12") is False
        assert docker_client._has_registry_prefix("ubuntu") is False
        assert docker_client._has_registry_prefix("myuser/myimage") is False

    def test_try_mirror_gcr_fallback_official_image(self, docker_client):
        """Test mirror.gcr.io construction for official images."""
        mirror = docker_client._try_mirror_gcr_fallback("python:3.12")
        assert mirror == "mirror.gcr.io/library/python:3.12"

        mirror = docker_client._try_mirror_gcr_fallback("ubuntu")
        assert mirror == "mirror.gcr.io/library/ubuntu"

    def test_try_mirror_gcr_fallback_user_image(self, docker_client):
        """Test mirror.gcr.io construction for user/org images."""
        mirror = docker_client._try_mirror_gcr_fallback("myuser/myimage:v1")
        assert mirror == "mirror.gcr.io/myuser/myimage:v1"

    def test_try_mirror_gcr_fallback_skip_registry_images(self, docker_client):
        """Test mirror.gcr.io fallback skips images with registry prefix."""
        mirror = docker_client._try_mirror_gcr_fallback("gcr.io/my/image:tag")
        assert mirror is None

        mirror = docker_client._try_mirror_gcr_fallback("cgr.dev/chainguard/python")
        assert mirror is None

    def test_try_mirror_gcr_fallback_skip_digest(self, docker_client):
        """Test mirror.gcr.io fallback skips digest-based images."""
        mirror = docker_client._try_mirror_gcr_fallback("python@sha256:abc123")
        assert mirror is None

    def test_pull_image_with_fallback_dns_error_with_upstream(self, docker_client):
        """Test upstream fallback when private registry has DNS lookup failure."""
        with patch('subprocess.run') as mock_run:
            # First call (private registry) fails with DNS error
            # Second call (upstream) succeeds
            mock_run.side_effect = [
                Mock(returncode=1, stderr="dial tcp: lookup docker.artifactory.mars.pcf-maximus.com on 192.168.5.3:53: no such host", stdout=""),
                Mock(returncode=0, stderr="", stdout=""),  # upstream success
            ]

            image, used_fallback, pull_successful, error_type = docker_client.pull_image_with_fallback(
                "docker.artifactory.mars.pcf-maximus.com/bitnami/mongodb:7.0.2-debian-11-r7",
                "linux/amd64",
                upstream_image="bitnami/mongodb:7.0.2-debian-11-r7"
            )

            assert image == "bitnami/mongodb:7.0.2-debian-11-r7"
            assert used_fallback is True
            assert pull_successful is True
            assert error_type == "none"
            assert mock_run.call_count == 2

    def test_pull_image_with_fallback_connection_refused_with_upstream(self, docker_client):
        """Test upstream fallback when private registry connection is refused."""
        with patch('subprocess.run') as mock_run:
            # First call (private registry) fails with connection refused
            # Second call (upstream) succeeds
            mock_run.side_effect = [
                Mock(returncode=1, stderr="Error: connection refused to private.registry.com", stdout=""),
                Mock(returncode=0, stderr="", stdout=""),  # upstream success
            ]

            image, used_fallback, pull_successful, error_type = docker_client.pull_image_with_fallback(
                "private.registry.com/nginx:latest",
                "linux/amd64",
                upstream_image="nginx:latest"
            )

            assert image == "nginx:latest"
            assert used_fallback is True
            assert pull_successful is True
            assert error_type == "none"
            assert mock_run.call_count == 2

    def test_pull_image_with_fallback_no_auth_with_upstream(self, docker_client):
        """Test upstream fallback when private registry requires authentication."""
        with patch('subprocess.run') as mock_run:
            # First call (private ECR) fails with no auth
            # Second call (upstream) succeeds
            mock_run.side_effect = [
                Mock(returncode=1, stderr="Error: no basic auth credentials", stdout=""),
                Mock(returncode=0, stderr="", stdout=""),  # upstream success
            ]

            image, used_fallback, pull_successful, error_type = docker_client.pull_image_with_fallback(
                "602401143452.dkr.ecr.us-west-2.amazonaws.com/eks/coredns:v1.8.7-eksbuild.1",
                "linux/amd64",
                upstream_image="eks/coredns:v1.8.7-eksbuild.1"
            )

            assert image == "eks/coredns:v1.8.7-eksbuild.1"
            assert used_fallback is True
            assert pull_successful is True
            assert error_type == "none"
            assert mock_run.call_count == 2


class TestImageSize:
    """Test image size detection."""

    @pytest.fixture
    def docker_client(self):
        """Create a DockerClient instance for testing."""
        with patch.object(DockerClient, '_detect_runtime', return_value='docker'):
            return DockerClient()

    def test_get_image_size_mb_gigabytes(self, docker_client):
        """Test parsing image size in gigabytes."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="1.25GB\n", stderr="")
            
            size = docker_client.get_image_size_mb("python:3.12")
            
            assert size == 1280  # 1.25 * 1024 = 1280 MB

    def test_get_image_size_mb_megabytes(self, docker_client):
        """Test parsing image size in megabytes."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="234MB\n", stderr="")
            
            size = docker_client.get_image_size_mb("alpine:latest")
            
            assert size == 234

    def test_get_image_size_mb_kilobytes(self, docker_client):
        """Test parsing image size in kilobytes."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="1536KB\n", stderr="")
            
            size = docker_client.get_image_size_mb("busybox:latest")
            
            assert size == 2  # 1536/1024 = 1.5, rounded to 2

    def test_get_image_size_mb_bytes(self, docker_client):
        """Test parsing image size in bytes."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="1048576B\n", stderr="")
            
            size = docker_client.get_image_size_mb("scratch:latest")
            
            assert size == 1  # 1048576 / (1024*1024) = 1 MB

    def test_get_image_size_mb_docker_io_library(self, docker_client):
        """Test image size with docker.io/library prefix tries short name."""
        with patch('subprocess.run') as mock_run:
            # First call with full name fails, second with short name succeeds
            mock_run.side_effect = [
                Mock(returncode=1, stdout="", stderr=""),
                Mock(returncode=0, stdout="234MB\n", stderr=""),
            ]
            
            size = docker_client.get_image_size_mb("docker.io/library/python:3.12")
            
            assert size == 234
            assert mock_run.call_count == 2

    def test_get_image_size_mb_docker_io_user(self, docker_client):
        """Test image size with docker.io user image tries short name."""
        with patch('subprocess.run') as mock_run:
            # First call with full name fails, second with short name succeeds
            mock_run.side_effect = [
                Mock(returncode=1, stdout="", stderr=""),
                Mock(returncode=0, stdout="156MB\n", stderr=""),
            ]
            
            size = docker_client.get_image_size_mb("docker.io/myuser/myimage:v1")
            
            assert size == 156
            assert mock_run.call_count == 2

    def test_get_image_size_mb_chainguard_image(self, docker_client):
        """Test image size for Chainguard images (cgr.dev)."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="15MB\n", stderr="")
            
            size = docker_client.get_image_size_mb("cgr.dev/chainguard/python:latest")
            
            assert size == 15

    def test_get_image_size_mb_not_found(self, docker_client):
        """Test image size when image is not found."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=1, stdout="", stderr="")
            
            size = docker_client.get_image_size_mb("nonexistent:image")
            
            assert size == 0.0

    def test_get_image_size_mb_timeout(self, docker_client):
        """Test image size with timeout."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("docker", 30)
            
            size = docker_client.get_image_size_mb("python:3.12")
            
            assert size == 0.0


class TestEnsureFreshImage:
    """Test ensure_fresh_image with fallback integration."""

    @pytest.fixture
    def docker_client(self):
        """Create a DockerClient instance for testing."""
        with patch.object(DockerClient, '_detect_runtime', return_value='docker'):
            return DockerClient()

    def test_ensure_fresh_image_up_to_date(self, docker_client):
        """Test when local image is already up-to-date."""
        with patch.object(docker_client, 'get_remote_digest', return_value="sha256:abc123"), \
             patch.object(docker_client, 'get_image_digest', return_value="sha256:abc123"):

            image, used_fallback, pull_successful, error_type = docker_client.ensure_fresh_image(
                "python:3.12", "linux/amd64"
            )

            assert image == "python:3.12"
            assert used_fallback is False
            assert pull_successful is True
            assert error_type == "none"

    def test_ensure_fresh_image_needs_update(self, docker_client):
        """Test when local image needs updating."""
        with patch.object(docker_client, 'get_remote_digest', return_value="sha256:new123"), \
             patch.object(docker_client, 'get_image_digest', return_value="sha256:old123"), \
             patch.object(docker_client, 'pull_image_with_fallback', return_value=("python:3.12", False, True, "none")):

            image, used_fallback, pull_successful, error_type = docker_client.ensure_fresh_image(
                "python:3.12", "linux/amd64"
            )

            assert image == "python:3.12"
            assert pull_successful is True
            assert error_type == "none"

    def test_ensure_fresh_image_with_fallback(self, docker_client):
        """Test ensure_fresh_image when fallback is used."""
        with patch.object(docker_client, 'get_remote_digest', return_value=None), \
             patch.object(docker_client, 'pull_image_with_fallback',
                         return_value=("mirror.gcr.io/library/python:3.12", True, True, "none")):

            image, used_fallback, pull_successful, error_type = docker_client.ensure_fresh_image(
                "python:3.12", "linux/amd64"
            )

            assert image == "mirror.gcr.io/library/python:3.12"
            assert used_fallback is True
            assert pull_successful is True
            assert error_type == "none"


class TestSkopeoFallback:
    """Test skopeo fallback scenarios."""

    @pytest.fixture
    def docker_client_with_skopeo(self):
        """Create a DockerClient instance with skopeo available."""
        with patch.object(DockerClient, '_detect_runtime', return_value='docker'), \
             patch.object(DockerClient, '_check_skopeo_available', return_value=True):
            return DockerClient()

    @pytest.fixture
    def docker_client_without_skopeo(self):
        """Create a DockerClient instance without skopeo available."""
        with patch.object(DockerClient, '_detect_runtime', return_value='docker'), \
             patch.object(DockerClient, '_check_skopeo_available', return_value=False):
            return DockerClient()

    def test_skopeo_not_available(self, docker_client_without_skopeo):
        """Test that skopeo fallback is skipped if skopeo is not available."""
        tag = docker_client_without_skopeo._get_most_recent_tag_with_skopeo("python:3.12")
        assert tag is None

    def test_get_latest_tag(self, docker_client_with_skopeo):
        """Test that 'latest' tag is preferred."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                returncode=0,
                stdout='{"Tags": ["1.0", "1.10", "1.2", "latest"]}'
            )
            tag = docker_client_with_skopeo._get_most_recent_tag_with_skopeo("python")
            assert tag == "latest"
    
    def test_get_main_tag(self, docker_client_with_skopeo):
        """Test that 'main' tag is preferred when 'latest' is not present."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                returncode=0,
                stdout='{"Tags": ["1.0", "1.10", "1.2", "main"]}'
            )
            tag = docker_client_with_skopeo._get_most_recent_tag_with_skopeo("python")
            assert tag == "main"

    def test_get_master_tag(self, docker_client_with_skopeo):
        """Test that 'master' tag is preferred when 'latest' and 'main' are not present."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                returncode=0,
                stdout='{"Tags": ["1.0", "1.10", "1.2", "master"]}'
            )
            tag = docker_client_with_skopeo._get_most_recent_tag_with_skopeo("python")
            assert tag == "master"

    def test_semver_fallback(self, docker_client_with_skopeo):
        """Test that semver sorting is used as a fallback."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                returncode=0,
                stdout='{"Tags": ["1.0", "1.10", "1.2"]}'
            )
            tag = docker_client_with_skopeo._get_most_recent_tag_with_skopeo("python")
            assert tag == "1.10"

    def test_semver_with_v_prefix(self, docker_client_with_skopeo):
        """Test that semver sorting handles 'v' prefix."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                returncode=0,
                stdout='{"Tags": ["v1.0", "v1.10", "v1.2"]}'
            )
            tag = docker_client_with_skopeo._get_most_recent_tag_with_skopeo("python")
            assert tag == "v1.10"

    def test_skopeo_returns_error(self, docker_client_with_skopeo):
        """Test that skopeo errors are handled gracefully."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=1, stderr="some error")
            tag = docker_client_with_skopeo._get_most_recent_tag_with_skopeo("python")
            assert tag is None

    def test_no_version_tags(self, docker_client_with_skopeo):
        """Test that non-version tags are ignored."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                returncode=0,
                stdout='{"Tags": ["edge"]}'
            )
            tag = docker_client_with_skopeo._get_most_recent_tag_with_skopeo("python")
            assert tag is None

    def test_pull_with_skopeo_fallback(self, docker_client_with_skopeo):
        """Test that pull_image_with_fallback uses skopeo."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                # pull original fails
                Mock(returncode=1, stderr="not found", stdout=""),
                # mirror fallback fails
                Mock(returncode=1, stderr="not found", stdout=""),
                # pull with :latest fails
                Mock(returncode=1, stderr="not found", stdout=""),
                # skopeo list-tags succeeds
                Mock(returncode=0, stdout='{"Tags": ["1.0", "1.10", "1.2", "master"]}', stderr=""),
                # pull with most recent tag succeeds
                Mock(returncode=0, stderr="", stdout=""),
            ]
            image, used_fallback, pull_successful, error_type = docker_client_with_skopeo.pull_image_with_fallback(
                "python:3.12-slim"
            )
            assert image == "python:master"
            assert used_fallback is True
            assert pull_successful is True
            assert error_type == "none"


class TestEnsureChainguardAuth:
    """Test Chainguard authentication checking."""

    @pytest.fixture
    def docker_client(self):
        """Create a DockerClient instance for testing."""
        with patch.object(DockerClient, '_detect_runtime', return_value='docker'):
            return DockerClient()

    def test_auth_already_configured(self, docker_client):
        """Test when chainctl is installed and auth token is valid."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                Mock(returncode=0, stdout="chainctl version 1.0.0", stderr=""),  # chainctl version
                Mock(returncode=0, stdout="eyJhbGc...", stderr=""),  # chainctl auth token
            ]

            result = docker_client.ensure_chainguard_auth()

            assert result is True
            assert mock_run.call_count == 2

    def test_chainctl_version_fails(self, docker_client):
        """Test when chainctl is not installed or not working."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=1, stdout="", stderr="command not found")

            result = docker_client.ensure_chainguard_auth()

            assert result is False
            assert mock_run.call_count == 1

    def test_auth_token_fails_login_succeeds(self, docker_client):
        """Test when auth token fails but login succeeds."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                Mock(returncode=0, stdout="chainctl version 1.0.0", stderr=""),  # chainctl version
                Mock(returncode=1, stdout="", stderr="not authenticated"),  # chainctl auth token fails
                Mock(returncode=0, stdout="", stderr=""),  # chainctl auth login succeeds
            ]

            result = docker_client.ensure_chainguard_auth()

            assert result is True
            assert mock_run.call_count == 3

    def test_auth_token_fails_login_fails(self, docker_client):
        """Test when both auth token and login fail."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                Mock(returncode=0, stdout="chainctl version 1.0.0", stderr=""),  # chainctl version
                Mock(returncode=1, stdout="", stderr="not authenticated"),  # chainctl auth token fails
                Mock(returncode=1, stdout="", stderr="login failed"),  # chainctl auth login fails
            ]

            result = docker_client.ensure_chainguard_auth()

            assert result is False
            assert mock_run.call_count == 3

    def test_chainctl_not_found_file_not_found_error(self, docker_client):
        """Test when chainctl binary is not found (FileNotFoundError)."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = FileNotFoundError("chainctl not found")

            result = docker_client.ensure_chainguard_auth()

            assert result is False

    def test_timeout_during_auth_check(self, docker_client):
        """Test when chainctl commands timeout."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="chainctl", timeout=10)

            result = docker_client.ensure_chainguard_auth()

            assert result is False

    def test_generic_exception_handled(self, docker_client):
        """Test that generic exceptions are caught and return False.

        This test ensures that unexpected errors (like NameError from
        undefined constants) are properly caught rather than crashing.
        """
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                Mock(returncode=0, stdout="chainctl version 1.0.0", stderr=""),  # chainctl version
                RuntimeError("Unexpected error"),  # Simulate unexpected error
            ]

            result = docker_client.ensure_chainguard_auth()

            assert result is False

    def test_constants_are_defined(self):
        """Test that all timeout constants used by ensure_chainguard_auth are defined.

        This test catches the bug where GITHUB_CLI_TIMEOUT was used but not imported.
        """
        from forge_gauge.constants import (
            VERSION_CHECK_TIMEOUT,
            GITHUB_CLI_TIMEOUT,
            CLI_SUBPROCESS_TIMEOUT,
        )

        # Verify they are positive numbers
        assert VERSION_CHECK_TIMEOUT > 0
        assert GITHUB_CLI_TIMEOUT > 0
        assert CLI_SUBPROCESS_TIMEOUT > 0

    def test_constants_imported_in_docker_utils(self):
        """Test that docker_utils.py has all required constants imported.

        This directly tests that the imports are correct by checking the module.
        """
        from forge_gauge import utils; import forge_gauge.utils.docker_utils as du

        # These should be accessible from the module's imported constants
        # If they're not imported, this would raise NameError when the function runs
        assert hasattr(du, 'VERSION_CHECK_TIMEOUT') or 'VERSION_CHECK_TIMEOUT' in dir(du)

        # Verify the function can be called without NameError by mocking subprocess
        with patch.object(DockerClient, '_detect_runtime', return_value='docker'):
            client = DockerClient()

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=1, stdout="", stderr="")
            # This should not raise NameError
            try:
                client.ensure_chainguard_auth()
            except NameError as e:
                pytest.fail(f"NameError indicates missing import: {e}")


class TestChainguardPrivateFallback:
    """Test chainguard-private fallback for org-specific registries."""

    @pytest.fixture
    def docker_client(self):
        """Create a DockerClient instance for testing."""
        with patch.object(DockerClient, '_detect_runtime', return_value='docker'):
            return DockerClient()

    def test_get_chainguard_private_fallback_org_image(self, docker_client):
        """Test fallback conversion for org-specific images."""
        result = docker_client._get_chainguard_private_fallback(
            "cgr.dev/cbp.gov/node:latest"
        )
        assert result == "cgr.dev/chainguard-private/node:latest"

    def test_get_chainguard_private_fallback_with_digest(self, docker_client):
        """Test fallback preserves digest references."""
        result = docker_client._get_chainguard_private_fallback(
            "cgr.dev/acme-corp/python@sha256:abc123"
        )
        assert result == "cgr.dev/chainguard-private/python@sha256:abc123"

    def test_get_chainguard_private_fallback_skips_chainguard_private(self, docker_client):
        """Test fallback returns None for already chainguard-private images."""
        result = docker_client._get_chainguard_private_fallback(
            "cgr.dev/chainguard-private/node:latest"
        )
        assert result is None

    def test_get_chainguard_private_fallback_skips_public_chainguard(self, docker_client):
        """Test fallback returns None for public chainguard images."""
        result = docker_client._get_chainguard_private_fallback(
            "cgr.dev/chainguard/node:latest"
        )
        assert result is None

    def test_get_chainguard_private_fallback_non_cgr(self, docker_client):
        """Test fallback returns None for non-cgr.dev images."""
        result = docker_client._get_chainguard_private_fallback(
            "docker.io/library/python:3.12"
        )
        assert result is None

    def test_get_chainguard_private_fallback_gcr(self, docker_client):
        """Test fallback returns None for GCR images."""
        result = docker_client._get_chainguard_private_fallback(
            "gcr.io/my-project/my-image:latest"
        )
        assert result is None

    def test_pull_with_chainguard_private_fallback_success(self, docker_client):
        """Test that auth failure on org registry falls back to chainguard-private when enabled."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                # First pull fails with auth error
                Mock(returncode=1, stderr="unauthorized: authentication required", stdout=""),
                # Second pull (chainguard-private) succeeds
                Mock(returncode=0, stderr="", stdout=""),
            ]

            image, used_fallback, pull_successful, error_type = docker_client.pull_image_with_fallback(
                "cgr.dev/cbp.gov/node:latest", "linux/amd64",
                allow_chainguard_private_fallback=True,  # Must be explicitly enabled
            )

            assert image == "cgr.dev/chainguard-private/node:latest"
            assert used_fallback is True
            assert pull_successful is True
            assert error_type == "none"
            assert mock_run.call_count == 2

    def test_pull_with_chainguard_private_fallback_also_fails(self, docker_client):
        """Test behavior when both org and chainguard-private fail."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                # First pull fails with auth error
                Mock(returncode=1, stderr="unauthorized: authentication required", stdout=""),
                # Second pull (chainguard-private) also fails
                Mock(returncode=1, stderr="unauthorized: authentication required", stdout=""),
            ]

            image, used_fallback, pull_successful, error_type = docker_client.pull_image_with_fallback(
                "cgr.dev/cbp.gov/node:latest", "linux/amd64",
                allow_chainguard_private_fallback=True,  # Must be explicitly enabled
            )

            # Should fail since both attempts failed
            assert pull_successful is False
            assert error_type == "auth"

    def test_pull_chainguard_private_no_fallback_needed(self, docker_client):
        """Test that chainguard-private images don't try fallback to themselves."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                # First pull fails with auth error
                Mock(returncode=1, stderr="unauthorized: authentication required", stdout=""),
            ]

            image, used_fallback, pull_successful, error_type = docker_client.pull_image_with_fallback(
                "cgr.dev/chainguard-private/node:latest", "linux/amd64",
                allow_chainguard_private_fallback=True,  # Even when enabled, skip if already private
            )

            # Should fail - no fallback attempted since already chainguard-private
            assert pull_successful is False
            assert used_fallback is False
            assert mock_run.call_count == 1

    def test_pull_chainguard_private_fallback_disabled_by_default(self, docker_client):
        """Test that chainguard-private fallback is NOT attempted when not enabled."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                # First pull fails with auth error
                Mock(returncode=1, stderr="unauthorized: authentication required", stdout=""),
            ]

            image, used_fallback, pull_successful, error_type = docker_client.pull_image_with_fallback(
                "cgr.dev/cbp.gov/node:latest", "linux/amd64",
                # allow_chainguard_private_fallback defaults to False
            )

            # Should fail without trying chainguard-private fallback
            assert pull_successful is False
            assert error_type == "auth"
            assert mock_run.call_count == 1  # Only one attempt, no fallback

    def test_support_mode_detection_on_fallback_success(self, docker_client):
        """Test that support mode is detected after first successful chainguard-private fallback."""
        assert docker_client._support_mode_detected is False
        assert docker_client._support_mode_org is None

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                # First pull (org registry) fails with auth error
                Mock(returncode=1, stderr="unauthorized: authentication required", stdout=""),
                # Second pull (chainguard-private) succeeds
                Mock(returncode=0, stderr="", stdout=""),
            ]

            image, used_fallback, pull_successful, error_type = docker_client.pull_image_with_fallback(
                "cgr.dev/cbp.gov/node:latest", "linux/amd64",
                allow_chainguard_private_fallback=True,
            )

            assert pull_successful is True
            assert docker_client._support_mode_detected is True
            assert docker_client._support_mode_org == "cbp.gov"

    def test_support_mode_skips_org_registry_on_subsequent_pulls(self, docker_client):
        """Test that support mode causes direct chainguard-private pulls for same org."""
        # Manually enable support mode
        docker_client._support_mode_detected = True
        docker_client._support_mode_org = "cbp.gov"

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                # Only one pull needed - directly to chainguard-private
                Mock(returncode=0, stderr="", stdout=""),
            ]

            image, used_fallback, pull_successful, error_type = docker_client.pull_image_with_fallback(
                "cgr.dev/cbp.gov/python:latest", "linux/amd64",
                allow_chainguard_private_fallback=True,
            )

            assert image == "cgr.dev/chainguard-private/python:latest"
            assert used_fallback is True
            assert pull_successful is True
            # Should only be one call since we skipped org registry
            assert mock_run.call_count == 1

    def test_support_mode_only_applies_to_same_org(self, docker_client):
        """Test that support mode for one org doesn't affect other orgs."""
        # Enable support mode for cbp.gov
        docker_client._support_mode_detected = True
        docker_client._support_mode_org = "cbp.gov"

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                # First attempt on different org should try org registry
                Mock(returncode=0, stderr="", stdout=""),
            ]

            image, used_fallback, pull_successful, error_type = docker_client.pull_image_with_fallback(
                "cgr.dev/other-org/node:latest", "linux/amd64",
                allow_chainguard_private_fallback=True,
            )

            # Should use original image since different org
            assert image == "cgr.dev/other-org/node:latest"
            assert used_fallback is False

    def test_support_mode_fallback_when_chainguard_private_also_fails(self, docker_client):
        """Test behavior when support mode is active but chainguard-private fails."""
        docker_client._support_mode_detected = True
        docker_client._support_mode_org = "cbp.gov"
        docker_client.skopeo_available = False  # Disable skopeo to simplify test

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                # Chainguard-private fails (maybe image doesn't exist there)
                Mock(returncode=1, stderr="manifest unknown", stdout=""),
                # Falls back to trying original org registry
                Mock(returncode=1, stderr="manifest unknown", stdout=""),
                # :latest fallback also fails
                Mock(returncode=1, stderr="manifest unknown", stdout=""),
            ]

            image, used_fallback, pull_successful, error_type = docker_client.pull_image_with_fallback(
                "cgr.dev/cbp.gov/custom-image:v1.0", "linux/amd64",
                allow_chainguard_private_fallback=True,
            )

            # Should fail since all attempts failed
            assert pull_successful is False

    def test_extract_org_from_cgr_image(self, docker_client):
        """Test organization extraction from cgr.dev image references."""
        assert docker_client._extract_org_from_cgr_image("cgr.dev/cbp.gov/node:latest") == "cbp.gov"
        assert docker_client._extract_org_from_cgr_image("cgr.dev/acme-corp/python:3.12") == "acme-corp"
        assert docker_client._extract_org_from_cgr_image("cgr.dev/chainguard-private/node:latest") is None
        assert docker_client._extract_org_from_cgr_image("cgr.dev/chainguard/node:latest") is None
        assert docker_client._extract_org_from_cgr_image("docker.io/library/python:3.12") is None
        assert docker_client._extract_org_from_cgr_image("gcr.io/project/image:tag") is None
