"""ToolPlugin implementation for gauge."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from forge_core.context import ExecutionContext
from forge_core.deps import assert_dependencies
from forge_core.plugin import ResultStatus, ToolParam, ToolResult

from forge_gauge.constants import (
    DEFAULT_CHPS_MAX_WORKERS,
    DEFAULT_HOURLY_RATE,
    DEFAULT_HOURS_PER_VULNERABILITY,
    DEFAULT_LLM_CONFIDENCE,
    DEFAULT_LLM_MODEL,
    DEFAULT_MATCH_CONFIDENCE,
    DEFAULT_MAX_WORKERS,
    DEFAULT_PLATFORM,
    DEFAULT_UPSTREAM_CONFIDENCE,
    __version__,
)

logger = logging.getLogger(__name__)

# External CLI tools required by gauge
REQUIRED_TOOLS: list[str] = ["gauge", "crane", "grype", "chainctl", "cosign"]


class GaugePlugin:
    """FORGE plugin for gauge - container vulnerability scanning and image matching."""

    name = "gauge"
    description = "Container vulnerability scanning and image matching"
    version = __version__

    def get_params(self) -> list[ToolParam]:
        """Declare parameters for gauge commands.

        The "command" parameter is treated as a positional subcommand by the CLI:
        - forge gauge scan --input file.csv
        - forge gauge match --input file.csv
        """
        return [
            # Subcommand selection (positional in CLI, not a --flag)
            ToolParam(
                name="command",
                description="Subcommand: scan or match",
                required=True,
                choices=["scan", "match"],
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
                description=(
                    "Output types: vuln_summary (HTML), cost_analysis (XLSX), "
                    "pricing, pricing:html, pricing:txt (comma-separated). Scan only."
                ),
            ),
            ToolParam(
                name="output-dir",
                description="Output directory for generated files",
                default="output",
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
            ToolParam(
                name="verbose",
                description="Enable verbose logging",
                type="bool",
            ),
            ToolParam(
                name="disable-mapping-auto-population",
                description="Disable auto-populating manual upstream mappings",
                type="bool",
            ),
        ]

    def run(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        """Execute gauge command."""
        self._seed_config()
        assert_dependencies(REQUIRED_TOOLS)

        command = args["command"]

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
        else:
            return ToolResult(
                status=ResultStatus.FAILURE,
                summary=f"Unknown command: {command}",
            )

    def _seed_config(self) -> None:
        """Copy bundled config files to ~/.gauge/config/ if not already present."""
        gauge_config_dir = Path.home() / ".gauge" / "config"
        gauge_config_dir.mkdir(parents=True, exist_ok=True)

        # Installed package: config/ lives alongside plugin.py inside the wheel.
        # Editable/dev install: config/ is at the package root (packages/forge-gauge/config/).
        bundled_config = Path(__file__).parent / "config"
        if not bundled_config.is_dir():
            bundled_config = Path(__file__).parent.parent.parent / "config"
        if not bundled_config.is_dir():
            return

        for src_file in bundled_config.iterdir():
            if src_file.is_file():
                dest_file = gauge_config_dir / src_file.name
                if not dest_file.exists():
                    shutil.copy2(src_file, dest_file)
                    logger.debug("Seeded config file: %s", dest_file)

    def _build_cmd(self, subcommand: str, args: dict[str, Any]) -> list[str]:
        """Build gauge CLI command from FORGE args dict.

        Args dict keys use underscores (argparse convention); we convert back to
        hyphens to match gauge's CLI flags (e.g. retry_failures → --retry-failures).
        """
        cmd = ["gauge", subcommand]

        for key, value in args.items():
            if key == "command":
                continue
            flag = f"--{key.replace('_', '-')}"
            if isinstance(value, bool):
                if value:
                    cmd.append(flag)
            elif value is not None:
                cmd.extend([flag, str(value)])

        return cmd

    def _run_scan(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        """Execute gauge scan command."""
        # Validate mutually exclusive flags before delegating to subprocess
        if args.get("retry_failures") and args.get("resume"):
            return ToolResult(
                status=ResultStatus.FAILURE,
                summary="--retry-failures and --resume are mutually exclusive",
            )
        if args.get("skip_permanent_failures") and not args.get("retry_failures"):
            return ToolResult(
                status=ResultStatus.FAILURE,
                summary="--skip-permanent-failures requires --retry-failures",
            )
        if args.get("retry_failures"):
            checkpoint = Path(args.get("checkpoint_file", ".gauge_checkpoint.json"))
            if not checkpoint.exists():
                return ToolResult(
                    status=ResultStatus.FAILURE,
                    summary=f"--retry-failures requires existing checkpoint file: {checkpoint}",
                )

        ctx.progress(0.0, "Starting vulnerability scan")

        cmd = self._build_cmd("scan", args)
        result = subprocess.run(cmd, text=True)

        if result.returncode != 0:
            return ToolResult(
                status=ResultStatus.FAILURE,
                summary=result.stderr or f"gauge scan failed with exit code {result.returncode}",
            )

        ctx.progress(1.0, "Scan complete")

        # Collect output artifacts
        artifacts: dict[str, str] = {}
        output_dir = Path(args.get("output_dir", "output"))
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

    def _run_match(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        """Execute gauge match command."""
        ctx.progress(0.0, "Starting image matching")

        cmd = self._build_cmd("match", args)
        result = subprocess.run(cmd, text=True)

        if result.returncode != 0:
            return ToolResult(
                status=ResultStatus.FAILURE,
                summary=result.stderr or f"gauge match failed with exit code {result.returncode}",
            )

        ctx.progress(1.0, "Matching complete")

        # Parse matched-log.yaml for matched/unmatched counts
        output_dir = Path(args.get("output_dir", "output"))
        output_file = output_dir / "matched-log.yaml"
        matched = 0
        unmatched = 0
        if output_file.exists():
            try:
                import yaml

                with open(output_file) as f:
                    data = yaml.safe_load(f)
                if isinstance(data, dict):
                    matched = len(data.get("matched", []))
                    unmatched = len(data.get("unmatched", []))
            except Exception:
                pass

        artifacts: dict[str, str] = {}
        if output_file.exists():
            artifacts["match_log"] = str(output_file.resolve())

        return ToolResult(
            status=ResultStatus.SUCCESS if unmatched == 0 else ResultStatus.PARTIAL,
            summary=f"Matched {matched} images, {unmatched} unmatched",
            data={"matched": matched, "unmatched": unmatched},
            artifacts=artifacts,
        )
