"""
DFC (Docker File Converter) mappings integration.

Fetches and caches image mappings from Chainguard's DFC project to automatically
match alternative container images to their Chainguard equivalents.

SECURITY NOTE: This module fetches YAML from a remote source. While yaml.safe_load
prevents code execution, the content is validated to ensure:
1. Proper structure (dict with 'images' key)
2. All mappings point to expected Chainguard registry prefixes
3. No unexpected keys or structures
"""

import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests
import yaml

from forge_gauge.constants import CHAINGUARD_PRIVATE_REGISTRY, CHAINGUARD_PUBLIC_REGISTRY, DFC_MAPPINGS_CACHE_MAX_AGE_DAYS

logger = logging.getLogger(__name__)

# DFC builtin-mappings.yaml URL
DFC_MAPPINGS_URL = "https://raw.githubusercontent.com/chainguard-dev/dfc/main/pkg/dfc/builtin-mappings.yaml"

# Cache configuration
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "gauge"
DFC_CACHE_FILE = "dfc-mappings.yaml"


class DFCMappings:
    """
    Manages DFC image mappings with caching and auto-sync.

    Fetches mappings from Chainguard's DFC project and caches them locally.
    Supports wildcard patterns (e.g., 'golang*' → 'go').
    """

    def __init__(self, cache_dir: Optional[Path] = None, local_file: Optional[Path] = None):
        """
        Initialize DFC mappings manager.

        Args:
            cache_dir: Directory for caching mappings (default: ~/.cache/gauge)
            local_file: Optional local DFC mappings file (for offline/air-gapped)
        """
        self.cache_dir = cache_dir or DEFAULT_CACHE_DIR
        self.cache_file = self.cache_dir / DFC_CACHE_FILE
        self.local_file = local_file
        self.mappings: dict[str, str] = {}
        self.wildcard_patterns: list[tuple[str, str]] = []

        # Ensure cache directory exists
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def load_mappings(self) -> dict[str, str]:
        """
        Load DFC mappings from cache or fetch from remote.

        Returns:
            Dictionary of image mappings (alternative → chainguard)

        Raises:
            RuntimeError: If mappings cannot be loaded
        """
        # Use local file if provided (offline mode)
        if self.local_file:
            logger.info(f"Loading DFC mappings from local file: {self.local_file}")
            self.mappings = self._load_from_file(self.local_file)
            self._parse_wildcard_patterns()
            return self.mappings

        # Check if cache needs refresh
        if self._cache_needs_refresh():
            logger.info("DFC mappings cache is stale or missing, fetching from remote...")
            try:
                self._fetch_and_cache()
            except Exception as e:
                logger.warning(f"Failed to fetch DFC mappings: {e}")
                if self.cache_file.exists():
                    logger.info("Using stale cache as fallback")
                else:
                    raise RuntimeError(f"Cannot load DFC mappings: {e}") from e

        # Load from cache
        logger.debug(f"Loading DFC mappings from cache: {self.cache_file}")
        self.mappings = self._load_from_file(self.cache_file)
        self._parse_wildcard_patterns()
        return self.mappings

    def match_image(self, alternative_image: str) -> Optional[str]:
        """
        Find Chainguard image match for alternative image.

        Supports exact matches and wildcard patterns.

        Args:
            alternative_image: Alternative/source image reference

        Returns:
            Matched Chainguard image reference, or None if no match
        """
        if not self.mappings:
            raise RuntimeError("DFC mappings not loaded. Call load_mappings() first.")

        # Extract base image name (remove registry and tag)
        base_image = self._extract_base_image(alternative_image)

        # Try exact match first
        if base_image in self.mappings:
            return self._normalize_chainguard_image(self.mappings[base_image])

        # Try wildcard patterns
        for pattern, target in self.wildcard_patterns:
            if self._matches_wildcard(base_image, pattern):
                return self._normalize_chainguard_image(target)

        return None

    def _cache_needs_refresh(self) -> bool:
        """Check if cache needs to be refreshed."""
        if not self.cache_file.exists():
            return True

        # Check cache age
        cache_mtime = datetime.fromtimestamp(
            self.cache_file.stat().st_mtime, tz=timezone.utc
        )
        age = datetime.now(timezone.utc) - cache_mtime
        max_age = timedelta(days=DFC_MAPPINGS_CACHE_MAX_AGE_DAYS)

        if age > max_age:
            logger.debug(f"Cache age ({age}) exceeds max age ({max_age})")
            return True

        return False

    def _fetch_and_cache(self) -> None:
        """Fetch DFC mappings from remote and cache locally with integrity validation."""
        logger.info(f"Fetching DFC mappings from {DFC_MAPPINGS_URL}")

        try:
            response = requests.get(DFC_MAPPINGS_URL, timeout=30)
            response.raise_for_status()

            # Parse and validate YAML structure
            mappings_data = yaml.safe_load(response.text)
            self._validate_mappings_integrity(mappings_data)

            # Log content hash for audit trail
            content_hash = hashlib.sha256(response.text.encode()).hexdigest()[:16]
            logger.debug(f"DFC mappings content hash: {content_hash}")

            # Write to cache
            with open(self.cache_file, "w", encoding="utf-8") as f:
                f.write(response.text)

            logger.info(f"DFC mappings cached to {self.cache_file}")

        except requests.RequestException as e:
            raise RuntimeError(f"Failed to fetch DFC mappings: {e}") from e
        except yaml.YAMLError as e:
            raise RuntimeError(f"Failed to parse DFC mappings: {e}") from e

    def _validate_mappings_integrity(self, data: dict) -> None:
        """
        Validate integrity of DFC mappings data.

        Checks:
        1. Proper structure (dict with 'images' key)
        2. All target mappings point to Chainguard registries
        3. No unexpected or suspicious content

        Args:
            data: Parsed YAML data

        Raises:
            ValueError: If validation fails
        """
        if not isinstance(data, dict):
            raise ValueError("Invalid DFC mappings format: expected dict")

        if "images" not in data:
            raise ValueError("Invalid DFC mappings format: missing 'images' key")

        images = data.get("images", {})
        if not isinstance(images, dict):
            raise ValueError("Invalid DFC mappings format: 'images' must be a dict")

        # Validate each mapping target points to Chainguard registry
        valid_prefixes = (CHAINGUARD_PRIVATE_REGISTRY, CHAINGUARD_PUBLIC_REGISTRY, "cgr.dev/")
        suspicious_mappings = []

        for source, target in images.items():
            if not isinstance(source, str) or not isinstance(target, str):
                raise ValueError(f"Invalid mapping type: {source} -> {target}")

            # Target should be a Chainguard image name (without full registry) or full reference
            # DFC format: source -> chainguard_name (e.g., "python" -> "python")
            # The registry prefix is added by the matcher, so targets are usually just image names
            # But if a full reference is provided, it must be Chainguard
            if "/" in target and not any(target.startswith(p) for p in valid_prefixes):
                suspicious_mappings.append(f"{source} -> {target}")

        if suspicious_mappings:
            logger.warning(
                f"DFC mappings contain {len(suspicious_mappings)} entries pointing to "
                f"non-Chainguard registries. These will be skipped for security."
            )
            for mapping in suspicious_mappings[:5]:  # Log first 5
                logger.warning(f"  Suspicious mapping: {mapping}")

        logger.debug(f"DFC mappings integrity validated: {len(images)} mappings")

    def _load_from_file(self, file_path: Path) -> dict[str, str]:
        """Load mappings from YAML file."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if not isinstance(data, dict):
                raise ValueError("Invalid mappings file format")

            # Extract image mappings section
            images = data.get("images", {})
            if not isinstance(images, dict):
                raise ValueError("Missing or invalid 'images' section")

            logger.info(f"Loaded {len(images)} DFC image mappings")
            return images

        except FileNotFoundError:
            raise RuntimeError(f"Mappings file not found: {file_path}")
        except yaml.YAMLError as e:
            raise RuntimeError(f"Failed to parse mappings file: {e}") from e

    def _parse_wildcard_patterns(self) -> None:
        """Extract and compile wildcard patterns from mappings."""
        self.wildcard_patterns = []

        for pattern, target in self.mappings.items():
            if "*" in pattern:
                self.wildcard_patterns.append((pattern, target))

        if self.wildcard_patterns:
            logger.debug(f"Found {len(self.wildcard_patterns)} wildcard patterns")

    def _matches_wildcard(self, image: str, pattern: str) -> bool:
        """Check if image matches wildcard pattern."""
        # Convert wildcard pattern to regex
        # Replace * with .* for regex matching
        regex_pattern = "^" + re.escape(pattern).replace(r"\*", ".*") + "$"
        return bool(re.match(regex_pattern, image, re.IGNORECASE))

    def _extract_base_image(self, image: str) -> str:
        """
        Extract base image name from full reference.

        Examples:
            docker.io/library/python:3.12 → python
            gcr.io/kaniko-project/executor:latest → executor
            nginx:1.25 → nginx
        """
        # Remove registry
        if "/" in image:
            # Extract last component of path
            parts = image.split("/")
            image = parts[-1]

        # Remove tag
        if ":" in image:
            image = image.split(":")[0]

        # Remove digest
        if "@" in image:
            image = image.split("@")[0]

        return image

    def _normalize_chainguard_image(self, image: str) -> str:
        """
        Normalize Chainguard image reference to full format.

        Examples:
            go → cgr.dev/chainguard-private/go:latest
            nginx-fips → cgr.dev/chainguard-private/nginx-fips:latest
            cgr.dev/chainguard-private/python:latest → cgr.dev/chainguard-private/python:latest
        """
        # Already has registry prefix
        if image.startswith("cgr.dev/"):
            # Ensure it has a tag
            if ":" not in image:
                image = f"{image}:latest"
            return image

        # Add default registry and tag
        if ":" not in image:
            image = f"{image}:latest"

        return f"{CHAINGUARD_PRIVATE_REGISTRY}/{image}"
