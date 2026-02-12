"""
Version-aware matching for cgr.dev images.

Implements intelligent version matching that:
1. Matches to the latest patch version for a given major.minor
2. Falls back to the latest minor version when the matched version is EOL
3. Preserves "latest" → "latest" matching
"""

import json
import logging
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from forge_gauge.constants import (
    API_REQUEST_TIMEOUT,
    FRESHNESS_CACHE_TTL_SECONDS,
    TAG_CACHE_TTL_SECONDS,
    VERSION_FRESHNESS_THRESHOLD_DAYS,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, order=True)
class SemVer:
    """
    Semantic version with comparison operators.

    Supports parsing versions like:
    - 1.2.3
    - v1.2.3
    - 1.2 (treated as 1.2.0)
    - 1 (treated as 1.0.0)
    """
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, version_str: str) -> Optional["SemVer"]:
        """
        Parse a version string into a SemVer object.

        Args:
            version_str: Version string like "1.2.3", "v1.2.3", "1.2", "1"

        Returns:
            SemVer object or None if parsing fails
        """
        if not version_str:
            return None

        # Strip leading 'v' or 'V'
        version_str = version_str.lstrip("vV")

        # Handle suffixes like -slim, -alpine, etc. by stripping them
        # But preserve the version part
        version_str = re.split(r"[-_](?![0-9])", version_str)[0]

        # Match version patterns
        match = re.match(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?$", version_str)
        if not match:
            return None

        major = int(match.group(1))
        minor = int(match.group(2)) if match.group(2) else 0
        patch = int(match.group(3)) if match.group(3) else 0

        return cls(major=major, minor=minor, patch=patch)

    def matches_minor(self, other: "SemVer") -> bool:
        """
        Check if this version has the same major.minor as another.

        Args:
            other: Another SemVer to compare

        Returns:
            True if same major.minor
        """
        return self.major == other.major and self.minor == other.minor

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass
class VersionMatchResult:
    """Result of version resolution."""

    resolved_tag: str
    """The resolved tag to use."""

    source_version: Optional[SemVer] = None
    """Parsed version from source image."""

    matched_version: Optional[SemVer] = None
    """Version that was matched on cgr.dev."""

    is_eol_fallback: bool = False
    """True if fallback to a different minor/major was needed."""


class TagDiscoveryService:
    """
    Lists available tags on cgr.dev using skopeo.

    Results are cached for TAG_CACHE_TTL_SECONDS (default 1 hour).
    """

    def __init__(self, cache_ttl_seconds: int = TAG_CACHE_TTL_SECONDS):
        self._cache: dict[str, tuple[list[str], datetime]] = {}
        self._cache_ttl = timedelta(seconds=cache_ttl_seconds)
        self._skopeo_available: Optional[bool] = None
        self._hint_shown: bool = False

    def _check_skopeo(self) -> bool:
        """Check if skopeo is available."""
        if self._skopeo_available is not None:
            return self._skopeo_available

        try:
            result = subprocess.run(
                ["skopeo", "--version"],
                capture_output=True,
                timeout=5,
            )
            self._skopeo_available = result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            self._skopeo_available = False

        return self._skopeo_available

    def list_tags(self, image_base: str) -> list[str]:
        """
        List all tags available for an image.

        Args:
            image_base: Image reference without tag (e.g., "cgr.dev/chainguard-private/nginx")

        Returns:
            List of available tags
        """
        # Check cache
        now = datetime.now(timezone.utc)
        if image_base in self._cache:
            tags, cached_at = self._cache[image_base]
            if now - cached_at < self._cache_ttl:
                logger.debug(f"Tag cache hit for {image_base}")
                return tags

        if not self._check_skopeo():
            if not self._hint_shown:
                print(
                    "Note: skopeo is not installed. Version matching is disabled — "
                    "all cgr.dev images will use ':latest'.\n"
                    "  Install skopeo for version-appropriate tag matching: "
                    "https://github.com/containers/skopeo/blob/main/install.md"
                )
                self._hint_shown = True
            return []

        try:
            cmd = ["skopeo", "list-tags", f"docker://{image_base}"]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=API_REQUEST_TIMEOUT,
            )

            if result.returncode != 0:
                logger.debug(f"skopeo list-tags failed for {image_base}: {result.stderr}")
                return []

            data = json.loads(result.stdout)
            tags = data.get("Tags", [])

            # Cache the result
            self._cache[image_base] = (tags, now)
            logger.debug(f"Found {len(tags)} tags for {image_base}")

            return tags

        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
            logger.debug(f"Failed to list tags for {image_base}: {e}")
            return []

    def get_semver_tags(self, image_base: str) -> list[SemVer]:
        """
        Get all semver-parseable tags for an image.

        Args:
            image_base: Image reference without tag

        Returns:
            List of SemVer objects, sorted descending (newest first)
        """
        tags = self.list_tags(image_base)
        semvers = []

        for tag in tags:
            semver = SemVer.parse(tag)
            if semver:
                semvers.append(semver)

        # Sort descending (newest first)
        return sorted(semvers, reverse=True)

    def clear_cache(self) -> None:
        """Clear the tag cache."""
        self._cache.clear()


