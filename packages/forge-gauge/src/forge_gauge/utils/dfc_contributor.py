"""
DFC contribution helper for generating mapping suggestions and git diffs.

Analyzes successful Tier 4 LLM matches and generates:
1. YAML file with suggested new DFC mappings
2. Git diff patch for easier PR creation
"""

import logging
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from forge_gauge.constants import DFC_CONTRIBUTION_THRESHOLD
from forge_gauge.utils.image_matcher import MatchResult
from forge_gauge.utils.image_utils import extract_base_name

logger = logging.getLogger(__name__)


class DFCContributor:
    """
    Helper for contributing new mappings to DFC project.

    Collects successful Tier 4 LLM matches and generates contribution materials.
    """

    def __init__(self, output_dir: Optional[Path] = None):
        """
        Initialize DFC contributor.

        Args:
            output_dir: Directory for generated files (default: current directory)
        """
        self.output_dir = output_dir or Path.cwd()
        self.suggestions: list[tuple[str, str, MatchResult]] = []

    def add_match(self, alternative_image: str, result: MatchResult) -> None:
        """
        Add a successful match for potential DFC contribution.

        Args:
            alternative_image: Source/alternative image name
            result: Match result from any tier (heuristic or LLM)
        """
        # Only add heuristic (Tier 3) or LLM (Tier 4) matches with high confidence
        # Skip DFC (Tier 1) and manual (Tier 2) as they're already in mappings
        if result.method in ["heuristic", "llm"] and result.confidence >= DFC_CONTRIBUTION_THRESHOLD:
            self.suggestions.append((alternative_image, result.chainguard_image, result))
            logger.debug(
                f"Added DFC suggestion ({result.method}): {alternative_image} → {result.chainguard_image} "
                f"(confidence: {result.confidence:.0%})"
            )

    def generate_suggestions_file(self) -> Path:
        """
        Generate YAML file with suggested DFC mappings.

        Returns:
            Path to generated suggestions file
        """
        if not self.suggestions:
            logger.warning("No DFC suggestions to generate")
            return None

        # Build YAML structure
        suggestions_data = {
            "metadata": {
                "generated_by": "gauge",
                "timestamp": datetime.now().isoformat(),
                "description": "Suggested DFC mappings from LLM-powered Tier 4 matching",
                "total_suggestions": len(self.suggestions),
            },
            "suggested_mappings": {},
        }

        # Add suggestions with metadata
        for alt_image, cg_image, result in self.suggestions:
            # Extract base image name for DFC format
            base_name = self._extract_base_name(alt_image)

            # Extract Chainguard image name (remove cgr.dev/chainguard/ prefix and :latest suffix)
            cg_name = self._extract_cg_name(cg_image)

            suggestions_data["suggested_mappings"][base_name] = {
                "target": cg_name,
                "confidence": result.confidence,
                "reasoning": result.reasoning if hasattr(result, "reasoning") else None,
                "example_source": alt_image,
            }

        # Write YAML file
        output_file = self.output_dir / "dfc-suggestions.yaml"
        with open(output_file, "w", encoding="utf-8") as f:
            yaml.dump(suggestions_data, f, default_flow_style=False, sort_keys=False)

        logger.info(f"Generated DFC suggestions file: {output_file}")
        logger.info(f"Total suggestions: {len(self.suggestions)}")

        return output_file

    def generate_git_diff(self, dfc_repo_path: Optional[Path] = None) -> Path:
        """
        Generate git diff patch for DFC builtin-mappings.yaml.

        Creates a temporary modified version of builtin-mappings.yaml and generates
        a unified diff that can be applied to the DFC repository.

        Args:
            dfc_repo_path: Optional path to local DFC repository clone
                          (if None, uses cached version from ~/.cache/gauge)

        Returns:
            Path to generated patch file
        """
        if not self.suggestions:
            logger.warning("No DFC suggestions to generate diff")
            return None

        # Determine source DFC mappings file
        if dfc_repo_path:
            dfc_file = dfc_repo_path / "pkg" / "dfc" / "builtin-mappings.yaml"
            if not dfc_file.exists():
                logger.warning(
                    f"DFC mappings file not found at {dfc_file}, using cached version"
                )
                dfc_file = Path.home() / ".cache" / "gauge" / "dfc-mappings.yaml"
        else:
            dfc_file = Path.home() / ".cache" / "gauge" / "dfc-mappings.yaml"

        if not dfc_file.exists():
            logger.error(f"Cannot generate diff: DFC mappings file not found at {dfc_file}")
            return None

        # Read original file as text to preserve formatting and comments
        with open(dfc_file, "r", encoding="utf-8") as f:
            original_lines = f.readlines()

        # Also parse to get data structure
        with open(dfc_file, "r", encoding="utf-8") as f:
            dfc_data = yaml.safe_load(f)

        if not isinstance(dfc_data, dict) or "images" not in dfc_data:
            logger.error("Invalid DFC mappings format")
            return None

        original_count = len(dfc_data["images"])

        # Collect new entries to add
        new_entries = {}
        for alt_image, cg_image, result in self.suggestions:
            base_name = self._extract_base_name(alt_image)
            cg_name = self._extract_cg_name(cg_image)

            # Only add if not already in DFC mappings
            if base_name not in dfc_data["images"]:
                new_entries[base_name] = cg_name
                logger.debug(f"Adding to diff: {base_name} → {cg_name}")

        if not new_entries:
            logger.info("All suggestions already exist in DFC mappings, no diff to generate")
            return None

        added_count = len(new_entries)

        # Insert new entries into the text, maintaining alphabetical order
        # Find the "images:" line
        images_line_idx = None
        for i, line in enumerate(original_lines):
            if line.strip() == "images:":
                images_line_idx = i
                break

        if images_line_idx is None:
            logger.error("Could not find 'images:' section in DFC file")
            return None

        # Build list of all entries (existing + new) in sorted order
        all_entries = {**dfc_data["images"], **new_entries}
        sorted_entries = sorted(all_entries.items())

        # Rebuild the images section with proper formatting (4-space indentation)
        new_images_lines = ["images:\n"]
        for key, value in sorted_entries:
            new_images_lines.append(f"    {key}: {value}\n")

        # Replace the images section in the original file
        # Find where the images section ends (next top-level key or EOF)
        section_end_idx = len(original_lines)
        for i in range(images_line_idx + 1, len(original_lines)):
            # Check if this is a new top-level key (no leading whitespace)
            if original_lines[i].strip() and not original_lines[i].startswith((' ', '\t')):
                section_end_idx = i
                break

        # Construct modified file
        modified_lines = (
            original_lines[:images_line_idx] +
            new_images_lines +
            original_lines[section_end_idx:]
        )

        # Write modified version to temp file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as temp_file:
            temp_file.writelines(modified_lines)
            temp_file_path = temp_file.name

        try:
            # Generate unified diff
            diff_output = subprocess.run(
                [
                    "diff",
                    "-u",
                    str(dfc_file),
                    temp_file_path,
                ],
                capture_output=True,
                text=True,
            )

            # diff returns exit code 1 when there are differences (this is expected)
            if diff_output.returncode not in (0, 1):
                logger.error(f"diff command failed: {diff_output.stderr}")
                return None

            # Write diff to patch file
            patch_file = self.output_dir / "dfc-suggestions.patch"
            with open(patch_file, "w", encoding="utf-8") as f:
                # Add header to patch
                f.write(f"# DFC Mapping Suggestions\n")
                f.write(f"# Generated by gauge on {datetime.now().isoformat()}\n")
                f.write(f"# Added {added_count} new mappings\n")
                f.write(f"#\n")
                f.write(f"# To apply this patch:\n")
                f.write(f"#   cd /path/to/dfc\n")
                f.write(
                    f"#   patch -p0 < {patch_file.name} (adjust path in diff headers if needed)\n"
                )
                f.write(f"#\n")
                f.write(
                    f"# Or manually copy the additions from dfc-suggestions.yaml to builtin-mappings.yaml\n"
                )
                f.write(f"\n")

                # Replace temp file path with correct DFC path in diff headers
                diff_text = diff_output.stdout
                diff_text = diff_text.replace(
                    temp_file_path, "pkg/dfc/builtin-mappings.yaml"
                )
                diff_text = diff_text.replace(
                    str(dfc_file), "pkg/dfc/builtin-mappings.yaml"
                )

                f.write(diff_text)

            logger.info(f"Generated DFC patch file: {patch_file}")
            logger.info(f"Added {added_count} new mappings (original: {original_count})")

            return patch_file

        finally:
            # Clean up temp file
            Path(temp_file_path).unlink(missing_ok=True)

    def _extract_base_name(self, image: str) -> str:
        """
        Extract base image name for DFC format.

        Examples:
            docker.io/library/python:3.12 → python
            ghcr.io/kyverno/background-controller:v1.10.3 → background-controller
            nginx:1.25 → nginx
        """
        return extract_base_name(image)

    def _extract_cg_name(self, cg_image: str) -> str:
        """
        Extract Chainguard image name for DFC format.

        Examples:
            cgr.dev/chainguard/python:latest → python
            cgr.dev/chainguard-private/nginx-fips:latest → nginx-fips
        """
        return extract_base_name(cg_image)

    def generate_all(self, dfc_repo_path: Optional[Path] = None) -> dict[str, Path]:
        """
        Generate both suggestions file and git diff.

        Args:
            dfc_repo_path: Optional path to local DFC repository clone

        Returns:
            Dictionary with paths to generated files:
            {'suggestions': Path, 'patch': Path}
        """
        if not self.suggestions:
            logger.warning("No DFC suggestions to generate")
            return {}

        results = {}

        # Generate suggestions YAML
        suggestions_file = self.generate_suggestions_file()
        if suggestions_file:
            results["suggestions"] = suggestions_file

        # Generate git diff patch
        patch_file = self.generate_git_diff(dfc_repo_path)
        if patch_file:
            results["patch"] = patch_file

        return results
