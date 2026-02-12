"""
FORGE plugin wrapper for coverage checking tool.
"""

from __future__ import annotations

import argparse
import logging
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any

from forge_core.context import ExecutionContext
from forge_core.plugin import ResultStatus, ToolParam, ToolResult

# Import constants from check_coverage to avoid duplication
from forge_coverage.check_coverage import (
    SUPPORTED_ARCHITECTURES,
    SUPPORTED_MANYLINUX_VARIANTS,
    SUPPORTED_PYTHON_VERSIONS,
)

logger = logging.getLogger(__name__)


class CoveragePlugin:
    """Plugin for checking Python and JavaScript package coverage."""

    name = "coverage"
    version = "1.0.0"
    description = "Check Python and JavaScript package coverage in Chainguard libraries"

    def get_params(self) -> list[ToolParam]:
        return [
            # Main arguments
            ToolParam(
                name="requirements-file",
                description="Path to requirements.txt (Python) or package-lock.json (JavaScript) file(s)",
                type="str",
                required=False,
            ),
            ToolParam(
                name="mode",
                description="Mode: index (default), db, sql, csv, api, js",
                type="str",
                required=False,
                default="index",
                choices=["index", "db", "sql", "csv", "api", "js"],
            ),
            ToolParam(
                name="index-url",
                description="Index URL (Python simple index or JavaScript registry)",
                type="str",
                required=False,
                default="https://libraries.cgr.dev/python/simple",
            ),

            # Filter arguments (Python only)
            ToolParam(
                name="arch",
                description="Require wheels for specific architecture",
                type="str",
                required=False,
                choices=SUPPORTED_ARCHITECTURES,
            ),
            ToolParam(
                name="python-version",
                description="Require wheels for specific Python version",
                type="str",
                required=False,
                choices=SUPPORTED_PYTHON_VERSIONS,
            ),
            ToolParam(
                name="manylinux-variant",
                description="Require wheels for specific manylinux variant",
                type="str",
                required=False,
                choices=SUPPORTED_MANYLINUX_VARIANTS,
            ),
            ToolParam(
                name="workers",
                description="Number of parallel workers for index mode",
                type="int",
                required=False,
                default=10,
            ),

            # Database mode arguments
            ToolParam(
                name="database-url",
                description="Database connection string for database mode",
                type="str",
                required=False,
            ),
            ToolParam(
                name="generation",
                description="Look only for specific generation in database",
                type="str",
                required=False,
            ),
            ToolParam(
                name="csv",
                description="Path to CSV input file for csv mode",
                type="str",
                required=False,
            ),

            # API mode arguments
            ToolParam(
                name="issue",
                description="GitHub issue number (required for api mode)",
                type="str",
                required=False,
            ),
            ToolParam(
                name="token",
                description="OIDC token for authentication",
                type="str",
                required=False,
            ),
            ToolParam(
                name="api-url",
                description="Rebuilder API base URL",
                type="str",
                required=False,
                default="https://rebuilder-api-python.prod-eco.dev",
            ),
            ToolParam(
                name="organization-id",
                description="Organization ID",
                type="str",
                required=False,
            ),
            ToolParam(
                name="environment",
                description="Environment for chainctl token audience",
                type="str",
                required=False,
                default="prod",
                choices=["prod", "staging"],
            ),
            ToolParam(
                name="refresh",
                description="Refresh a request group (api mode only)",
                type="bool",
                required=False,
                default=False,
            ),
            ToolParam(
                name="force",
                description="Force reprocess all requests (with --refresh)",
                type="bool",
                required=False,
                default=False,
            ),

            # General arguments
            ToolParam(
                name="verbose",
                description="Enable verbose logging",
                type="bool",
                required=False,
                default=False,
            ),
        ]

    def run(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        """Execute the coverage check."""
        # Validate mode-specific requirements
        mode = args.get("mode", "index")

        if mode == "csv" and not args.get("csv"):
            return ToolResult(
                status=ResultStatus.FAILURE,
                summary="The --csv argument is required when mode is 'csv'",
            )

        if mode == "api":
            if not args.get("issue"):
                return ToolResult(
                    status=ResultStatus.FAILURE,
                    summary="The --issue argument is required when mode is 'api'",
                )
            if args.get("force") and not args.get("refresh"):
                return ToolResult(
                    status=ResultStatus.FAILURE,
                    summary="The --force argument can only be used with --refresh",
                )
        elif not args.get("requirements-file"):
            return ToolResult(
                status=ResultStatus.FAILURE,
                summary="At least one requirements-file is required",
            )

        # Set up logging level
        if args.get("verbose"):
            logger.setLevel(logging.DEBUG)

        try:
            # Import the check_coverage module
            from forge_coverage import check_coverage

            # Convert args dict to argparse.Namespace
            ns = self._args_to_namespace(args)

            ctx.progress(0.0, "Starting coverage check")

            # Capture stdout to return as output
            captured_output = StringIO()
            with redirect_stdout(captured_output):
                check_coverage.main_with_args(ns)

            output = captured_output.getvalue()
            ctx.progress(1.0, "Coverage check completed")

            return ToolResult(
                status=ResultStatus.SUCCESS,
                summary="Coverage check completed successfully",
                data={"output": output},
            )

        except Exception as e:
            logger.error(f"Coverage check failed: {e}", exc_info=True)
            return ToolResult(
                status=ResultStatus.FAILURE,
                summary=f"Coverage check failed: {e}",
            )

    def _args_to_namespace(self, args: dict[str, Any]) -> argparse.Namespace:
        """Convert args dict to argparse.Namespace for check_coverage.py."""
        ns = argparse.Namespace()

        # Convert requirements-file to requirements_file (path list)
        req_file = args.get("requirements-file")
        if req_file:
            # Handle single file as a list
            ns.requirements_file = [Path(req_file)]
        else:
            ns.requirements_file = []

        # Simple string/int/bool mappings
        ns.mode = args.get("mode", "index")
        ns.index_url = args.get("index-url", "https://libraries.cgr.dev/python/simple")
        ns.verbose = args.get("verbose", False)
        ns.workers = args.get("workers", 10)

        # Filter arguments
        ns.arch = args.get("arch")
        ns.python_version = args.get("python-version")
        ns.manylinux_variant = args.get("manylinux-variant")

        # Database arguments
        ns.database_url = args.get("database-url")
        ns.generation = args.get("generation")

        csv_path = args.get("csv")
        ns.csv = Path(csv_path) if csv_path else None

        # API arguments
        ns.issue = args.get("issue")
        ns.token = args.get("token")
        ns.api_url = args.get("api-url", "https://rebuilder-api-python.prod-eco.dev")
        ns.organization_id = args.get("organization-id")
        ns.environment = args.get("environment", "prod")
        ns.refresh = args.get("refresh", False)
        ns.force = args.get("force", False)

        return ns
