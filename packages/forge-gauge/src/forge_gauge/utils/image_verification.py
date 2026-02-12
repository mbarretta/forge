"""
Centralized image verification service.

Provides unified verification for Chainguard images with configurable strategies:
- GitHub metadata API (fast, but requires token)
- Docker registry manifest inspection (slower, but always works)
"""

import logging
from collections import OrderedDict
from typing import Optional

from forge_gauge.integrations.github_metadata import GitHubMetadataClient
from forge_gauge.utils.image_utils import ImageReference

logger = logging.getLogger(__name__)

# Default maximum cache size for verification results
DEFAULT_VERIFICATION_CACHE_SIZE = 1000


class ImageVerificationService:
    """
    Centralized service for verifying Chainguard image existence.

    Uses a two-tier verification strategy:
    1. GitHub metadata API (fast, preferred)
    2. Docker manifest inspect (fallback)

    Results are cached in-memory to avoid redundant verification calls.
    """

    def __init__(
        self,
        github_token: Optional[str] = None,
        cache_maxsize: int = DEFAULT_VERIFICATION_CACHE_SIZE,
    ):
        """
        Initialize image verification service.

        Args:
            github_token: Optional GitHub token for metadata API access
            cache_maxsize: Maximum number of entries in the verification cache (default: 1000)
        """
        self.github_metadata = GitHubMetadataClient(github_token=github_token)
        # In-memory LRU cache for verification results (per instance)
        self._verification_cache: OrderedDict[str, bool] = OrderedDict()
        self._cache_maxsize = cache_maxsize

    def _cache_put(self, key: str, value: bool) -> None:
        """
        Add entry to cache with LRU eviction.

        Args:
            key: Cache key (image reference)
            value: Verification result
        """
        # If key exists, move to end (most recently used)
        if key in self._verification_cache:
            self._verification_cache.move_to_end(key)
            self._verification_cache[key] = value
            return

        # Evict oldest entry if at capacity
        if len(self._verification_cache) >= self._cache_maxsize:
            oldest_key = next(iter(self._verification_cache))
            del self._verification_cache[oldest_key]
            logger.debug(f"Cache evicted oldest entry: {oldest_key}")

        self._verification_cache[key] = value

    def _cache_get(self, key: str) -> Optional[bool]:
        """
        Get entry from cache with LRU update.

        Args:
            key: Cache key (image reference)

        Returns:
            Cached value or None if not found
        """
        if key in self._verification_cache:
            # Move to end (most recently used)
            self._verification_cache.move_to_end(key)
            return self._verification_cache[key]
        return None

    def verify_image_exists(
        self,
        image: str,
        prefer_github_api: bool = True
    ) -> bool:
        """
        Verify if a Chainguard image exists.

        Args:
            image: Full image reference (e.g., cgr.dev/chainguard/python:latest)
            prefer_github_api: If True, try GitHub API before Docker fallback

        Returns:
            True if image exists, False otherwise
        """
        # Check in-memory cache first
        cached_result = self._cache_get(image)
        if cached_result is not None:
            logger.debug(f"Cache hit for image verification: {image}")
            return cached_result

        # Only verify Chainguard images
        if not self._is_chainguard_image(image):
            logger.debug(f"Image {image} is not a Chainguard image")
            self._cache_put(image, False)
            return False

        image_name = self._extract_image_name(image)
        if not image_name:
            logger.debug(f"Could not extract image name from {image}")
            self._cache_put(image, False)
            return False

        # Try GitHub API first (if preferred)
        if prefer_github_api:
            if self._verify_via_github_api(image_name):
                self._cache_put(image, True)
                return True

        # Fallback to Docker manifest inspection
        result = self._verify_via_docker(image)
        self._cache_put(image, result)
        return result

    def _is_chainguard_image(self, image: str) -> bool:
        """Check if image is from Chainguard registry."""
        ref = ImageReference.parse(image)
        return ref.is_chainguard()

    def _extract_image_name(self, image: str) -> Optional[str]:
        """
        Extract image name from full reference.

        Example:
            cgr.dev/chainguard/python:latest → python
            cgr.dev/chainguard-private/nginx:1.21 → nginx

        Returns:
            Image name without registry, tag, or digest
        """
        ref = ImageReference.parse(image)
        return ref.name if ref.name else None

    def _verify_via_github_api(self, image_name: str) -> bool:
        """
        Verify image via GitHub metadata API.

        Args:
            image_name: Name of the image (without registry/tag)

        Returns:
            True if verified, False if verification failed
        """
        try:
            tier = self.github_metadata.get_image_tier(image_name)
            if tier is not None:
                logger.debug(f"GitHub API confirmed image exists: {image_name} (tier: {tier})")
                return True
        except Exception as e:
            logger.debug(f"GitHub metadata not found for {image_name}: {e}")

        return False

    def _verify_via_docker(self, image: str) -> bool:
        """
        Verify image via Docker manifest inspection.

        Args:
            image: Full image reference

        Returns:
            True if verified, False if verification failed
        """
        logger.debug(f"Falling back to Docker verification for {image}")

        # Import here to avoid circular dependency
        from forge_gauge.utils.docker_utils import image_exists_in_registry

        try:
            exists = image_exists_in_registry(image)
            if exists:
                logger.debug(f"Docker manifest confirmed image exists: {image}")
            return exists
        except Exception as e:
            logger.debug(f"Docker verification failed for {image}: {e}")
            return False
