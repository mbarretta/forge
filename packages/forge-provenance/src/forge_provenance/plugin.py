"""ToolPlugin implementation for verify-provenance."""

from __future__ import annotations

import csv
import logging
from io import StringIO
from pathlib import Path
from typing import Any

from forge_core.context import ExecutionContext
from forge_core.deps import assert_dependencies
from forge_core.plugin import ToolParam, ToolResult, ResultStatus

from forge_provenance.core import (
    __version__,
    REQUIRED_TOOLS,
    check_dependencies,
    get_image_list,
    verify_image,
    run_cmd,
)

logger = logging.getLogger(__name__)


class ProvenancePlugin:
    """FORGE plugin for verify-provenance - verify Chainguard image delivery authenticity."""

    name = "provenance"
    description = "Verify Chainguard image provenance and delivery authenticity"
    version = __version__

    def get_params(self) -> list[ToolParam]:
        """Declare parameters for verify-provenance."""
        return [
            ToolParam(
                name="customer-org",
                description="Customer organization to verify",
                required=True,
            ),
            ToolParam(
                name="full",
                description="Full verification mode (verify base digest in chainguard-private)",
                type="bool",
            ),
            ToolParam(
                name="verify-signatures",
                description="Enable full cryptographic signature verification",
                type="bool",
            ),
            ToolParam(
                name="limit",
                description="Limit number of images to check (0 = all)",
                type="int",
                default=0,
            ),
            ToolParam(
                name="output",
                description="Output CSV file path (default: print to stdout)",
            ),
        ]

    def run(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        """Execute provenance verification."""
        # Check external dependencies
        missing = check_dependencies()
        if missing:
            return ToolResult(
                status=ResultStatus.FAILURE,
                summary=f"Missing required tools: {', '.join(missing)}",
            )

        customer_org = args["customer_org"]  # argparse converts hyphens to underscores
        full_mode = args.get("full", False)
        verify_signatures = args.get("verify_signatures", False) or full_mode
        limit = args.get("limit", 0)
        output_file = args.get("output")

        registry = "cgr.dev"
        reference_org = "chainguard-private"
        customer_only = not full_mode

        # Check auth
        success, _, _ = run_cmd(["chainctl", "auth", "status"], timeout=10)
        if not success:
            return ToolResult(
                status=ResultStatus.FAILURE,
                summary="Not authenticated. Run 'chainctl auth login'",
            )

        # Get images
        ctx.progress(0.0, f"Fetching images for '{customer_org}'")
        images = get_image_list(customer_org)

        if not images:
            return ToolResult(
                status=ResultStatus.FAILURE,
                summary="Could not retrieve image list",
            )

        if limit > 0:
            images = images[:limit]

        ctx.progress(0.1, f"Verifying {len(images)} images")

        # Verify images
        results = []
        passed_count = 0
        failed_count = 0

        for i, image in enumerate(images):
            if ctx.is_cancelled:
                return ToolResult(
                    status=ResultStatus.CANCELLED,
                    summary="Cancelled by user",
                )

            ctx.progress(
                0.1 + 0.8 * (i / len(images)),
                f"Verifying {image} ({i+1}/{len(images)})",
            )

            result = verify_image(
                image=image,
                registry=registry,
                customer_org=customer_org,
                reference_org=reference_org,
                verify_signatures=verify_signatures,
                capture_details=True,
                customer_only=customer_only,
            )

            results.append(result)

            # Count successful verifications (DELIVERY_VERIFIED or VERIFIED)
            if result.status in ("DELIVERY_VERIFIED", "VERIFIED"):
                passed_count += 1
            else:
                failed_count += 1

        ctx.progress(0.9, "Generating report")

        # Generate CSV output
        csv_output = StringIO()
        writer = csv.writer(csv_output)

        # Write header
        writer.writerow([
            "Image",
            "Base Digest",
            "Reference Status",
            "Rekor Status",
            "Rekor Log Index",
            "Signature Status",
            "Overall Status",
            "Error",
        ])

        # Write results
        for result in results:
            writer.writerow([
                result.image,
                result.base_digest,
                result.ref_status,
                result.rekor_status,
                result.rekor_log_index,
                result.sig_status,
                result.status,
                result.error,
            ])

        csv_content = csv_output.getvalue()

        # Save to file if specified
        artifacts = {}
        if output_file:
            output_path = Path(output_file)
            output_path.write_text(csv_content)
            artifacts["report"] = str(output_path.resolve())

        ctx.progress(1.0, "Verification complete")

        # Determine overall status
        overall_status = ResultStatus.SUCCESS if failed_count == 0 else ResultStatus.PARTIAL

        return ToolResult(
            status=overall_status,
            summary=f"Verified {len(images)} images: {passed_count} passed, {failed_count} failed",
            data={
                "total": len(images),
                "passed": passed_count,
                "failed": failed_count,
                "results": [
                    {
                        "image": r.image,
                        "base_digest": r.base_digest,
                        "status": r.status,
                        "error": r.error,
                    }
                    for r in results
                ],
                "csv": csv_content if not output_file else None,
            },
            artifacts=artifacts,
        )