class TagFreshnessChecker:
    """
    Checks image freshness via org.opencontainers.image.created label.

    Results are cached for FRESHNESS_CACHE_TTL_SECONDS (default 24 hours).
    """

    OCI_CREATED_LABEL = "org.opencontainers.image.created"

    def __init__(
        self,
        cache_ttl_seconds: int = FRESHNESS_CACHE_TTL_SECONDS,
        get_label_func=None,
    ):
        self._cache: dict[str, tuple[Optional[datetime], datetime]] = {}
        self._cache_ttl = timedelta(seconds=cache_ttl_seconds)
        self._get_label_func = get_label_func
        self._skopeo_available: Optional[bool] = None

    def _check_skopeo(self) -> bool:
        """Check if skopeo is available."""
        if self._skopeo_available is not None:
            return self._skopeo_available

        try:
            result = subprocess.run(
                ["skopeo", "--version"],
                capture_output=True,
                timeout=5,
            )
            self._skopeo_available = result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            self._skopeo_available = False

        return self._skopeo_available

    def _get_label(self, image_ref: str, label: str) -> Optional[str]:
        """Get a label from an image using skopeo or injected function."""
        if self._get_label_func:
            return self._get_label_func(image_ref, label)

        if not self._check_skopeo():
            return None

        try:
            cmd = ["skopeo", "inspect", f"docker://{image_ref}"]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=API_REQUEST_TIMEOUT,
            )

            if result.returncode != 0:
                logger.debug(f"skopeo inspect failed for {image_ref}: {result.stderr}")
                return None

            data = json.loads(result.stdout)
            labels = data.get("Labels", {}) or {}
            return labels.get(label)

        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
            logger.debug(f"Failed to get label for {image_ref}: {e}")
            return None

    def get_created_date(self, image_ref: str) -> Optional[datetime]:
        """
        Get the creation date of an image.

        Args:
            image_ref: Full image reference (e.g., "cgr.dev/chainguard-private/nginx:1.27.0")

        Returns:
            Creation datetime (UTC) or None if unavailable
        """
        # Check cache
        now = datetime.now(timezone.utc)
        if image_ref in self._cache:
            created, cached_at = self._cache[image_ref]
            if now - cached_at < self._cache_ttl:
                logger.debug(f"Freshness cache hit for {image_ref}")
                return created

        created_str = self._get_label(image_ref, self.OCI_CREATED_LABEL)
        if not created_str:
            self._cache[image_ref] = (None, now)
            return None

        # Parse ISO 8601 timestamp
        try:
            # Handle various ISO 8601 formats
            # Remove trailing 'Z' and replace with +00:00 for parsing
            if created_str.endswith("Z"):
                created_str = created_str[:-1] + "+00:00"

            created = datetime.fromisoformat(created_str)

            # Ensure UTC
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)

            self._cache[image_ref] = (created, now)
            return created

        except ValueError as e:
            logger.debug(f"Failed to parse created date '{created_str}': {e}")
            self._cache[image_ref] = (None, now)
            return None

    def is_fresh(
        self,
        image_ref: str,
        threshold_days: int = VERSION_FRESHNESS_THRESHOLD_DAYS,
    ) -> bool:
        """
        Check if an image is fresh (built within threshold days).

        Args:
            image_ref: Full image reference
            threshold_days: Number of days to consider "fresh"

        Returns:
            True if image was created within threshold_days, False otherwise.
            Returns True if creation date cannot be determined (assume fresh).
        """
        created = self.get_created_date(image_ref)

        if created is None:
            # If we can't determine the date, assume it's fresh to avoid
            # unnecessary fallbacks
            logger.debug(f"Cannot determine creation date for {image_ref}, assuming fresh")
            return True

        now = datetime.now(timezone.utc)
        age = now - created
        is_fresh = age.days <= threshold_days

        if not is_fresh:
            logger.debug(f"Image {image_ref} is stale ({age.days} days old)")

        return is_fresh

    def clear_cache(self) -> None:
        """Clear the freshness cache."""
        self._cache.clear()


