"""Tests for input validation utilities."""

import pytest
from pathlib import Path

from forge_gauge.core.exceptions import ValidationException
from forge_gauge.utils.validation import (
    looks_like_image_reference,
    validate_image_reference,
    validate_file_path,
    validate_positive_number,
    validate_customer_name,
)


class TestLooksLikeImageReference:
    """Tests for looks_like_image_reference heuristic."""

    def test_image_with_tag(self):
        """Test image with version tag is detected."""
        assert looks_like_image_reference("python:3.12") is True
        assert looks_like_image_reference("nginx:latest") is True
        assert looks_like_image_reference("nginx:1.25.0") is True

    def test_image_with_registry(self):
        """Test image with registry prefix is detected."""
        assert looks_like_image_reference("gcr.io/project/image:v1") is True
        assert looks_like_image_reference("docker.io/library/nginx:latest") is True
        assert looks_like_image_reference("ghcr.io/owner/repo:tag") is True
        assert looks_like_image_reference("quay.io/org/image:v2") is True
        assert looks_like_image_reference("cgr.dev/chainguard/python:latest") is True

    def test_image_with_digest(self):
        """Test image with digest is detected."""
        assert looks_like_image_reference("nginx@sha256:abc123") is True
        assert looks_like_image_reference("python:3.12@sha256:abc123") is True
        assert looks_like_image_reference("image@sha512:def456") is True

    def test_ecr_images(self):
        """Test AWS ECR images are detected."""
        assert looks_like_image_reference("123456789.dkr.ecr.us-east-1.amazonaws.com/my-app:latest") is True
        assert looks_like_image_reference("public.ecr.aws/nginx/nginx:latest") is True

    def test_azure_images(self):
        """Test Azure ACR images are detected."""
        assert looks_like_image_reference("myregistry.azurecr.io/myimage:v1") is True

    def test_file_paths_not_detected(self):
        """Test file paths are not detected as images."""
        assert looks_like_image_reference("images.csv") is False
        assert looks_like_image_reference("./images.csv") is False
        assert looks_like_image_reference("../data/images.txt") is False
        assert looks_like_image_reference("/absolute/path/file.yaml") is False
        assert looks_like_image_reference("data.json") is False

    def test_relative_paths_not_detected(self):
        """Test relative paths starting with ./ or ../ are not detected."""
        assert looks_like_image_reference("./nginx:latest") is False
        assert looks_like_image_reference("../nginx:latest") is False

    def test_empty_and_whitespace(self):
        """Test empty and whitespace-only strings."""
        assert looks_like_image_reference("") is False
        assert looks_like_image_reference("   ") is False
        assert looks_like_image_reference(None) is False

    def test_complex_tags(self):
        """Test images with complex version tags."""
        assert looks_like_image_reference("eks/csi-node-driver-registrar:v2.15.0-eksbuild.3") is True
        assert looks_like_image_reference("my-image:v1.2.3-beta.1") is True
        assert looks_like_image_reference("app:20240101") is True

    def test_simple_names_without_tag(self):
        """Test simple names without tags are not detected (could be files)."""
        # These are ambiguous - could be files or images
        # We conservatively treat them as files
        assert looks_like_image_reference("nginx") is False
        assert looks_like_image_reference("myimage") is False


class TestValidateImageReference:
    """Tests for image reference validation."""

    def test_valid_simple_image(self):
        """Test valid simple image name."""
        result = validate_image_reference("python:3.12")
        assert result == "python:3.12"

    def test_valid_registry_image(self):
        """Test valid image with registry."""
        result = validate_image_reference("cgr.dev/chainguard/python:latest")
        assert result == "cgr.dev/chainguard/python:latest"

    def test_valid_with_underscores(self):
        """Test valid image with underscores."""
        result = validate_image_reference("my_custom_image:v1.0")
        assert result == "my_custom_image:v1.0"

    def test_valid_digest_only(self):
        """Test valid image with digest only (no tag)."""
        result = validate_image_reference(
            "longhornio/longhorn-instance-manager@sha256:76c527b1a4b0d1d2a07e65f58fb65bed5b6dcd23f27ad945bf8afb452eadd137"
        )
        assert "@sha256:" in result

    def test_valid_tag_and_digest(self):
        """Test valid image with both tag and digest."""
        result = validate_image_reference(
            "python:3.12@sha256:abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
        )
        assert ":3.12@sha256:" in result

    def test_valid_registry_with_digest(self):
        """Test valid image with registry and digest."""
        result = validate_image_reference(
            "cgr.dev/chainguard/python@sha256:abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
        )
        assert result.startswith("cgr.dev/chainguard/python@sha256:")

    def test_valid_sha512_digest(self):
        """Test valid image with sha512 digest."""
        result = validate_image_reference(
            "python@sha512:abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
        )
        assert "@sha512:" in result

    def test_empty_image(self):
        """Test empty image reference."""
        with pytest.raises(ValidationException) as exc:
            validate_image_reference("")
        assert "cannot be empty" in str(exc.value)

    def test_whitespace_only(self):
        """Test whitespace-only image reference."""
        with pytest.raises(ValidationException) as exc:
            validate_image_reference("   ")
        assert "cannot be empty" in str(exc.value)

    def test_invalid_characters(self):
        """Test image with invalid characters."""
        invalid_images = [
            'python"3.12',  # quotes
            "python;latest",  # semicolon
            "python&latest",  # ampersand
            "python|latest",  # pipe
            "python$latest",  # dollar sign
            "python`latest",  # backtick
        ]
        for img in invalid_images:
            with pytest.raises(ValidationException) as exc:
                validate_image_reference(img)
            assert "invalid characters" in str(exc.value)

    def test_strips_whitespace(self):
        """Test that whitespace is stripped."""
        result = validate_image_reference("  python:3.12  ")
        assert result == "python:3.12"

    def test_custom_field_name(self):
        """Test custom field name in error message."""
        with pytest.raises(ValidationException) as exc:
            validate_image_reference("", "my_custom_field")
        assert "my_custom_field" in str(exc.value)


