"""
Automatic population of manual image mappings.

Promotes successful Tier 3 (heuristic) and Tier 4 (LLM) matches to Tier 2 (manual)
for faster, more confident matching in future runs.
"""

import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from forge_gauge.constants import MANUAL_MAPPING_THRESHOLD
from forge_gauge.utils.image_matcher import MatchResult
from forge_gauge.utils.paths import get_config_path

logger = logging.getLogger(__name__)


class ManualMappingPopulator:
    """
    Automatically populates manual image mappings from successful matches.

    Collects high-confidence Tier 3/4 matches and appends them to the manual
    mappings file, promoting them to Tier 2 for future runs.
    """

    def __init__(
        self,
        mappings_file: Optional[Path] = None,
        min_confidence: float = MANUAL_MAPPING_THRESHOLD,
    ):
        """
        Initialize manual mapping populator.

        Args:
            mappings_file: Path to manual mappings file (default: config/image_mappings.yaml)
            min_confidence: Minimum confidence to auto-populate (default: 0.85)
        """
        self.mappings_file = mappings_file or get_config_path("image_mappings.yaml")
        self.min_confidence = min_confidence
        self.new_mappings: dict[str, tuple[str, MatchResult]] = {}

    def add_match(self, alternative_image: str, result: MatchResult) -> None:
        """
        Add a successful match for potential auto-population.

        Only adds Tier 3 (heuristic) and Tier 4 (LLM) matches with high confidence.
        Skips Tier 1 (DFC) and Tier 2 (manual) as they're already in mappings.

        Args:
            alternative_image: Source/alternative image name
            result: Match result from any tier
        """
        # Only add heuristic (Tier 3) or LLM (Tier 4) matches with high confidence
        if result.method in ["heuristic", "llm"] and result.confidence >= self.min_confidence:
            # Store with full image reference (including tag) for exact matching
            self.new_mappings[alternative_image] = (result.chainguard_image, result)
            logger.debug(
                f"Queued for auto-population ({result.method}): {alternative_image} → {result.chainguard_image} "
                f"(confidence: {result.confidence:.0%})"
            )

    def populate_mappings(self) -> int:
        """
        Write new mappings to the manual mappings file.

        Safely appends new mappings while preserving existing ones.
        Creates backup before modifying.

        Returns:
            Number of new mappings added
        """
        if not self.new_mappings:
            logger.debug("No new mappings to populate")
            return 0

        # Load existing mappings
        existing_mappings = {}
        if self.mappings_file.exists():
            try:
                with open(self.mappings_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    if data and isinstance(data, dict):
                        existing_mappings = data
                logger.debug(f"Loaded {len(existing_mappings)} existing manual mappings")
            except Exception as e:
                logger.warning(f"Failed to load existing mappings: {e}")

        # Filter out mappings that already exist
        truly_new = {}
        for image, (cg_image, result) in self.new_mappings.items():
            if image not in existing_mappings:
                truly_new[image] = cg_image
            else:
                logger.debug(f"Skipping {image}: already in manual mappings")

        if not truly_new:
            logger.info("All successful matches already exist in manual mappings")
            return 0

        # Create backup if file exists
        if self.mappings_file.exists():
            backup_file = self.mappings_file.with_suffix(".yaml.bak")
            shutil.copy2(self.mappings_file, backup_file)
            logger.debug(f"Created backup: {backup_file}")

        # Merge and sort mappings
        merged_mappings = {**existing_mappings, **truly_new}
        merged_mappings = dict(sorted(merged_mappings.items()))

        # Ensure parent directory exists
        self.mappings_file.parent.mkdir(parents=True, exist_ok=True)

        # Write updated mappings
        try:
            with open(self.mappings_file, "w", encoding="utf-8") as f:
                # Add header comment
                f.write("# Manual Image Mappings\n")
                f.write(f"# Last updated: {datetime.now().isoformat()}\n")
                f.write(f"# Total mappings: {len(merged_mappings)}\n")
                f.write("#\n")
                f.write("# Format: \"source:tag\": \"cgr.dev/chainguard[-private]/image:tag\"\n")
                f.write("#\n")
                f.write(f"# Auto-populated from successful matches:\n")
                for image in sorted(truly_new.keys()):
                    cg_image, result = self.new_mappings[image]
                    f.write(f"#   {image} → {cg_image} ({result.method}, {result.confidence:.0%})\n")
                f.write("#\n\n")

                yaml.dump(merged_mappings, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

            logger.info(
                f"✓ Auto-populated {len(truly_new)} new mappings to {self.mappings_file}"
            )

            return len(truly_new)

        except Exception as e:
            logger.error(f"Failed to write manual mappings: {e}")
            return 0
