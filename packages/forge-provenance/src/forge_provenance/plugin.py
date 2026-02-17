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
        from forge_provenance.core import print_chain_details

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

        # Print header (like original script)
        mode_desc = "DELIVERY VERIFICATION" if customer_only else "FULL VERIFICATION"
        title = f"Chainguard Image Provenance   {mode_desc}"
        print("╔══════════════════════════════════════════════════════════════════════════════╗")
        print(f"║{title:^78}║")
        print("╠══════════════════════════════════════════════════════════════════════════════╣")
        print(f"║  Customer Org:     {customer_org:<58}║")
        if not customer_only:
            print(f"║  Reference Org:    {reference_org:<58}║")
        print(f"║  Signature Verify: {str(verify_signatures):<58}║")
        print("╚══════════════════════════════════════════════════════════════════════════════╝")
        print()

        # Get images
        print(f"Fetching entitled images for '{customer_org}'...")
        images = get_image_list(customer_org)

        if not images:
            return ToolResult(
                status=ResultStatus.FAILURE,
                summary="Could not retrieve image list",
            )

        print(f"Found {len(images)} images")

        if limit > 0:
            images = images[:limit]
            print(f"Limited to first {limit} images")

        # Verify images with detailed output
        print("\nVerifying images...")
        results = []

        for i, image in enumerate(images, 1):
            if ctx.is_cancelled:
                return ToolResult(
                    status=ResultStatus.CANCELLED,
                    summary="Cancelled by user",
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

            # Print detailed chain output for each image (like original script)
            print_chain_details(result, i, customer_only=customer_only)

        # Sort by image name
        results.sort(key=lambda r: r.image)

        # Write CSV - match original script format
        csv_file = output_file or f"{customer_org}.csv"
        with open(csv_file, "w", newline="") as f:
            writer = csv.writer(f)
            if customer_only:
                writer.writerow([
                    "image", "base_digest", "rekor_status", "rekor_log_index",
                    "rekor_url", "signature_status", "verification_status", "error"
                ])
                for r in results:
                    rekor_url = r.chain.customer_rekor_url or ""
                    writer.writerow([
                        r.image, r.chain.base_digest_full, r.rekor_status,
                        r.chain.customer_rekor_index, rekor_url, r.sig_status,
                        r.status, r.error
                    ])
            else:
                writer.writerow([
                    "image", "base_digest", "reference_status", "rekor_status",
                    "rekor_log_index", "rekor_url", "signature_status",
                    "verification_status", "error"
                ])
                for r in results:
                    rekor_url = ""
                    if r.rekor_log_index:
                        rekor_url = f"https://search.sigstore.dev/?logIndex={r.rekor_log_index}"
                    writer.writerow([
                        r.image, r.chain.base_digest_full, r.ref_status, r.rekor_status,
                        r.rekor_log_index, rekor_url, r.sig_status, r.status, r.error
                    ])

        # Count results
        counts = {}
        for r in results:
            counts[r.status] = counts.get(r.status, 0) + 1

        # Print summary (like original script)
        print()
        print("═" * 80)
        print("  SUMMARY")
        print("═" * 80)
        print(f"  Customer Org:       {customer_org}")
        if not customer_only:
            print(f"  Reference Org:      {reference_org}")
        print(f"  Mode:               {'Delivery Verification' if customer_only else 'Full Verification'}")
        print(f"  Total Checked:      {len(results)}")
        print()

        if customer_only:
            print(f"  Delivery Verified:  {counts.get('DELIVERY_VERIFIED', 0)}  (signed by Chainguard + in Rekor)")
            print(f"  No Signature:       {counts.get('NO_SIG', 0)}")
            print(f"  Partial:            {counts.get('PARTIAL', 0)}")
            print(f"  No Base Digest:     {counts.get('NO_BASE', 0)}")
            print(f"  Errors:             {counts.get('ERROR', 0)}")
        else:
            print(f"  Verified:           {counts.get('VERIFIED', 0)}  (in reference + Rekor)")
            print(f"  Partial:            {counts.get('PARTIAL', 0)}   (in reference only)")
            print(f"  Not Found:          {counts.get('NOT_FOUND', 0)}")
            print(f"  No Base Digest:     {counts.get('NO_BASE', 0)}")
            print(f"  Errors:             {counts.get('ERROR', 0)}")

        print()
        print(f"  CSV Output:         {csv_file}")
        print("═" * 80)

        if customer_only:
            print("\n  NOTE: To compare images across customers, share the base_digest")
            print("        column from the CSV. Matching base_digest = same source image.")

        # Print warnings (like original script)
        if not customer_only and counts.get("NOT_FOUND", 0) > 0:
            print(f"\nWARNING: Some images not found in '{reference_org}'")

        if counts.get("PARTIAL", 0) > 0:
            print("\nWARNING: Some images have no Rekor entries")

        verified_count = counts.get("DELIVERY_VERIFIED", 0) if customer_only else counts.get("VERIFIED", 0)
        if verified_count == len(results) and len(results) > 0:
            print("\n✓ ALL IMAGES VERIFIED")

        # Determine overall status based on results
        overall_status = ResultStatus.SUCCESS if verified_count == len(results) else ResultStatus.PARTIAL

        return ToolResult(
            status=overall_status,
            summary=f"Verified {len(results)} images in '{customer_org}'",
            artifacts={"report": csv_file},
        )
