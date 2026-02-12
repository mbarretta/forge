"""
Docker/Podman utility functions for image operations.

Provides a unified interface for working with container images,
supporting both Docker and Podman automatically.
"""

import json
import logging
import os
import re
import subprocess
from typing import Optional

from forge_gauge.constants import (
    API_REQUEST_TIMEOUT,
    CLI_SUBPROCESS_TIMEOUT,
    DEFAULT_PLATFORM,
    DOCKER_PULL_TIMEOUT,
    GITHUB_CLI_TIMEOUT,
    VERSION_CHECK_TIMEOUT,
)
from forge_gauge.core.error_patterns import (
    classify_error_type as _classify_error_type,
    is_auth_error as _is_auth_error,
    is_recoverable_error as _is_recoverable_error,
)
from forge_gauge.utils.image_utils import (
    ImageReference,
    extract_org_from_cgr_image,
    extract_registry_from_image,
)
from forge_gauge.utils.pull_strategies import (
    ChainguardPrivateFallbackStrategy,
    LatestTagFallbackStrategy,
    MirrorGCRFallbackStrategy,
    PullContext,
    PullStrategy,
    SkopeoMostRecentStrategy,
    UpstreamFallbackStrategy,
)
from forge_gauge.utils.validation import validate_image_reference

logger = logging.getLogger(__name__)


