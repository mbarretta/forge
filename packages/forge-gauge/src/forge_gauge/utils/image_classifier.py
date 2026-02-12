"""
Image classification system for determining Chainguard image tiers.

Maintains a local dictionary of image->tier mappings and fetches missing
information from GitHub metadata as needed.
"""

import logging
from typing import Optional

import yaml

from forge_gauge.core.models import ImageTier
from forge_gauge.integrations.github_metadata import GitHubMetadataClient
from forge_gauge.utils.image_utils import extract_base_name
from forge_gauge.utils.paths import get_config_path

logger = logging.getLogger(__name__)

# Path to tier mappings file (resolved via paths module)
TIER_MAPPINGS_FILE = get_config_path("image_tiers.yaml")


class ImageClassifier:
    """
    Classifier for determining Chainguard image tiers.

    Uses a local dictionary of known tiers, falling back to GitHub API
    for unknown images.
    """

    def __init__(self, github_token: Optional[str] = None, auto_update: bool = True):
        """
        Initialize image classifier.

        Args:
            github_token: Optional GitHub token for API access.
                         If None, GitHubMetadataClient will try env var and gh CLI.
            auto_update: If True, automatically fetch and save unknown tiers
        """
        # Always create GitHubMetadataClient - it will handle token fallback internally
        # Passing None allows the client to try GITHUB_TOKEN env var and gh CLI
        self.github_client = GitHubMetadataClient(github_token)
        self.auto_update = auto_update
        self.tier_mappings: dict[str, str] = {}
        self.modified = False
        self._load_tier_mappings()

    def _load_tier_mappings(self):
        """Load tier mappings from YAML file."""
        if not TIER_MAPPINGS_FILE.exists():
            logger.warning(f"Tier mappings file not found: {TIER_MAPPINGS_FILE}")
            self.tier_mappings = {}
            return

        try:
            with open(TIER_MAPPINGS_FILE, "r") as f:
                content = yaml.safe_load(f)
                self.tier_mappings = content if isinstance(content, dict) else {}
            logger.debug(f"Loaded {len(self.tier_mappings)} tier mappings from {TIER_MAPPINGS_FILE}")
        except Exception as e:
            logger.error(f"Failed to load tier mappings: {e}")
            self.tier_mappings = {}

    def save_tier_mappings(self):
        """Save tier mappings to YAML file."""
        if not self.modified:
            logger.debug("No changes to tier mappings, skipping save")
            return

        try:
            # Ensure directory exists
            TIER_MAPPINGS_FILE.parent.mkdir(parents=True, exist_ok=True)

            with open(TIER_MAPPINGS_FILE, "w") as f:
                # Write header comment
                f.write("# Chainguard Image Tier Mappings\n")
                f.write("# This file is automatically maintained by Gauge\n")
                f.write("#\n")
                f.write("# Tiers:\n")
                f.write("#   - base: Base images (minimal OS, language runtimes)\n")
                f.write("#   - application: Application images (full apps, databases, etc.)\n")
                f.write("#   - fips: FIPS-validated images\n")
                f.write("#   - ai: AI/ML framework images\n\n")

                # Write mappings sorted by key
                yaml.dump(
                    dict(sorted(self.tier_mappings.items())),
                    f,
                    default_flow_style=False,
                    sort_keys=False,
                )

            logger.info(f"Saved {len(self.tier_mappings)} tier mappings to {TIER_MAPPINGS_FILE}")
            self.modified = False

        except Exception as e:
            logger.error(f"Failed to save tier mappings: {e}")
            raise

    def _normalize_image_name(self, image: str) -> str:
        """
        Normalize image reference to base name.

        Args:
            image: Image reference (e.g., "cgr.dev/chainguard-private/python:latest")

        Returns:
            Base image name (e.g., "python")
        """
        return extract_base_name(image)

    def get_image_tier(self, image: str) -> ImageTier:
        """
        Get tier for a Chainguard image.

        Checks local dictionary first, then fetches from GitHub if needed
        and auto_update is enabled.

        Args:
            image: Chainguard image reference

        Returns:
            ImageTier enum value

        Raises:
            ValueError: If tier cannot be determined
        """
        normalized_name = self._normalize_image_name(image)

        # Check local dictionary first
        if normalized_name in self.tier_mappings:
            tier_value = self.tier_mappings[normalized_name]
            logger.debug(f"Found tier '{tier_value}' for {normalized_name} in local mappings")
            return ImageTier(tier_value)

        # Not in dictionary - fetch from GitHub if enabled
        if not self.auto_update:
            raise ValueError(
                f"Image '{normalized_name}' not found in tier mappings and auto_update is disabled. "
                f"Run 'gauge setup update-tiers' or enable auto_update."
            )

        if not self.github_client.token:
            raise ValueError(
                f"Image '{normalized_name}' not found in tier mappings and no GitHub token provided. "
                f"Set GITHUB_TOKEN environment variable or provide token to classifier."
            )

        logger.info(f"Fetching tier for unknown image '{normalized_name}' from GitHub...")

        try:
            tier = self.github_client.get_image_tier(normalized_name)

            # Save to local dictionary
            self.tier_mappings[normalized_name] = tier.value
            self.modified = True

            logger.info(f"Added {normalized_name} -> {tier.value} to tier mappings")

            # Auto-save if enabled
            if self.auto_update:
                self.save_tier_mappings()
                logger.info(
                    f"✓ Updated {TIER_MAPPINGS_FILE} with new tier mapping. "
                    "Please commit this change to share with your team."
                )

            return tier

        except Exception as e:
            raise ValueError(
                f"Failed to determine tier for image '{normalized_name}': {e}. "
                "This image may not exist in the Chainguard catalog or metadata may be unavailable."
            )

    def classify_images(self, images: list[str]) -> dict[str, ImageTier]:
        """
        Classify multiple images at once.

        Args:
            images: List of Chainguard image references

        Returns:
            Dictionary mapping normalized image names to tiers

        Raises:
            ValueError: If any image cannot be classified
        """
        results = {}
        errors = []

        for image in images:
            normalized_name = self._normalize_image_name(image)
            try:
                tier = self.get_image_tier(image)
                results[normalized_name] = tier
            except ValueError as e:
                errors.append(f"{normalized_name}: {e}")

        if errors:
            raise ValueError(
                f"Failed to classify {len(errors)} image(s):\n" + "\n".join(errors)
            )

        return results