class TestValidateFilePath:
    """Tests for file path validation."""

    def test_valid_existing_file(self, temp_csv_file):
        """Test validation of existing file."""
        result = validate_file_path(temp_csv_file, must_exist=True)
        assert result == temp_csv_file

    def test_non_existent_file_required(self, tmp_path):
        """Test validation fails for non-existent file when required."""
        non_existent = tmp_path / "does_not_exist.txt"
        with pytest.raises(ValidationException) as exc:
            validate_file_path(non_existent, must_exist=True)
        assert "File not found" in str(exc.value)

    def test_non_existent_file_optional(self, tmp_path):
        """Test validation passes for non-existent file when not required."""
        non_existent = tmp_path / "does_not_exist.txt"
        result = validate_file_path(non_existent, must_exist=False)
        assert result == non_existent

    def test_empty_path(self):
        """Test validation fails for empty path."""
        with pytest.raises(ValidationException) as exc:
            validate_file_path(None)
        assert "cannot be empty" in str(exc.value)


class TestValidatePositiveNumber:
    """Tests for positive number validation."""

    def test_valid_number(self):
        """Test valid positive number."""
        result = validate_positive_number(10.5, "test_field")
        assert result == 10.5

    def test_zero_with_default_min(self):
        """Test zero is valid with default min (0.0)."""
        result = validate_positive_number(0.0, "test_field")
        assert result == 0.0

    def test_below_minimum(self):
        """Test number below minimum."""
        with pytest.raises(ValidationException) as exc:
            validate_positive_number(-5.0, "test_field", min_value=0.0)
        assert "must be >=" in str(exc.value)
        assert "test_field" in str(exc.value)

    def test_above_maximum(self):
        """Test number above maximum."""
        with pytest.raises(ValidationException) as exc:
            validate_positive_number(150.0, "test_field", max_value=100.0)
        assert "must be <=" in str(exc.value)
        assert "test_field" in str(exc.value)

    def test_within_range(self):
        """Test number within specified range."""
        result = validate_positive_number(
            50.0,
            "test_field",
            min_value=10.0,
            max_value=100.0,
        )
        assert result == 50.0


class TestValidateCustomerName:
    """Tests for customer name validation."""

    def test_valid_simple_name(self):
        """Test valid simple customer name."""
        result = validate_customer_name("Acme Corp")
        assert result == "Acme Corp"

    def test_strips_whitespace(self):
        """Test whitespace is stripped."""
        result = validate_customer_name("  Acme Corp  ")
        assert result == "Acme Corp"

    def test_empty_name(self):
        """Test empty customer name."""
        with pytest.raises(ValidationException) as exc:
            validate_customer_name("")
        assert "cannot be empty" in str(exc.value)

    def test_whitespace_only(self):
        """Test whitespace-only customer name."""
        with pytest.raises(ValidationException) as exc:
            validate_customer_name("   ")
        assert "cannot be empty" in str(exc.value)

    def test_invalid_characters(self):
        """Test customer name with invalid characters."""
        invalid_names = [
            "Acme/Corp",  # forward slash
            "Acme\\Corp",  # backslash
            "Acme<Corp>",  # angle brackets
            'Acme"Corp',  # quotes
            "Acme;Corp",  # semicolon
            "Acme&Corp",  # ampersand
            "Acme|Corp",  # pipe
        ]
        for name in invalid_names:
            with pytest.raises(ValidationException) as exc:
                validate_customer_name(name)
            assert "invalid characters" in str(exc.value)

    def test_too_long(self):
        """Test customer name that is too long."""
        long_name = "A" * 101  # Over 100 character limit
        with pytest.raises(ValidationException) as exc:
            validate_customer_name(long_name)
        assert "too long" in str(exc.value)

    def test_max_length(self):
        """Test customer name at maximum length."""
        max_name = "A" * 100
        result = validate_customer_name(max_name)
        assert result == max_name
