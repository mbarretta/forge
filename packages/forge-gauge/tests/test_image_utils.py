"""Tests for shared image utilities."""

import pytest

from forge_gauge.utils.image_utils import (
    ImageReference,
    convert_to_private_registry,
    extract_base_name,
    normalize_image_name,
)


class TestImageReferenceProperties:
    """Tests for ImageReference properties."""

    def test_full_name_simple(self):
        """Test full_name with simple image."""
        ref = ImageReference(None, None, "python", "3.12", None)
        assert ref.full_name == "python:3.12"

    def test_full_name_with_registry(self):
        """Test full_name with registry."""
        ref = ImageReference("gcr.io", "project", "app", "v1", None)
        assert ref.full_name == "gcr.io/project/app:v1"

    def test_full_name_with_digest(self):
        """Test full_name with digest."""
        ref = ImageReference(None, None, "python", None, "sha256:abc")
        assert ref.full_name == "python@sha256:abc"

    def test_name_with_org(self):
        """Test name_with_org property."""
        ref = ImageReference("gcr.io", "myorg", "app", "v1", None)
        assert ref.name_with_org == "myorg/app"

    def test_name_with_org_no_org(self):
        """Test name_with_org when no org."""
        ref = ImageReference(None, None, "python", "3.12", None)
        assert ref.name_with_org == "python"


class TestExtractBaseName:
    """Tests for extract_base_name function."""

    def test_simple_image(self):
        """Test extracting from simple image."""
        assert extract_base_name("python") == "python"

    def test_with_tag(self):
        """Test extracting from image with tag."""
        assert extract_base_name("python:3.12") == "python"

    def test_with_registry(self):
        """Test extracting from image with registry."""
        assert extract_base_name("docker.io/library/python:3.12") == "python"

    def test_with_digest(self):
        """Test extracting from image with digest."""
        assert extract_base_name("python@sha256:abc123") == "python"

    def test_complex_reference(self):
        """Test extracting from complex reference."""
        assert extract_base_name("gcr.io/my-project/subpath/myapp:v1.2.3") == "myapp"

    def test_chainguard_image(self):
        """Test extracting from Chainguard image."""
        assert extract_base_name("cgr.dev/chainguard-private/redis:latest") == "redis"

    def test_name_is_lowercase(self):
        """Test that image name is lowercased."""
        assert extract_base_name("docker.io/library/PYTHON:3.12") == "python"

    def test_registry_with_port(self):
        """Test extracting from image with registry port."""
        assert extract_base_name("localhost:5000/myimage:latest") == "myimage"

    def test_org_without_registry(self):
        """Test extracting from org/image without explicit registry."""
        assert extract_base_name("bitnami/redis:latest") == "redis"


class TestNormalizeImageName:
    """Tests for normalize_image_name function."""

    def test_basic(self):
        """Test basic normalization."""
        assert normalize_image_name("docker.io/library/PYTHON:3.12") == "python"

    def test_already_normalized(self):
        """Test already normalized name."""
        assert normalize_image_name("redis") == "redis"


class TestConvertToPrivateRegistry:
    """Tests for convert_to_private_registry function."""

    def test_public_to_private(self):
        """Test converting public Chainguard registry to private."""
        result = convert_to_private_registry("cgr.dev/chainguard/python:3.12")
        assert result == "cgr.dev/chainguard-private/python:3.12"

    def test_already_private(self):
        """Test that already-private registry is unchanged."""
        result = convert_to_private_registry("cgr.dev/chainguard-private/nginx:latest")
        assert result == "cgr.dev/chainguard-private/nginx:latest"

    def test_non_chainguard(self):
        """Test that non-Chainguard registry is unchanged."""
        result = convert_to_private_registry("docker.io/library/python:3.12")
        assert result == "docker.io/library/python:3.12"

    def test_other_registry(self):
        """Test that other registries are unchanged."""
        result = convert_to_private_registry("gcr.io/project/app:v1")
        assert result == "gcr.io/project/app:v1"