class DockerClient:
    """
    Unified client for Docker/Podman operations.

    Automatically detects available container runtime (docker or podman)
    and provides a consistent interface for image operations.
    """

    def __init__(self, support_mode_org: Optional[str] = None):
        """
        Initialize Docker client and detect available runtime.

        Args:
            support_mode_org: If provided, enables support mode for this organization,
                skipping org registry attempts and going directly to chainguard-private.
                This should be set when authenticated as a support identity.
        """
        self.runtime = self._detect_runtime()
        if not self.runtime:
            raise RuntimeError("Neither docker nor podman found in PATH")
        logger.debug(f"Using container runtime: {self.runtime}")

        self.skopeo_available = self._check_skopeo_available()
        self._skopeo_hint_shown = False  # Track if we've shown the install hint
        if not self.skopeo_available:
            logger.debug("skopeo not found, will not be able to find latest tags")

        # Support mode: when True, skip org registry and use chainguard-private directly
        # This can be set at init (if detected via chainctl auth status) or dynamically
        # after the first successful chainguard-private fallback
        self._support_mode_detected = support_mode_org is not None
        self._support_mode_org: Optional[str] = support_mode_org
        if self._support_mode_detected:
            logger.info(
                f"Support mode enabled: will use chainguard-private directly for '{support_mode_org}' images"
            )

        # Initialize pull fallback strategies
        self._pull_strategies = self._init_pull_strategies()

    def _init_pull_strategies(self) -> list[PullStrategy]:
        """Initialize the pull fallback strategies."""
        return [
            ChainguardPrivateFallbackStrategy(
                self._get_chainguard_private_fallback,
                self._extract_org_from_cgr_image
            ),
            UpstreamFallbackStrategy(),
            MirrorGCRFallbackStrategy(self._try_mirror_gcr_fallback),
            LatestTagFallbackStrategy(self._get_latest_fallback_image),
            SkopeoMostRecentStrategy(self._get_most_recent_tag_with_skopeo),
        ]

    def _check_skopeo_available(self) -> bool:
        """Check if skopeo is available."""
        try:
            result = subprocess.run(
                ["skopeo", "--version"],
                capture_output=True,
                timeout=VERSION_CHECK_TIMEOUT,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def get_image_label(self, image: str, label: str) -> Optional[str]:
        """
        Get an OCI label from an image using skopeo inspect.

        Args:
            image: Image reference (e.g., "cgr.dev/chainguard-private/nginx:1.27.0")
            label: Label name (e.g., "org.opencontainers.image.created")

        Returns:
            Label value or None if not found or unavailable
        """
        if not self.skopeo_available:
            logger.debug("skopeo not available, cannot get image label")
            return None

        try:
            cmd = ["skopeo", "inspect", f"docker://{image}"]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=API_REQUEST_TIMEOUT,
            )

            if result.returncode != 0:
                logger.debug(f"skopeo inspect failed for {image}: {result.stderr}")
                return None

            data = json.loads(result.stdout)
            labels = data.get("Labels", {}) or {}
            return labels.get(label)

        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
            logger.debug(f"Failed to get label for {image}: {e}")
            return None

    def _detect_runtime(self) -> Optional[str]:
        """Detect available container runtime."""
        for cmd in ["docker", "podman"]:
            try:
                result = subprocess.run(
                    [cmd, "--version"],
                    capture_output=True,
                    timeout=VERSION_CHECK_TIMEOUT,
                )
                if result.returncode == 0:
                    return cmd
            except (subprocess.TimeoutExpired, FileNotFoundError):
                continue
        return None

    def get_image_digest(self, image: str) -> Optional[str]:
        """
        Get the digest (sha256) of an image.

        Args:
            image: Image reference (registry/repo:tag)

        Returns:
            Image digest or None if unavailable
        """
        try:
            # Try to get local image digest first
            result = subprocess.run(
                [self.runtime, "inspect", "--format={{.Id}}", image],
                capture_output=True,
                text=True,
                timeout=API_REQUEST_TIMEOUT,
            )

            if result.returncode == 0:
                digest = result.stdout.strip()
                if digest.startswith("sha256:"):
                    return digest
                return f"sha256:{digest}"

        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.debug(f"Failed to get digest for {image}: {e}")

        return None

    def get_remote_digest(self, image: str, platform: str) -> Optional[str]:
        """
        Get the digest of an image from the remote registry for a specific platform.

        Args:
            image: Image reference (registry/repo:tag)
            platform: Platform string (e.g., "linux/amd64")

        Returns:
            Remote image digest for the specified platform or None if unavailable
        """
        try:
            result = subprocess.run(
                [self.runtime, "manifest", "inspect", image],
                capture_output=True,
                text=True,
                timeout=API_REQUEST_TIMEOUT,
            )

            if result.returncode != 0:
                return None

            manifest = json.loads(result.stdout)

            # Handle multi-arch manifests
            if "manifests" in manifest and isinstance(manifest["manifests"], list):
                # Parse target platform
                target_os, target_arch = platform.split("/") if "/" in platform else (platform, None)

                # Find platform-specific manifest
                for m in manifest["manifests"]:
                    p = m.get("platform", {})
                    if p.get("os") == target_os and p.get("architecture") == target_arch:
                        return m.get("digest")

                # Fallback to first manifest if specific platform not found
                if manifest["manifests"]:
                    logger.debug(
                        f"Could not find {platform} manifest for {image}, using first available"
                    )
                    return manifest["manifests"][0].get("digest")

            # Single-arch manifest
            if "config" in manifest and "digest" in manifest["config"]:
                return manifest["config"]["digest"]

            return manifest.get("digest")

        except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            logger.debug(f"Failed to get remote digest for {image}: {e}")
            return None

    def ensure_fresh_image(
        self,
        image: str,
        platform: Optional[str] = None,
        upstream_image: Optional[str] = None,
        allow_chainguard_private_fallback: bool = False,
    ) -> tuple[str, bool, bool, str]:
        """
        Ensure local image is up-to-date with remote, with intelligent fallback strategies.

        Args:
            image: Image reference to check/pull
            platform: Platform specification (default: "linux/amd64")
            upstream_image: Optional upstream image to try as fallback (e.g., docker.io equivalent)
            allow_chainguard_private_fallback: Whether to try cgr.dev/chainguard-private as
                fallback for org-specific Chainguard images.

        Returns:
            Tuple of (image_used, used_fallback, pull_successful, error_type) where:
                - image_used: The actual image reference that was used
                - used_fallback: True if any fallback was used, False otherwise
                - pull_successful: True if image was successfully pulled, False otherwise
                - error_type: Type of error if pull failed ("none" if successful)

        Raises:
            ValidationException: If image reference is invalid
        """
        # Validate image references before any operations
        image = validate_image_reference(image, "image")
        if upstream_image:
            upstream_image = validate_image_reference(upstream_image, "upstream_image")

        try:
            # Default to linux/amd64 for consistency across environments
            platform = platform or DEFAULT_PLATFORM

            remote_digest = self.get_remote_digest(image, platform)
            if not remote_digest:
                logger.debug(
                    f"Could not get remote digest for {image}, attempting pull with fallback"
                )
                # Image might not exist, try pulling with fallback
                return self.pull_image_with_fallback(
                    image, platform, upstream_image=upstream_image,
                    allow_chainguard_private_fallback=allow_chainguard_private_fallback,
                )

            local_digest = self.get_image_digest(image)

            if not local_digest or local_digest != remote_digest:
                logger.info(f"Pulling fresh copy of {image} ({platform})")
                return self.pull_image_with_fallback(
                    image, platform, upstream_image=upstream_image,
                    allow_chainguard_private_fallback=allow_chainguard_private_fallback,
                )

            logger.debug(f"Image {image} is up-to-date")
            return image, False, True, "none"

        except subprocess.TimeoutExpired:
            logger.warning(f"Timeout pulling {image}")
            return image, False, False, "timeout"

    def get_image_size_mb(self, image: str) -> float:
        """
        Get image size in megabytes.

        Uses 'docker images' command instead of 'inspect' because the .Size field
        in inspect returns only the top layer size, not the full image size.

        Args:
            image: Image reference

        Returns:
            Size in MB, rounded to nearest integer
        """

        def parse_size(size_str: str) -> float:
            """Parse human-readable size string to MB."""
            if not size_str:
                return 0.0

            # Parse human-readable size (e.g., "1.25GB", "234MB", "45.3kB")
            size_str = size_str.upper()

            # Extract numeric value
            numeric_part = ""
            unit = ""
            for char in size_str:
                if char.isdigit() or char == ".":
                    numeric_part += char
                elif char.isalpha():
                    unit += char

            if not numeric_part:
                return 0.0

            value = float(numeric_part)

            # Convert to MB
            if "GB" in unit:
                return round(value * 1024)
            elif "MB" in unit:
                return round(value)
            elif "KB" in unit or "K" in unit:
                return round(value / 1024)
            elif "TB" in unit:
                return round(value * 1024 * 1024)
            elif (
                "B" in unit
                and "KB" not in unit
                and "MB" not in unit
                and "GB" not in unit
            ):
                # Just bytes
                return round(value / (1024 * 1024))
            else:
                # Unknown unit, assume MB
                return round(value)

        # Try multiple image name variations
        # Docker stores images with short names (e.g., "alpine") but we might query with full names
        image_variations = [image]

        # Add short name variation for docker.io/library/* images
        if image.startswith("docker.io/library/"):
            short_name = image.replace("docker.io/library/", "")
            image_variations.append(short_name)
        elif image.startswith("docker.io/"):
            # For other docker.io images, try without the registry prefix
            short_name = image.replace("docker.io/", "")
            image_variations.append(short_name)

        for img_name in image_variations:
            try:
                # Use docker images command which reports actual image size
                # Format: {{.Size}} returns human-readable format like "1.25GB" or "234MB"
                result = subprocess.run(
                    [self.runtime, "images", img_name, "--format", "{{.Size}}"],
                    capture_output=True,
                    text=True,
                    timeout=API_REQUEST_TIMEOUT,
                )

                if result.returncode == 0:
                    size_str = result.stdout.strip()
                    if size_str:
                        # Take first line in case multiple images match
                        first_line = size_str.split("\n")[0].strip()
                        if first_line:
                            size_mb = parse_size(first_line)
                            if size_mb > 0:
                                logger.debug(f"Got size for {img_name}: {size_mb} MB")
                                return size_mb

            except (subprocess.TimeoutExpired, ValueError) as e:
                logger.debug(f"Failed to get size for {img_name}: {e}")
                continue

        # If all variations failed
        logger.debug(f"Could not get size for {image} (tried: {image_variations})")
        return 0.0

    def get_image_created_date(self, image: str) -> Optional[str]:
        """
        Get image creation timestamp.

        Args:
            image: Image reference

        Returns:
            ISO 8601 timestamp string (e.g., "2024-10-27T12:31:00.000Z") or None if unavailable
        """
        try:
            result = subprocess.run(
                [self.runtime, "inspect", "--format={{.Created}}", image],
                capture_output=True,
                text=True,
                timeout=API_REQUEST_TIMEOUT,
            )

            if result.returncode == 0:
                created = result.stdout.strip()
                return created if created else None

        except (subprocess.TimeoutExpired, ValueError) as e:
            logger.debug(f"Failed to get creation date for {image}: {e}")

        return None

    def pull_image(self, image: str, platform: Optional[str] = None) -> bool:
        """
        Pull an image from registry.

        Args:
            image: Image reference to pull
            platform: Platform specification (default: "linux/amd64")

        Returns:
            True if pull succeeded, False otherwise
        """
        try:
            # Default to linux/amd64 for consistency across environments
            platform = platform or DEFAULT_PLATFORM

            cmd = [self.runtime, "pull", "--platform", platform, image]

            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=DOCKER_PULL_TIMEOUT
            )

            return result.returncode == 0

        except subprocess.TimeoutExpired:
            logger.warning(f"Timeout pulling {image}")
            return False

    def image_exists_in_registry(self, image: str) -> bool:
        """
        Check if an image exists in the remote registry.

        Args:
            image: Image reference to check

        Returns:
            True if image exists in registry, False otherwise
        """
        try:
            result = subprocess.run(
                [self.runtime, "manifest", "inspect", image],
                capture_output=True,
                timeout=API_REQUEST_TIMEOUT,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def _has_registry_prefix(self, image: str) -> bool:
        """
        Check if an image already has a registry prefix.

        Args:
            image: Image reference to check

        Returns:
            True if image has a registry prefix, False otherwise
        """
        # If there's no slash, it's a simple image name (e.g., "ubuntu")
        if "/" not in image:
            return False

        # Split on first slash to get potential registry part
        first_part = image.split("/")[0]

        # If first part contains a dot or colon, it's likely a registry
        # (e.g., "gcr.io", "registry.example.com:5000")
        return "." in first_part or ":" in first_part

    def _try_mirror_gcr_fallback(self, image: str) -> Optional[str]:
        """
        Try to construct a mirror.gcr.io fallback URL for Docker Hub images.

        Args:
            image: Original image reference

        Returns:
            mirror.gcr.io URL if applicable, None otherwise
        """
        # Only apply to Docker Hub images (no existing registry prefix)
        if self._has_registry_prefix(image):
            logger.debug(
                f"Image {image} already has registry prefix, skipping mirror.gcr.io fallback"
            )
            return None

        # Skip digest-based images
        if "@sha256:" in image:
            logger.debug(
                f"Image {image} is digest-based, skipping mirror.gcr.io fallback"
            )
            return None

        # Transform official images: ubuntu:20.04 -> mirror.gcr.io/library/ubuntu:20.04
        # Transform user/org images: user/repo:tag -> mirror.gcr.io/user/repo:tag
        if "/" not in image:
            # Official image (e.g., ubuntu, node, python)
            mirror_image = f"mirror.gcr.io/library/{image}"
        else:
            # User/org image (e.g., user/repo:tag)
            mirror_image = f"mirror.gcr.io/{image}"

        logger.debug(f"Mirror.gcr.io fallback for {image}: {mirror_image}")
        return mirror_image

    def _attempt_pull(self, image: str, platform: str) -> tuple[bool, str]:
        """
        Attempt to pull a single image.

        Args:
            image: Image reference to pull
            platform: Platform specification

        Returns:
            Tuple of (success, stderr)
        """
        try:
            result = subprocess.run(
                [self.runtime, "pull", "--platform", platform, image],
                capture_output=True,
                text=True,
                timeout=DOCKER_PULL_TIMEOUT,
            )

            # Check if image already exists with this digest
            # Docker returns non-zero exit code with "cannot overwrite digest" when
            # trying to pull an image that's already present locally
            if (
                result.returncode != 0
                and "cannot overwrite digest" in result.stderr.lower()
            ):
                logger.debug(f"Image {image} already present locally (digest exists)")
                return True, ""  # Treat as success

            return result.returncode == 0, result.stderr
        except subprocess.TimeoutExpired:
            return False, "timeout"

    def _extract_registry_from_image(self, image: str) -> str:
        """
        Extract registry hostname from image reference.

        Args:
            image: Full image reference (e.g., registry.example.com/repo/image:tag)

        Returns:
            Registry hostname or "docker.io" for Docker Hub images
        """
        return extract_registry_from_image(image)

    def _is_auth_error(self, stderr: str) -> bool:
        """
        Check if error is due to authentication/authorization failure.

        These are permanent failures that should not be retried with fallback strategies.

        Args:
            stderr: Error output from docker command

        Returns:
            True if error is authentication-related
        """
        return _is_auth_error(stderr)

    def classify_error_type(self, stderr: str) -> str:
        """
        Classify the type of error from stderr output.

        Args:
            stderr: Error output from docker command

        Returns:
            Error type: "auth", "timeout", "rate_limit", "not_found", or "unknown"
        """
        return _classify_error_type(stderr)

    def _is_recoverable_error(self, stderr: str) -> bool:
        """Check if error is recoverable with fallback strategies."""
        return _is_recoverable_error(stderr)

    def _get_latest_fallback_image(self, image: str) -> str | None:
        """
        Get :latest fallback image if applicable.

        Returns:
            Latest image reference or None if not applicable
        """
        if image.endswith(":latest") or "@sha256:" in image or ":" not in image:
            return None

        base_image = image.rsplit(":", 1)[0]
        return f"{base_image}:latest"

    def _get_chainguard_private_fallback(self, image: str) -> str | None:
        """
        Get chainguard-private fallback for org-specific Chainguard images.

        Converts cgr.dev/<org>/<image>:<tag> to cgr.dev/chainguard-private/<image>:<tag>

        This is useful for support users who can list entitled images in an org
        but don't have pull access. They can fall back to chainguard-private
        if they have access there.

        Args:
            image: Image reference like cgr.dev/cbp.gov/node:latest

        Returns:
            Fallback image reference like cgr.dev/chainguard-private/node:latest,
            or None if not applicable
        """
        ref = ImageReference.parse(image)
        return ref.to_chainguard_private()

    def _extract_org_from_cgr_image(self, image: str) -> str | None:
        """
        Extract the organization from a cgr.dev image reference.

        Args:
            image: Image reference like cgr.dev/cbp.gov/node:latest

        Returns:
            Organization name (e.g., "cbp.gov") or None if not a cgr.dev org image
        """
        return extract_org_from_cgr_image(image)

    def _sort_versions(self, versions: list[str]) -> list[str]:
        """Sort versions numerically, handling 'v' prefix."""
        def version_key(v):
            return [int(x.lstrip('v')) for x in v.split('.')]
        return sorted(versions, key=version_key, reverse=True)

    def _get_most_recent_tag_with_skopeo(self, image: str) -> Optional[str]:
        """
        Use skopeo to find the most recent tag for an image.
        """
        if not self.skopeo_available:
            return None

        base_image = image.rsplit(":", 1)[0]
        logger.debug(f"Using skopeo to find tags for {base_image}")

        try:
            cmd = ["skopeo", "list-tags", f"docker://{base_image}"]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=API_REQUEST_TIMEOUT,
            )
            if result.returncode != 0:
                logger.debug(f"skopeo list-tags failed for {base_image}: {result.stderr}")
                return None

            data = json.loads(result.stdout)
            tags = data.get("Tags", [])

            if "latest" in tags:
                return "latest"
            if "main" in tags:
                return "main"
            if "master" in tags:
                return "master"

            # Filter for version-like tags, optionally with a 'v' prefix
            version_tags = [t for t in tags if re.match(r"^v?\d+(\.\d+)*$", t)]
            if not version_tags:
                return None

            # Sort versions to find the latest
            sorted_tags = self._sort_versions(version_tags)
            return sorted_tags[0]

        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
            logger.debug(f"skopeo failed for {base_image}: {e}")
            return None

    def pull_image_with_fallback(
        self,
        image: str,
        platform: Optional[str] = None,
        upstream_image: Optional[str] = None,
        allow_chainguard_private_fallback: bool = False,
    ) -> tuple[str, bool, bool, str]:
        """
        Pull an image from registry with intelligent fallback strategies.

        Uses a strategy pattern to try multiple fallback approaches in order:
        1. Try exact image as specified
        2. If upstream image provided (from upstream discovery), try that
        3. If Docker Hub image and failed, try mirror.gcr.io fallback
        4. If that fails, try with :latest tag as last resort
        5. If that fails, try to find the most recent tag with skopeo

        Additionally, for auth errors on cgr.dev/<org> images when
        allow_chainguard_private_fallback=True, tries cgr.dev/chainguard-private
        as a fallback before other strategies.

        Args:
            image: Image reference to pull
            platform: Platform specification (default: "linux/amd64")
            upstream_image: Optional upstream image to try as fallback (e.g., docker.io equivalent)
            allow_chainguard_private_fallback: Whether to try cgr.dev/chainguard-private as
                fallback for org-specific Chainguard images. Only set to True when scanning
                Chainguard images in --organization mode.

        Returns:
            Tuple of (image_used, used_fallback, pull_successful, error_type)
            error_type is one of: "none", "auth", "timeout", "rate_limit", "not_found", "unknown"
        """
        platform = platform or DEFAULT_PLATFORM
        original_image = image
        last_stderr = ""

        # Support mode optimization: if we've detected support mode for this org,
        # directly transform to chainguard-private instead of failing first
        if allow_chainguard_private_fallback and self._support_mode_detected:
            org = self._extract_org_from_cgr_image(image)
            if org and org == self._support_mode_org:
                private_image = self._get_chainguard_private_fallback(image)
                if private_image:
                    logger.debug(
                        f"Support mode active: using chainguard-private directly for {image}"
                    )
                    success, stderr = self._attempt_pull(private_image, platform)
                    if success:
                        return private_image, True, True, "none"
                    last_stderr = stderr

        # Strategy 1: Try to pull the exact image
        logger.debug(f"Attempting to pull {image}")
        success, stderr = self._attempt_pull(image, platform)
        last_stderr = stderr

        if success:
            logger.debug(f"Successfully pulled {image}")
            return image, False, True, "none"

        # Build context for strategy evaluation
        is_auth_error = self._is_auth_error(stderr)
        is_recoverable = self._is_recoverable_error(stderr)

        ctx = PullContext(
            original_image=original_image,
            last_error=stderr,
            is_auth_error=is_auth_error,
            is_recoverable=is_recoverable,
            upstream_image=upstream_image,
            allow_chainguard_private_fallback=allow_chainguard_private_fallback,
            support_mode_detected=self._support_mode_detected,
            support_mode_org=self._support_mode_org,
        )

        # For auth errors, try chainguard-private fallback first before failing
        if is_auth_error and allow_chainguard_private_fallback:
            private_fallback = self._get_chainguard_private_fallback(image)
            if private_fallback:
                logger.warning(
                    f"Authentication failed for {image}, trying chainguard-private fallback"
                )
                success, stderr = self._attempt_pull(private_fallback, platform)
                last_stderr = stderr

                if success:
                    # Enable support mode for subsequent images from this org
                    org = self._extract_org_from_cgr_image(image)
                    if org and not self._support_mode_detected:
                        self._support_mode_detected = True
                        self._support_mode_org = org
                        logger.info(
                            f"Support mode detected: will use chainguard-private directly for '{org}' images"
                        )
                    logger.info(
                        f"✓ chainguard-private fallback successful: {original_image} → {private_fallback}"
                    )
                    return private_fallback, True, True, "none"

                logger.debug(f"chainguard-private fallback failed: {stderr}")

        # For auth errors with no applicable fallbacks, fail early
        if not is_recoverable and not (is_auth_error and upstream_image):
            if is_auth_error:
                registry = self._extract_registry_from_image(image)
                logger.error(
                    f"Authentication required for {image}\n"
                    f"  Registry: {registry}\n"
                    f"  Error: {stderr.strip()}\n"
                    f"  → Run: docker login {registry}"
                )
            else:
                logger.error(f"Failed to pull {image}: {stderr}")
            return image, False, False, self.classify_error_type(stderr)

        # Log the situation
        if is_auth_error and upstream_image:
            logger.warning(f"Authentication failed for {image}, trying fallback strategies")
        else:
            logger.warning(f"Image {image} not found or rate limited, trying fallback strategies")

        # Try each applicable strategy (skip chainguard-private as it was tried above)
        for strategy in self._pull_strategies:
            if isinstance(strategy, ChainguardPrivateFallbackStrategy):
                continue  # Already tried above
            if not strategy.can_apply(ctx):
                continue

            fallback_image = strategy.get_fallback_image(ctx)
            if not fallback_image:
                continue

            logger.warning(f"Trying {strategy.name} fallback: {fallback_image}")
            success, stderr = self._attempt_pull(fallback_image, platform)
            last_stderr = stderr

            if success:
                logger.info(f"✓ {strategy.name} fallback successful: {original_image} → {fallback_image}")

                # Handle any state updates from the strategy
                state_updates = strategy.on_success(ctx, fallback_image)
                if state_updates:
                    if state_updates.get("support_mode_detected"):
                        self._support_mode_detected = True
                        self._support_mode_org = state_updates.get("support_mode_org")

                return fallback_image, True, True, "none"

            logger.debug(f"{strategy.name} fallback failed: {stderr}")

        # All strategies failed
        logger.warning(f"All fallback strategies failed for {original_image} (will retry)")
        if not self.skopeo_available and not self._skopeo_hint_shown:
            logger.info(
                "Tip: Install skopeo to enable tag discovery fallback for images with non-standard tags. "
                "See: https://github.com/containers/skopeo/blob/main/install.md"
            )
            self._skopeo_hint_shown = True
        return original_image, False, False, self.classify_error_type(last_stderr)

    def ensure_chainguard_auth(self) -> bool:
        """
        Ensure authentication to cgr.dev is configured.

        Checks if chainctl is installed and authenticated. If not authenticated,
        attempts to login interactively.

        Returns:
            True if authentication is configured, False otherwise
        """
        try:
            # Check if chainctl is available
            result = subprocess.run(
                ["chainctl", "version"],
                capture_output=True,
                timeout=VERSION_CHECK_TIMEOUT,
            )

            if result.returncode != 0:
                logger.warning(
                    "chainctl not found or not working. "
                    "Install chainctl for Chainguard registry access: "
                    "https://edu.chainguard.dev/chainguard/administration/how-to-install-chainctl/"
                )
                return False

            # chainctl available - check if authenticated
            token_result = subprocess.run(
                ["chainctl", "auth", "token"],
                capture_output=True,
                timeout=GITHUB_CLI_TIMEOUT,
            )

            if token_result.returncode == 0:
                logger.info("✓ Chainguard authentication configured")
                return True

            # Not authenticated, try to login
            logger.info("Authenticating to Chainguard...")
            login_result = subprocess.run(
                ["chainctl", "auth", "login"],
                capture_output=True,
                timeout=CLI_SUBPROCESS_TIMEOUT,
            )

            if login_result.returncode == 0:
                logger.info("✓ Authenticated to Chainguard")
                return True

            logger.warning("chainctl auth login failed")
            return False

        except subprocess.TimeoutExpired:
            logger.warning("Timeout checking chainctl authentication")
            return False
        except FileNotFoundError:
            logger.warning(
                "chainctl not found. "
                "Install chainctl for Chainguard registry access: "
                "https://edu.chainguard.dev/chainguard/administration/how-to-install-chainctl/"
            )
            return False
        except Exception as e:
            logger.debug(f"Error checking Chainguard authentication: {e}")
            return False


# Module-level helper functions for convenience
_client = None


def image_exists_in_registry(image: str) -> bool:
    """
    Check if an image exists in the registry.

    Module-level convenience function that creates a shared DockerClient instance.

    Args:
        image: Image reference to check

    Returns:
        True if image exists in registry, False otherwise
    """
    global _client
    if _client is None:
        _client = DockerClient()
    return _client.image_exists_in_registry(image)
