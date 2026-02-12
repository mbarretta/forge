"""ToolPlugin implementation for gauge."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any

from forge_core.context import ExecutionContext
from forge_core.deps import assert_dependencies
from forge_core.plugin import ToolParam, ToolResult, ResultStatus

from forge_gauge.constants import (
    __version__,
    DEFAULT_HOURS_PER_VULNERABILITY,
    DEFAULT_HOURLY_RATE,
    DEFAULT_MAX_WORKERS,
    DEFAULT_PLATFORM,
    DEFAULT_CHPS_MAX_WORKERS,
    DEFAULT_MATCH_CONFIDENCE,
    DEFAULT_UPSTREAM_CONFIDENCE,
    DEFAULT_LLM_CONFIDENCE,
    DEFAULT_LLM_MODEL,
)

logger = logging.getLogger(__name__)

# External CLI tools required by gauge
REQUIRED_TOOLS: list[str] = ["crane", "grype", "chainctl", "cosign"]


class GaugePlugin:
    """FORGE plugin for gauge - container vulnerability scanning and image matching."""

    name = "gauge"
    description = "Container vulnerability scanning and image matching"
    version = __version__

    def get_params(self) -> list[ToolParam]:
        """Declare parameters for gauge commands."""
        return [
            # Command selection
            ToolParam(
                name="command",
                description="Command to run",
                required=True,
                choices=["scan", "match", "update"],
            ),
            # Input/Output arguments (common to scan and match)
            ToolParam(
                name="input",
                description="Input CSV file, single image reference, or organization",
            ),
            ToolParam(
                name="organization",
                description="Chainguard organization to scan (discovers images from metadata)",
            ),
            ToolParam(
                name="output",
                description="Output types (comma-separated, e.g. html,xlsx,yaml)",
            ),
            ToolParam(
                name="output-dir",
                description="Output directory",
                default=".",
            ),
            ToolParam(
                name="customer",
                description="Customer name",
                default="Customer",
            ),
            # Scan-specific options
            ToolParam(
                name="pricing-policy",
                description="Pricing policy file path",
                default="pricing-policy.yaml",
            ),
            ToolParam(
                name="exec-summary",
                description="Executive summary file path",
                default="exec-summary.md",
            ),
            ToolParam(
                name="appendix",
                description="Custom appendix file path",
                default="appendix.md",
            ),
            ToolParam(
                name="hours-per-vuln",
                description="Hours per vulnerability",
                type="float",
                default=DEFAULT_HOURS_PER_VULNERABILITY,
            ),
            ToolParam(
                name="hourly-rate",
                description="Hourly rate in USD",
                type="float",
                default=DEFAULT_HOURLY_RATE,
            ),
            # Performance options
            ToolParam(
                name="max-workers",
                description="Number of parallel workers",
                type="int",
                default=DEFAULT_MAX_WORKERS,
            ),
            ToolParam(
                name="platform",
                description="Image platform",
                default=DEFAULT_PLATFORM,
            ),
            # Cache options
            ToolParam(
                name="cache-dir",
                description="Cache directory",
                default=".cache",
            ),
            ToolParam(
                name="no-cache",
                description="Disable caching",
                type="bool",
            ),
            ToolParam(
                name="clear-cache",
                description="Clear cache before running",
                type="bool",
            ),
            ToolParam(
                name="no-fresh-check",
                description="Skip fresh image check",
                type="bool",
            ),
            ToolParam(
                name="resume",
                description="Resume from checkpoint",
                type="bool",
            ),
            ToolParam(
                name="checkpoint-file",
                description="Checkpoint file path",
                default=".gauge_checkpoint.json",
            ),
            ToolParam(
                name="retry-failures",
                description="Retry only failed comparisons from checkpoint",
                type="bool",
            ),
            ToolParam(
                name="skip-permanent-failures",
                description="Skip auth/not_found errors when retrying",
                type="bool",
            ),
            # Matching options
            ToolParam(
                name="min-confidence",
                description="Minimum confidence threshold (0.0-1.0)",
                type="float",
                default=DEFAULT_MATCH_CONFIDENCE,
            ),
            ToolParam(
                name="skip-public-repo-search",
                description="Skip upstream public repository search",
                type="bool",
            ),
            ToolParam(
                name="upstream-confidence",
                description="Upstream discovery confidence threshold",
                type="float",
                default=DEFAULT_UPSTREAM_CONFIDENCE,
            ),
            ToolParam(
                name="upstream-mappings-file",
                description="Upstream mappings file path",
            ),
            ToolParam(
                name="dfc-mappings-file",
                description="DFC mappings file path",
            ),
            ToolParam(
                name="disable-llm-matching",
                description="Disable LLM-based fuzzy matching",
                type="bool",
            ),
            ToolParam(
                name="llm-model",
                description="LLM model to use for matching",
                default=DEFAULT_LLM_MODEL,
            ),
            ToolParam(
                name="llm-confidence-threshold",
                description="LLM matching confidence threshold",
                type="float",
                default=DEFAULT_LLM_CONFIDENCE,
            ),
            ToolParam(
                name="anthropic-api-key",
                description="Anthropic API key for LLM matching",
            ),
            ToolParam(
                name="generate-dfc-pr",
                description="Generate DFC contribution PR",
                type="bool",
            ),
            ToolParam(
                name="github-token",
                description="GitHub token for PR generation",
            ),
            ToolParam(
                name="always-match-cgr-latest",
                description="Always match to :latest tag of Chainguard images",
                type="bool",
            ),
            # Match-specific options
            ToolParam(
                name="interactive",
                description="Enable interactive matching mode",
                type="bool",
            ),
            ToolParam(
                name="known-registries",
                description="Comma-separated list of registries with credentials",
            ),
            # Feature flags
            ToolParam(
                name="with-chps",
                description="Include CHPS scoring",
                type="bool",
            ),
            ToolParam(
                name="with-fips",
                description="Include FIPS analysis / prefer FIPS variants",
                type="bool",
            ),
            ToolParam(
                name="with-kevs",
                description="Include KEV data",
                type="bool",
            ),
            ToolParam(
                name="with-all",
                description="Enable all optional features",
                type="bool",
            ),
            ToolParam(
                name="include-negligible",
                description="Include Negligible/Unknown CVEs in counts",
                type="bool",
            ),
            ToolParam(
                name="chps-max-workers",
                description="Number of parallel CHPS scanning threads",
                type="int",
                default=DEFAULT_CHPS_MAX_WORKERS,
            ),
            # Authentication options
            ToolParam(
                name="gcr-credentials",
                description="Path to Google Cloud service account JSON",
            ),
            ToolParam(
                name="no-gcr-auth",
                description="Disable automatic GCR authentication",
                type="bool",
            ),
        ]

    def run(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        """Execute gauge command."""
        # Check external dependencies
        assert_dependencies(REQUIRED_TOOLS)

        command = args["command"]

        # Validate command-specific requirements
        if command == "scan":
            if not args.get("input") and not args.get("organization"):
                return ToolResult(
                    status=ResultStatus.FAILURE,
                    summary="scan command requires --input or --organization",
                )
            return self._run_scan(args, ctx)
        elif command == "match":
            if not args.get("input"):
                return ToolResult(
                    status=ResultStatus.FAILURE,
                    summary="match command requires --input",
                )
            return self._run_match(args, ctx)
        elif command == "update":
            return self._run_update(args, ctx)
        else:
            return ToolResult(
                status=ResultStatus.FAILURE,
                summary=f"Unknown command: {command}",
            )

    def _run_scan(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        """Execute gauge scan command."""
        from forge_gauge.core.orchestrator import GaugeOrchestrator

        # Convert args dict to argparse Namespace
        scan_args = self._args_to_namespace(args)

        # Handle --with-all flag
        if scan_args.with_all:
            scan_args.with_chps = True
            scan_args.with_fips = True
            scan_args.with_kevs = True

        ctx.progress(0.0, "Starting vulnerability scan")

        try:
            orchestrator = GaugeOrchestrator(scan_args)
            orchestrator.run()

            ctx.progress(1.0, "Scan complete")

            # Collect output artifacts
            artifacts = {}
            output_dir = Path(args.get("output-dir", "."))

            # Look for generated files
            for pattern in ["*.html", "*.xlsx", "*.yaml", "*.csv"]:
                for file in output_dir.glob(pattern):
                    if file.is_file() and file.stat().st_size > 0:
                        artifacts[file.stem] = str(file.resolve())

            return ToolResult(
                status=ResultStatus.SUCCESS,
                summary="Vulnerability scan completed successfully",
                data={"command": "scan"},
                artifacts=artifacts,
            )
        except Exception as e:
            logger.exception("Scan command failed")
            return ToolResult(
                status=ResultStatus.FAILURE,
                summary=f"Scan failed: {str(e)}",
            )

    def _run_match(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        """Execute gauge match command."""
        from forge_gauge.commands.match import match_images

        match_args = self._args_to_namespace(args)
        input_file = Path(args["input"])

        if not input_file.exists():
            return ToolResult(
                status=ResultStatus.FAILURE,
                summary=f"Input file not found: {input_file}",
            )

        ctx.progress(0.0, "Starting image matching")

        # Parse known registries
        known_registries = None
        if args.get("known-registries"):
            known_registries = [
                r.strip() for r in args["known-registries"].split(",") if r.strip()
            ]

        try:
            matched_images, unmatched_images = match_images(
                input_file=input_file,
                output_file=Path(args.get("output", "output/matched-log.yaml")),
                output_dir=Path(args.get("output-dir", "output")),
                min_confidence=args.get("min-confidence", DEFAULT_MATCH_CONFIDENCE),
                interactive=args.get("interactive", False),
                dfc_mappings_file=args.get("dfc-mappings-file"),
                cache_dir=args.get("cache-dir"),
                find_upstream=not args.get("skip-public-repo-search", False),
                upstream_confidence=args.get("upstream-confidence", DEFAULT_UPSTREAM_CONFIDENCE),
                upstream_mappings_file=args.get("upstream-mappings-file"),
                enable_llm_matching=not args.get("disable-llm-matching", False),
                llm_model=args.get("llm-model", DEFAULT_LLM_MODEL),
                llm_confidence_threshold=args.get("llm-confidence-threshold", DEFAULT_LLM_CONFIDENCE),
                anthropic_api_key=args.get("anthropic-api-key"),
                generate_dfc_pr=args.get("generate-dfc-pr", False),
                github_token=args.get("github-token"),
                known_registries=known_registries,
                prefer_fips=args.get("with-fips", False),
                customer_name=args.get("customer", "Customer"),
                always_match_cgr_latest=args.get("always-match-cgr-latest", False),
            )

            ctx.progress(1.0, "Matching complete")

            return ToolResult(
                status=ResultStatus.SUCCESS if not unmatched_images else ResultStatus.PARTIAL,
                summary=f"Matched {len(matched_images)} images, {len(unmatched_images)} unmatched",
                data={
                    "matched": len(matched_images),
                    "unmatched": len(unmatched_images),
                },
                artifacts={"match_log": str(Path(args.get("output", "output/matched-log.yaml")).resolve())},
            )
        except Exception as e:
            logger.exception("Match command failed")
            return ToolResult(
                status=ResultStatus.FAILURE,
                summary=f"Match failed: {str(e)}",
            )

    def _run_update(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        """Execute gauge update command."""
        from forge_gauge.plugins.gauge_core.update_command import execute_update

        update_args = self._args_to_namespace(args)

        ctx.progress(0.0, "Checking for updates")

        try:
            exit_code = execute_update(update_args)
            ctx.progress(1.0, "Update check complete")

            return ToolResult(
                status=ResultStatus.SUCCESS if exit_code == 0 else ResultStatus.FAILURE,
                summary="Update check completed" if exit_code == 0 else "Update check failed",
                data={"command": "update"},
            )
        except Exception as e:
            logger.exception("Update command failed")
            return ToolResult(
                status=ResultStatus.FAILURE,
                summary=f"Update failed: {str(e)}",
            )

    def _args_to_namespace(self, args: dict[str, Any]) -> argparse.Namespace:
        """Convert args dict to argparse Namespace for compatibility with gauge internals."""
        ns = argparse.Namespace()

        # Map all parameters
        for key, value in args.items():
            # Convert hyphenated names to underscored (argparse convention)
            attr_name = key.replace("-", "_")
            setattr(ns, attr_name, value)

        return ns
