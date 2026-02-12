"""
Shared utilities for parsing and manipulating container image references.

This module provides the canonical ImageReference dataclass for parsing container
image references, used across all modules that need to manipulate image names.
"""

import re
from dataclasses import dataclass
from typing import Optional

from forge_gauge.constants import CHAINGUARD_PRIVATE_REGISTRY, CHAINGUARD_PUBLIC_REGISTRY


@dataclass
class ImageReference:
    """
    Parsed container image reference.

    Canonical representation of a container image reference with methods for
    common operations like extracting base names and converting registries.
    """

    registry: Optional[str]
    """Registry hostname (e.g., 'gcr.io', 'docker.io'). None for Docker Hub short names."""

    organization: Optional[str]
    """Organization/namespace (e.g., 'chainguard-private', 'library'). For cgr.dev images."""

    name: str
    """Image name without registry, org, tag, or digest."""

    tag: Optional[str]
    """Image tag (e.g., 'latest', '3.12'). None if digest is used."""

    digest: Optional[str]
    """Image digest (e.g., 'sha256:abc...'). None if tag is used."""

    @classmethod
    def parse(cls, image: str) -> "ImageReference":
        """
        Parse a container image reference string.

        Handles various formats:
            - nginx:latest -> registry=docker.io, org=library, name=nginx
            - library/nginx:latest -> registry=docker.io, org=library, name=nginx
            - docker.io/library/nginx:latest -> full form
            - gcr.io/project/image:tag -> GCR format
            - cgr.dev/chainguard/python:latest -> Chainguard format
            - cgr.dev/org.name/image:latest -> Chainguard org format
            - image@sha256:abc... -> digest format

        Args:
            image: Image reference string

        Returns:
            Parsed ImageReference
        """
        original = image
        registry = None
        organization = None
        tag = None
        digest = None

        # Extract digest first (after @)
        if "@" in image:
            image, digest = image.rsplit("@", 1)

        # Extract tag (after last :, but only if it's after any /)
        if ":" in image:
            if "/" in image:
                last_slash = image.rfind("/")
                last_colon = image.rfind(":")
                if last_colon > last_slash:
                    image, tag = image.rsplit(":", 1)
            else:
                # No slash means : must be a tag
                image, tag = image.rsplit(":", 1)

        # Parse the path components
        parts = image.split("/")

        if len(parts) == 1:
            # Short form: nginx -> docker.io/library/nginx
            registry = "docker.io"
            organization = "library"
            name = parts[0]
        elif len(parts) == 2:
            first_part = parts[0]
            # Check if first part looks like a registry
            if "." in first_part or ":" in first_part or first_part == "localhost":
                # registry/image format (e.g., gcr.io/image or localhost:5000/image)
                registry = first_part
                organization = None
                name = parts[1]
            else:
                # org/image format (e.g., library/nginx)
                registry = "docker.io"
                organization = first_part
                name = parts[1]
        elif len(parts) >= 3:
            first_part = parts[0]
            # Check if first part looks like a registry
            if "." in first_part or ":" in first_part or first_part == "localhost":
                registry = first_part
                # For cgr.dev, the second part is the organization
                if first_part == "cgr.dev":
                    organization = parts[1]
                    name = "/".join(parts[2:])
                else:
                    # For other registries, join remaining parts
                    organization = parts[1] if len(parts) > 2 else None
                    name = "/".join(parts[2:]) if len(parts) > 2 else parts[1]
            else:
                # No registry prefix
                registry = "docker.io"
                organization = parts[0]
                name = "/".join(parts[1:])

        return cls(
            registry=registry,
            organization=organization,
            name=name.lower() if name else "",
            tag=tag,
            digest=digest,
        )

    @property
    def full_name(self) -> str:
        """Return the full image reference."""
        parts = []
        if self.registry:
            parts.append(self.registry)
        if self.organization:
            parts.append(self.organization)
        parts.append(self.name)

        result = "/".join(parts)

        if self.digest:
            result = f"{result}@{self.digest}"
        elif self.tag:
            result = f"{result}:{self.tag}"

        return result

    @property
    def name_with_org(self) -> str:
        """Return org/name if org exists, otherwise just name."""
        if self.organization:
            return f"{self.organization}/{self.name}"
        return self.name

    def base_name(self, strip_fips: bool = False, strip_version: bool = False) -> str:
        """
        Get the base image name (final path component only).

        Args:
            strip_fips: If True, remove -fips suffix
            strip_version: If True, remove version suffixes (e.g., redis7 -> redis)

        Returns:
            Base image name (lowercase, final component only)
        """
        # Get just the final component if there are path segments
        name = self.name.lower()
        if "/" in name:
            name = name.rsplit("/", 1)[-1]

        if strip_fips:
            name = re.sub(r"[-_]fips$", "", name)

        if strip_version:
            # Strip version patterns like "-9", "_8.x", "7", "33", "v3"
            name = re.sub(r'v\d+(?:\.\w+)?$', '', name)
            name = re.sub(r'[-_]?\d+(?:\.\w+)?$', '', name)

        return name

    def is_chainguard(self) -> bool:
        """Check if this is a Chainguard registry image."""
        return self.registry == "cgr.dev"

    def is_chainguard_private(self) -> bool:
        """Check if this is a Chainguard private registry image."""
        return self.registry == "cgr.dev" and self.organization == "chainguard-private"

    def is_chainguard_public(self) -> bool:
        """Check if this is a Chainguard public registry image."""
        return self.registry == "cgr.dev" and self.organization == "chainguard"

    def to_chainguard_private(self) -> Optional[str]:
        """
        Convert to chainguard-private registry form.

        For cgr.dev/<org>/<image> images, converts to cgr.dev/chainguard-private/<image>.
        Returns None if not applicable (not a cgr.dev image, or already chainguard-private/chainguard).

        Returns:
            Converted image reference or None if not applicable
        """
        if not self.is_chainguard():
            return None

        # Skip if already chainguard-private or public chainguard
        if self.organization in ("chainguard-private", "chainguard"):
            return None

        # Construct the private image reference
        tag_or_digest = ""
        if self.digest:
            tag_or_digest = f"@{self.digest}"
        elif self.tag:
            tag_or_digest = f":{self.tag}"

        return f"cgr.dev/chainguard-private/{self.name}{tag_or_digest}"

    def with_registry(self, registry: str, organization: Optional[str] = None) -> "ImageReference":
        """
        Return a new ImageReference with a different registry.

        Args:
            registry: New registry hostname
            organization: New organization (optional)

        Returns:
            New ImageReference with updated registry/org
        """
        return ImageReference(
            registry=registry,
            organization=organization,
            name=self.name,
            tag=self.tag,
            digest=self.digest,
        )

    def with_tag(self, tag: str) -> "ImageReference":
        """
        Return a new ImageReference with a different tag.

        Args:
            tag: New tag

        Returns:
            New ImageReference with updated tag (digest cleared)
        """
        return ImageReference(
            registry=self.registry,
            organization=self.organization,
            name=self.name,
            tag=tag,
            digest=None,
        )


