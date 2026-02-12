"""
Input validation utilities for Gauge application.

Provides validation functions for image references, file paths,
and other user inputs to ensure data integrity and security.
"""

import re
from pathlib import Path
from typing import Optional

from forge_gauge.core.exceptions import ValidationException


def looks_like_image_reference(value: str) -> bool:
    """
    Check if a string looks like a container image reference rather than a file path.

    This is a heuristic check used to determine if --input should be treated as
    a single image or as a file path. Returns True if the value:
    - Contains a tag separator (:) with what looks like a version tag
    - Contains a digest reference (@sha256: or @sha512:)
    - Contains a registry pattern (e.g., gcr.io/, docker.io/, cgr.dev/)

    Args:
        value: String to check

    Returns:
        True if value looks like an image reference, False otherwise

    Examples:
        >>> looks_like_image_reference("python:3.12")
        True
        >>> looks_like_image_reference("nginx:latest")
        True
        >>> looks_like_image_reference("gcr.io/project/image:v1")
        True
        >>> looks_like_image_reference("images.csv")
        False
        >>> looks_like_image_reference("./path/to/file.txt")
        False
    """
    if not value or not value.strip():
        return False

    value = value.strip()

    # File path indicators - these are definitely not images
    if value.startswith(("./", "../", "/")):
        return False
    if value.endswith((".csv", ".txt", ".yaml", ".yml", ".json")):
        return False

    # Digest reference is definitely an image
    if "@sha256:" in value or "@sha512:" in value:
        return True

    # Check for registry patterns (common registries)
    registry_patterns = [
        "gcr.io/", "docker.io/", "ghcr.io/", "quay.io/",
        "cgr.dev/", "registry.k8s.io/", "mcr.microsoft.com/",
        "public.ecr.aws/", ".dkr.ecr.", ".azurecr.io/",
    ]
    if any(pattern in value for pattern in registry_patterns):
        return True

    # Check for tag pattern: contains : followed by tag-like string (not a drive letter)
    # Tags typically look like: :latest, :v1.2.3, :1.0, :stable, etc.
    if ":" in value:
        parts = value.rsplit(":", 1)
        if len(parts) == 2:
            tag = parts[1]
            # Tag should be alphanumeric with dots, dashes, underscores
            # and not look like a file extension
            if tag and re.match(r'^[a-zA-Z0-9][a-zA-Z0-9._-]*$', tag):
                # Exclude common file extensions
                if not tag.lower() in ("csv", "txt", "yaml", "yml", "json", "md"):
                    return True

    # Check for repo/image pattern without tag (e.g., "nginx", "library/python")
    # Must contain at least one slash to distinguish from simple filenames
    if "/" in value and ":" not in value and "@" not in value:
        # Could be a path or an image - check if it exists as a file
        # If we can't tell, assume it's a file path for safety
        return False

    return False


def validate_image_reference(image: str, field_name: str = "image") -> str:
    """
    Validate and normalize container image reference.

    Args:
        image: Image reference to validate
        field_name: Field name for error messages

    Returns:
        Normalized image reference

    Raises:
        ValidationException: If image reference is invalid

    Examples:
        >>> validate_image_reference("python:3.12")
        'python:3.12'
        >>> validate_image_reference("cgr.dev/chainguard/python:latest")
        'cgr.dev/chainguard/python:latest'
        >>> validate_image_reference("invalid image!")
        ValidationException: ...
    """
    if not image or not image.strip():
        raise ValidationException("Image reference cannot be empty", field_name)

    image = image.strip()

    # Check for obviously invalid characters
    if any(char in image for char in ['"', "'", ";", "&", "|", "$", "`", "\n", "\r"]):
        raise ValidationException(
            f"Image reference contains invalid characters: {image}",
            field_name
        )

    # Basic format validation (registry/repo:tag, repo@digest, or repo:tag@digest)
    # Allows: lowercase alphanumeric, dots, slashes, colons, hyphens, underscores
    # Supports digest format: @sha256:hex or @sha512:hex
    pattern = r'^[a-z0-9]+([\._\-][a-z0-9]+)*(\/[a-z0-9]+([\._\-][a-z0-9]+)*)*(:[a-zA-Z0-9\._\-]+)?(@[a-z0-9]+:[a-f0-9]+)?$'
    if not re.match(pattern, image, re.IGNORECASE):
        raise ValidationException(
            f"Invalid image reference format: {image}",
            field_name
        )

    return image


def validate_file_path(path: Path, must_exist: bool = True) -> Path:
    """
    Validate file path.

    Args:
        path: Path to validate
        must_exist: Whether file must already exist

    Returns:
        Validated Path object

    Raises:
        ValidationException: If path is invalid
    """
    if not path:
        raise ValidationException("File path cannot be empty", "path")

    if must_exist and not path.exists():
        raise ValidationException(f"File not found: {path}", "path")

    return path


def validate_positive_number(
    value: float,
    field_name: str,
    min_value: float = 0.0,
    max_value: Optional[float] = None,
) -> float:
    """
    Validate numeric value is within acceptable range.

    Args:
        value: Value to validate
        field_name: Field name for error messages
        min_value: Minimum acceptable value
        max_value: Maximum acceptable value (optional)

    Returns:
        Validated value

    Raises:
        ValidationException: If value is out of range
    """
    if value < min_value:
        raise ValidationException(
            f"Value must be >= {min_value}, got {value}",
            field_name
        )

    if max_value is not None and value > max_value:
        raise ValidationException(
            f"Value must be <= {max_value}, got {value}",
            field_name
        )

    return value


def validate_customer_name(name: str) -> str:
    """
    Validate and normalize customer name.

    Args:
        name: Customer name to validate

    Returns:
        Normalized customer name

    Raises:
        ValidationException: If name is invalid
    """
    if not name or not name.strip():
        raise ValidationException("Customer name cannot be empty", "customer_name")

    name = name.strip()

    # Prevent path traversal and injection attempts
    # Customer names are used in filenames, so restrict special characters
    if any(char in name for char in ["/", "\\", "<", ">", '"', "'", ";", "|", "&"]):
        raise ValidationException(
            "Customer name contains invalid characters",
            "customer_name"
        )

    if len(name) > 100:
        raise ValidationException(
            "Customer name too long (max 100 characters)",
            "customer_name"
        )

    return name


__all__ = [
    "looks_like_image_reference",
    "validate_image_reference",
    "validate_file_path",
    "validate_positive_number",
    "validate_customer_name",
]