class VersionMatcher:
    """
    Main orchestrator for version resolution.

    Resolves source image tags to appropriate cgr.dev tags based on:
    1. Exact major.minor match with latest patch
    2. EOL fallback to latest available version
    3. Freshness checks via image build dates
    """

    def __init__(
        self,
        tag_discovery: Optional[TagDiscoveryService] = None,
        freshness_checker: Optional[TagFreshnessChecker] = None,
        freshness_threshold_days: int = VERSION_FRESHNESS_THRESHOLD_DAYS,
    ):
        self.tag_discovery = tag_discovery or TagDiscoveryService()
        self.freshness_checker = freshness_checker or TagFreshnessChecker()
        self.freshness_threshold_days = freshness_threshold_days

    def resolve(self, source_image: str, chainguard_base: str) -> VersionMatchResult:
        """
        Resolve the best tag for a Chainguard image based on source version.

        Algorithm:
        1. If source tag is "latest" or empty → return "latest"
        2. Parse source tag as semver; if not parseable → return "latest"
        3. List available semver tags on cgr.dev for the image
        4. Find latest patch matching source major.minor
        5. If no match for major.minor, find latest patch of any version
        6. Check freshness of matched version via org.opencontainers.image.created
        7. If stale (>7 days old), find latest fresh version instead
        8. Return resolved tag

        Args:
            source_image: Source image reference (e.g., "nginx:1.27.0")
            chainguard_base: Chainguard image base without tag (e.g., "cgr.dev/chainguard-private/nginx")

        Returns:
            VersionMatchResult with resolved tag and metadata
        """
        # Extract source tag
        source_tag = self._extract_tag(source_image)

        # Rule 1: Latest passthrough
        if not source_tag or source_tag.lower() == "latest":
            logger.debug(f"Source tag is 'latest' or empty, using 'latest'")
            return VersionMatchResult(resolved_tag="latest")

        # Skip digest references
        if "@sha256:" in source_image:
            logger.debug(f"Source is digest reference, using 'latest'")
            return VersionMatchResult(resolved_tag="latest")

        # Rule 2: Parse source version
        source_version = SemVer.parse(source_tag)
        if source_version is None:
            logger.debug(f"Cannot parse '{source_tag}' as semver, using 'latest'")
            return VersionMatchResult(resolved_tag="latest")

        # Rule 3: Get available versions on cgr.dev
        available_versions = self.tag_discovery.get_semver_tags(chainguard_base)
        if not available_versions:
            logger.debug(f"No semver tags found on cgr.dev for {chainguard_base}, using 'latest'")
            return VersionMatchResult(
                resolved_tag="latest",
                source_version=source_version,
            )

        # Rule 4: Find latest patch for source major.minor
        matched_version = self._find_latest_patch(source_version, available_versions)
        is_eol_fallback = False

        # Rule 5: If no match for major.minor, use latest available
        if matched_version is None:
            logger.info(
                f"No cgr.dev version matching {source_version.major}.{source_version.minor}.x, "
                f"using latest available"
            )
            matched_version = available_versions[0]  # Already sorted descending
            is_eol_fallback = True

        # Build the image reference for freshness check
        matched_tag = str(matched_version)
        matched_image_ref = f"{chainguard_base}:{matched_tag}"

        # Rule 6 & 7: Check freshness
        if not self.freshness_checker.is_fresh(
            matched_image_ref,
            self.freshness_threshold_days,
        ):
            # Image is stale, find a fresh alternative
            fresh_version = self._find_fresh_version(chainguard_base, available_versions)

            if fresh_version and fresh_version != matched_version:
                logger.info(
                    f"Matched version {matched_version} is stale, "
                    f"falling back to fresh version {fresh_version}"
                )
                matched_version = fresh_version
                is_eol_fallback = True

        logger.debug(
            f"Resolved {source_image} → {chainguard_base}:{matched_version} "
            f"(eol_fallback={is_eol_fallback})"
        )

        return VersionMatchResult(
            resolved_tag=str(matched_version),
            source_version=source_version,
            matched_version=matched_version,
            is_eol_fallback=is_eol_fallback,
        )

    def _extract_tag(self, image: str) -> Optional[str]:
        """Extract tag from image reference."""
        # Handle digest references
        if "@" in image:
            image = image.split("@")[0]

        # Extract tag
        if ":" in image:
            # Check if : is part of registry (e.g., localhost:5000)
            parts = image.split("/")
            last_part = parts[-1]
            if ":" in last_part:
                return last_part.split(":", 1)[1]

        return None

    def _find_latest_patch(
        self,
        source: SemVer,
        available: list[SemVer],
    ) -> Optional[SemVer]:
        """
        Find the latest patch version matching source major.minor.

        Args:
            source: Source version to match
            available: Available versions (sorted descending)

        Returns:
            Latest matching version or None
        """
        for version in available:
            if version.matches_minor(source):
                return version
        return None

    def _find_fresh_version(
        self,
        chainguard_base: str,
        available: list[SemVer],
    ) -> Optional[SemVer]:
        """
        Find the latest fresh version.

        Args:
            chainguard_base: Chainguard image base
            available: Available versions (sorted descending)

        Returns:
            Latest fresh version or None
        """
        for version in available:
            image_ref = f"{chainguard_base}:{version}"
            if self.freshness_checker.is_fresh(image_ref, self.freshness_threshold_days):
                return version

        # No fresh version found, return the latest anyway
        return available[0] if available else None
