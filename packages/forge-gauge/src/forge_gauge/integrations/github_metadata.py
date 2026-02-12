"""
GitHub metadata integration for Chainguard image tier information.

Fetches image metadata from the chainguard-images/images-private repository
to determine pricing tiers.

SECURITY NOTE: This module fetches YAML from GitHub. While yaml.safe_load
prevents code execution, the content is validated to ensure expected structure
and valid tier values before use.
"""

import logging
import os
import time
from pathlib import Path
from typing import Optional

import requests
import yaml

from forge_gauge.constants import GITHUB_API_TIMEOUT
from forge_gauge.core.models import ImageTier
from forge_gauge.utils.cache_utils import ensure_cache_dir
from forge_gauge.utils.github_utils import get_github_token_from_gh_cli
from forge_gauge.utils.image_utils import extract_base_name
from forge_gauge.utils.llm_utils import db_connection

logger = logging.getLogger(__name__)

# GitHub configuration
GITHUB_API_BASE = "https://api.github.com"
IMAGES_PRIVATE_REPO = "chainguard-images/images-private"
METADATA_PATH_TEMPLATE = "images/{image_name}/metadata.yaml"


class GitHubMetadataClient:
    """Client for fetching Chainguard image metadata from GitHub."""

    # Cache TTL: 24 hours (tiers rarely change)
    CACHE_TTL_SECONDS = 86400

    def __init__(
        self,
        github_token: Optional[str] = None,
        cache_dir: Optional[Path] = None,
    ):
        """
        Initialize GitHub metadata client.

        Args:
            github_token: Optional GitHub token for API access.
                         Falls back to GITHUB_TOKEN env var, then gh CLI.
            cache_dir: Directory for SQLite cache (default: ~/.cache/gauge)
        """
        # Try explicit token, then env var, then gh CLI
        self.token = github_token or os.getenv("GITHUB_TOKEN") or get_github_token_from_gh_cli()

        if not self.token:
            logger.warning(
                "No GitHub token found. GitHub API has strict rate limits for unauthenticated requests. "
                "To authenticate, either:\n"
                "  1. Run 'gh auth login' (recommended)\n"
                "  2. Set GITHUB_TOKEN environment variable\n"
                "  3. Pass token to constructor"
            )

        self.headers = {
            "Accept": "application/vnd.github.v3.raw",
        }
        if self.token:
            self.headers["Authorization"] = f"token {self.token}"

        # Initialize cache
        self.cache_dir = ensure_cache_dir(cache_dir)
        self.cache_db = self.cache_dir / "llm_cache.db"
        self._init_cache_db()

    def _init_cache_db(self) -> None:
        """Initialize SQLite cache database with github_metadata_cache table."""
        with db_connection(self.cache_db) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS github_metadata_cache (
                    image_name TEXT PRIMARY KEY,
                    tier TEXT NOT NULL,
                    timestamp INTEGER NOT NULL
                )
            """
            )
            conn.commit()

    def _get_cached_tier(self, image_name: str) -> Optional[ImageTier]:
        """
        Get cached tier for image.

        Args:
            image_name: Image name to look up

        Returns:
            Cached ImageTier if available and not expired, None otherwise
        """
        with db_connection(self.cache_db) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT tier, timestamp FROM github_metadata_cache
                WHERE image_name = ?
            """,
                (image_name,),
            )
            row = cursor.fetchone()

        if row:
            tier_value, timestamp = row
            age = time.time() - timestamp
            if age < self.CACHE_TTL_SECONDS:
                logger.debug(f"Cache hit for GitHub metadata: {image_name} (age: {age:.0f}s)")
                try:
                    return ImageTier(tier_value)
                except ValueError:
                    pass  # Invalid cached value, will refetch

        return None

    def _cache_tier(self, image_name: str, tier: ImageTier) -> None:
        """
        Cache tier result.

        Args:
            image_name: Image name
            tier: Tier to cache
        """
        with db_connection(self.cache_db) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO github_metadata_cache
                (image_name, tier, timestamp)
                VALUES (?, ?, ?)
            """,
                (image_name, tier.value, int(time.time())),
            )
            conn.commit()

    def get_image_tier(self, image_name: str) -> ImageTier:
        """
        Fetch image tier from GitHub metadata.

        Args:
            image_name: Name of the Chainguard image (e.g., "python", "nginx", "postgres-fips")

        Returns:
            ImageTier enum value

        Raises:
            ValueError: If metadata cannot be fetched or tier cannot be determined
        """
        # Extract base image name from full reference
        # cgr.dev/chainguard-private/python:latest -> python
        image_name = extract_base_name(image_name)

        # Check cache first
        cached_tier = self._get_cached_tier(image_name)
        if cached_tier:
            return cached_tier

        logger.debug(f"Fetching GitHub metadata for image: {image_name}")

        # Construct GitHub API URL
        metadata_path = METADATA_PATH_TEMPLATE.format(image_name=image_name)
        url = f"{GITHUB_API_BASE}/repos/{IMAGES_PRIVATE_REPO}/contents/{metadata_path}"

        try:
            response = requests.get(url, headers=self.headers, timeout=GITHUB_API_TIMEOUT)
            response.raise_for_status()

            # Parse YAML content with structure validation
            metadata = yaml.safe_load(response.text)

            # Validate metadata structure
            if not isinstance(metadata, dict):
                raise ValueError(f"Invalid metadata format for {image_name}: expected dict")

            # Extract tier from metadata
            tier_value = metadata.get("tier")
            if not tier_value:
                raise ValueError(f"No 'tier' field found in metadata for {image_name}")

            # Map tier value to ImageTier enum
            try:
                tier = ImageTier(tier_value.lower())
                logger.info(f"Found tier '{tier.value}' for image {image_name}")
                # Cache the result
                self._cache_tier(image_name, tier)
                return tier
            except ValueError:
                raise ValueError(
                    f"Unknown tier value '{tier_value}' for image {image_name}. "
                    f"Valid tiers: {[t.value for t in ImageTier]}"
                )

        except requests.HTTPError as e:
            if e.response.status_code == 404:
                raise ValueError(
                    f"Metadata not found for image '{image_name}' in {IMAGES_PRIVATE_REPO}. "
                    f"Image may not exist or path may be incorrect."
                )
            elif e.response.status_code == 403:
                error_detail = ""
                try:
                    error_json = e.response.json()
                    if "SAML" in error_json.get("message", ""):
                        error_detail = (
                            "\n\nYour GitHub token requires SAML SSO authorization for the Chainguard organization.\n"
                            "To authorize your token:\n"
                            "  1. Go to: https://github.com/settings/tokens\n"
                            "  2. Click on your token\n"
                            "  3. Click 'Configure SSO'\n"
                            "  4. Click 'Authorize' next to the chainguard-dev organization"
                        )
                except (ValueError, KeyError, TypeError):
                    # JSON parsing failed or unexpected structure - use generic error message
                    logger.debug(f"Could not parse error response for {image_name}")

                raise ValueError(
                    f"GitHub API access forbidden for {IMAGES_PRIVATE_REPO}. "
                    f"Your token may not have access to this private repository.{error_detail}"
                )
            else:
                raise ValueError(f"GitHub API error: {e}")

        except requests.RequestException as e:
            raise ValueError(f"Failed to fetch metadata from GitHub: {e}")

        except yaml.YAMLError as e:
            raise ValueError(f"Failed to parse metadata YAML for {image_name}: {e}")

    def get_image_metadata(self, image_name: str) -> Optional[dict]:
        """
        Fetch full image metadata from GitHub.

        Args:
            image_name: Name of the Chainguard image (e.g., "python", "nginx")

        Returns:
            Full metadata dict including aliases, upstream_url, tier, etc.
            Returns None if metadata cannot be fetched.
        """
        # Extract base image name from full reference
        # cgr.dev/chainguard-private/python:latest -> python
        image_name = extract_base_name(image_name)

        logger.debug(f"Fetching GitHub metadata for image: {image_name}")

        # Construct GitHub API URL
        metadata_path = METADATA_PATH_TEMPLATE.format(image_name=image_name)
        url = f"{GITHUB_API_BASE}/repos/{IMAGES_PRIVATE_REPO}/contents/{metadata_path}"

        try:
            response = requests.get(url, headers=self.headers, timeout=GITHUB_API_TIMEOUT)
            response.raise_for_status()

            # Parse YAML content
            metadata = yaml.safe_load(response.text)
            return metadata

        except requests.HTTPError as e:
            if e.response.status_code == 404:
                logger.debug(f"Metadata not found for image '{image_name}'")
                return None
            elif e.response.status_code == 403:
                logger.warning(
                    f"GitHub API access forbidden for {image_name}. "
                    "Your token may need SSO authorization."
                )
                return None
            else:
                logger.warning(f"GitHub API error for {image_name}: {e}")
                return None

        except requests.RequestException as e:
            logger.warning(f"Failed to fetch metadata for {image_name}: {e}")
            return None

        except yaml.YAMLError as e:
            logger.warning(f"Failed to parse metadata YAML for {image_name}: {e}")
            return None