def extract_base_name(image: str) -> str:
    """
    Extract base image name from full reference.

    Removes registry, organization, tag, and digest to get just the image name.

    Args:
        image: Full image reference

    Returns:
        Base image name (lowercase)

    Examples:
        >>> extract_base_name("docker.io/library/python:3.12")
        'python'
        >>> extract_base_name("cgr.dev/chainguard/redis:latest")
        'redis'
        >>> extract_base_name("myregistry.com/org/app@sha256:abc")
        'app'
    """
    return ImageReference.parse(image).base_name()


def normalize_image_name(image: str) -> str:
    """
    Normalize image name for comparison.

    Extracts base name and normalizes to lowercase.

    Args:
        image: Full image reference

    Returns:
        Normalized image name
    """
    return extract_base_name(image).lower()


def convert_to_private_registry(image_ref: str) -> str:
    """
    Convert public Chainguard registry reference to private.

    Args:
        image_ref: Image reference that may use public registry

    Returns:
        Image reference with private registry prefix if it was public,
        otherwise returns the original reference unchanged.

    Examples:
        >>> convert_to_private_registry("cgr.dev/chainguard/python:3.12")
        'cgr.dev/chainguard-private/python:3.12'
        >>> convert_to_private_registry("cgr.dev/chainguard-private/nginx:latest")
        'cgr.dev/chainguard-private/nginx:latest'
        >>> convert_to_private_registry("docker.io/library/python:3.12")
        'docker.io/library/python:3.12'
    """
    if image_ref.startswith(f"{CHAINGUARD_PUBLIC_REGISTRY}/"):
        return image_ref.replace(
            f"{CHAINGUARD_PUBLIC_REGISTRY}/",
            f"{CHAINGUARD_PRIVATE_REGISTRY}/",
            1
        )
    return image_ref


def extract_registry_from_image(image: str) -> str:
    """
    Extract registry hostname from image reference.

    Args:
        image: Full image reference (e.g., "nginx:latest", "gcr.io/project/app:v1")

    Returns:
        Registry hostname. Returns "docker.io" for Docker Hub images.

    Examples:
        "nginx:latest" -> "docker.io"
        "library/nginx:latest" -> "docker.io"
        "registry1.dso.mil/ironbank/nginx:1.25" -> "registry1.dso.mil"
        "gcr.io/myproject/app:v1" -> "gcr.io"
    """
    ref = ImageReference.parse(image)
    return ref.registry or "docker.io"


def extract_org_from_cgr_image(image: str) -> Optional[str]:
    """
    Extract the organization from a cgr.dev image reference.

    Args:
        image: Image reference like cgr.dev/cbp.gov/node:latest

    Returns:
        Organization name (e.g., "cbp.gov") or None if not a cgr.dev org image
    """
    ref = ImageReference.parse(image)
    if not ref.is_chainguard():
        return None

    # Skip if already chainguard-private or public chainguard
    if ref.organization in ("chainguard-private", "chainguard"):
        return None

    return ref.organization
