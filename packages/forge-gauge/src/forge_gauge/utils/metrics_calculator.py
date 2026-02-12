"""
Metrics calculator for vulnerability assessment reports.

Calculates CVE reduction metrics, KEV statistics, and severity summaries
from scan results.
"""

from typing import Any

from forge_gauge.core.models import ScanResult


class MetricsCalculator:
    """Calculates metrics from vulnerability scan results."""

    SEVERITY_ORDER = ["Critical", "High", "Medium", "Low", "Negligible"]

    @staticmethod
    def calculate_metrics(results: list[ScanResult], include_negligible: bool = False) -> dict[str, Any]:
        """
        Calculate comprehensive vulnerability reduction metrics.

        Args:
            results: List of ScanResult objects from image comparisons
            include_negligible: Whether to include Negligible/Unknown CVEs in counts (default: False)

        Returns:
            Dictionary containing:
            - total_customer_vulns: Total CVEs in customer images
            - total_chainguard_vulns: Total CVEs in Chainguard images
            - total_reduction: Absolute CVE reduction
            - reduction_percentage: Percentage reduction
            - images_scanned: Number of image pairs scanned
            - images_with_reduction: Count of images with CVE reduction
            - average_reduction_per_image: Average CVEs reduced per image
            - alternative_summary: Per-severity counts for customer images
            - chainguard_summary: Per-severity counts for Chainguard images
            - total_customer_kevs: KEV count in customer images
            - total_chainguard_kevs: KEV count in Chainguard images
            - kev_reduction: KEV reduction count
            - images_with_customer_kevs: Images with KEVs in customer version
            - images_with_chainguard_kevs: Images with KEVs in Chainguard version
        """
        # Total vulnerability counts
        total_customer_vulns = sum(
            r.alternative_analysis.vulnerabilities.get_total(include_negligible) for r in results
        )
        total_cgr_vulns = sum(
            r.chainguard_analysis.vulnerabilities.get_total(include_negligible) for r in results
        )
        total_reduction = total_customer_vulns - total_cgr_vulns

        # Reduction percentage
        reduction_percentage = 0.0
        if total_customer_vulns > 0:
            reduction_percentage = (total_reduction / total_customer_vulns) * 100

        # Count images with reduction
        images_with_reduction = sum(
            1
            for r in results
            if r.chainguard_analysis.vulnerabilities.get_total(include_negligible)
            < r.alternative_analysis.vulnerabilities.get_total(include_negligible)
        )

        # Average reduction per image
        images_scanned = len(results)
        average_reduction_per_image = (
            total_reduction / images_scanned if images_scanned > 0 else 0.0
        )

        # Per-severity summary
        alternative_summary = {
            severity: 0 for severity in MetricsCalculator.SEVERITY_ORDER
        }
        chainguard_summary = {
            severity: 0 for severity in MetricsCalculator.SEVERITY_ORDER
        }

        for result in results:
            alternative = result.alternative_analysis
            chainguard = result.chainguard_analysis

            alternative_summary["Critical"] += alternative.vulnerabilities.critical
            alternative_summary["High"] += alternative.vulnerabilities.high
            alternative_summary["Medium"] += alternative.vulnerabilities.medium
            alternative_summary["Low"] += alternative.vulnerabilities.low
            alternative_summary["Negligible"] += alternative.vulnerabilities.negligible

            chainguard_summary["Critical"] += chainguard.vulnerabilities.critical
            chainguard_summary["High"] += chainguard.vulnerabilities.high
            chainguard_summary["Medium"] += chainguard.vulnerabilities.medium
            chainguard_summary["Low"] += chainguard.vulnerabilities.low
            chainguard_summary["Negligible"] += chainguard.vulnerabilities.negligible

        # KEV metrics (if available)
        total_customer_kevs = sum(
            r.alternative_analysis.kev_count for r in results
        )
        total_chainguard_kevs = sum(
            r.chainguard_analysis.kev_count for r in results
        )
        kev_reduction = total_customer_kevs - total_chainguard_kevs

        # Count images with KEVs
        images_with_customer_kevs = sum(
            1 for r in results if r.alternative_analysis.kev_count > 0
        )
        images_with_chainguard_kevs = sum(
            1 for r in results if r.chainguard_analysis.kev_count > 0
        )

        return {
            "total_customer_vulns": total_customer_vulns,
            "total_chainguard_vulns": total_cgr_vulns,
            "total_reduction": total_reduction,
            "reduction_percentage": round(reduction_percentage, 2),
            "images_scanned": images_scanned,
            "images_with_reduction": images_with_reduction,
            "average_reduction_per_image": round(average_reduction_per_image, 1),
            "alternative_summary": alternative_summary,
            "chainguard_summary": chainguard_summary,
            "total_customer_kevs": total_customer_kevs,
            "total_chainguard_kevs": total_chainguard_kevs,
            "kev_reduction": kev_reduction,
            "images_with_customer_kevs": images_with_customer_kevs,
            "images_with_chainguard_kevs": images_with_chainguard_kevs,
        }
