"""Load images from a Chainguard organization for scanning."""

import json
import logging
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

from forge_gauge.constants import CATALOG_CACHE_TTL_SECONDS, CLI_SUBPROCESS_TIMEOUT
from forge_gauge.core.models import ImagePair
from forge_gauge.utils.cache_utils import ensure_cache_dir
from forge_gauge.utils.chainctl_auth import (
    get_support_identity_id,
    has_org_access as has_org_pull_access,
    is_support_identity,
    login as chainctl_login,
    login_as_support,
    logout as chainctl_logout,
)

logger = logging.getLogger(__name__)


def restore_normal_identity() -> bool:
    """
    Restore normal identity by logging out and logging back in.

    Returns:
        True if restoration successful, False otherwise
    """
    logger.info("Restoring normal identity...")

    if not chainctl_logout():
        logger.warning("Logout may have failed")

    if chainctl_login():
        logger.info("Successfully restored normal identity")
        return True

    logger.error("Failed to restore normal identity")
    return False


class OrganizationImageLoader:
    """Loads entitled images from a Chainguard organization."""

    def __init__(
        self,
        organization: str,
        cache_dir: Optional[Path] = None,
        github_token: Optional[str] = None,
    ):
        """
        Initialize the organization image loader.

        Args:
            organization: Chainguard organization name (e.g., 'chainguard-private')
            cache_dir: Directory for caching (default: ~/.cache/gauge)
            github_token: GitHub token for fetching metadata from images-private repo
        """
        self.organization = organization
        self.cache_dir = ensure_cache_dir(cache_dir)
        self.github_token = github_token

        # Lazy import to avoid circular dependencies
        self._github_client = None

    @property
    def github_client(self):
        """Lazy-load the GitHub metadata client."""
        if self._github_client is None:
            from forge_gauge.integrations.github_metadata import GitHubMetadataClient
            self._github_client = GitHubMetadataClient(github_token=self.github_token)
        return self._github_client

    def load_image_pairs(self) -> list[ImagePair]:
        """
        Load all entitled images and their alternatives as ImagePairs.

        Returns:
            List of ImagePair objects with Chainguard and alternative images
        """
        entitled_images = self._list_entitled_images()
        logger.info(f"Found {len(entitled_images)} entitled images in organization '{self.organization}'")

        pairs = []
        skipped_no_metadata = []
        skipped_no_aliases = []

        for image_name in entitled_images:
            alternative = self._get_alternative_image(image_name)
            if alternative:
                chainguard_ref = f"cgr.dev/{self.organization}/{image_name}:latest"
                pairs.append(ImagePair(
                    chainguard_image=chainguard_ref,
                    alternative_image=alternative,
                ))
                logger.debug(f"Loaded: {alternative} -> {chainguard_ref}")
            elif alternative is None:
                # Distinguish between no metadata and no aliases
                skipped_no_metadata.append(image_name)
            else:
                skipped_no_aliases.append(image_name)

        if skipped_no_metadata:
            logger.warning(
                f"Skipped {len(skipped_no_metadata)} images without metadata: "
                f"{', '.join(skipped_no_metadata[:5])}{'...' if len(skipped_no_metadata) > 5 else ''}"
            )

        if skipped_no_aliases:
            logger.warning(
                f"Skipped {len(skipped_no_aliases)} images without aliases: "
                f"{', '.join(skipped_no_aliases[:5])}{'...' if len(skipped_no_aliases) > 5 else ''}"
            )

        return pairs

    def _list_entitled_images(self) -> list[str]:
        """
        List all entitled images in the organization via chainctl.

        Returns:
            Sorted list of image names

        Raises:
            RuntimeError: If chainctl is not available or fails
        """
        cache_file = self.cache_dir / f"org_catalog_{self.organization}.json"

        # Check cache
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cache_data = json.load(f)
                cache_age = time.time() - cache_data.get("timestamp", 0)
                if cache_age < CATALOG_CACHE_TTL_SECONDS:
                    images = cache_data.get("images", [])
                    logger.debug(
                        f"Using cached organization catalog ({len(images)} images, age: {cache_age:.0f}s)"
                    )
                    return images
            except (json.JSONDecodeError, OSError) as e:
                logger.debug(f"Failed to load catalog cache: {e}")

        # Verify chainctl is available
        if not shutil.which("chainctl"):
            raise RuntimeError(
                "chainctl not found - required for organization scanning.\n"
                "Install from: https://edu.chainguard.dev/chainguard/administration/how-to-install-chainctl/"
            )

        logger.info(f"Fetching entitled images from organization '{self.organization}'...")

        try:
            result = subprocess.run(
                ["chainctl", "img", "repos", "list", "--parent", self.organization, "-o", "json"],
                capture_output=True,
                text=True,
                timeout=CLI_SUBPROCESS_TIMEOUT,
            )

            if result.returncode != 0:
                stderr = result.stderr.strip()
                # Check for "No folder found" error - user doesn't have access to org
                if "No folder found" in stderr or '"code":4' in stderr:
                    raise RuntimeError(
                        f"You don't have access to organization '{self.organization}'.\n\n"
                        "Possible solutions:\n"
                        f'  1. Login as a support user:\n'
                        f'     chainctl auth login --identity=$(chainctl iam ids ls --parent=chainguard-support --name="{self.organization} support identity" --output=id)\n\n'
                        f"  2. Request access from the organization owner to be added to '{self.organization}'"
                    )
                raise RuntimeError(f"chainctl failed: {stderr}")

            repos_data = json.loads(result.stdout)
            items = repos_data.get("items", [])
            images = sorted([item.get("name", "") for item in items if item.get("name")])

            # Cache the results
            try:
                cache_data = {"timestamp": time.time(), "images": images}
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(cache_data, f)
                logger.debug(f"Cached {len(images)} images to {cache_file}")
            except OSError as e:
                logger.debug(f"Failed to cache catalog: {e}")

            return images

        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"chainctl timed out after {CLI_SUBPROCESS_TIMEOUT}s. "
                "Check your network connection and chainctl authentication."
            )
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Failed to parse chainctl output: {e}")

    def _get_alternative_image(self, image_name: str) -> Optional[str]:
        """
        Get the first alternative image reference from metadata.yaml.

        Args:
            image_name: Name of the Chainguard image

        Returns:
            - First alias string if metadata exists and has aliases
            - Empty string ("") if metadata exists but has no aliases
            - None if metadata could not be fetched (missing or error)

        Note:
            The caller should distinguish between the return values:
            - truthy value (non-empty string): use as alternative image
            - None: metadata not found (skip with "no metadata" reason)
            - "" (empty): metadata found but no aliases (skip with "no aliases" reason)
        """
        try:
            metadata = self.github_client.get_image_metadata(image_name)
            if metadata is None:
                return None

            aliases = metadata.get("aliases", [])
            if aliases:
                return aliases[0]
            else:
                return ""

        except Exception as e:
            logger.debug(f"Failed to get metadata for {image_name}: {e}")
            return None
