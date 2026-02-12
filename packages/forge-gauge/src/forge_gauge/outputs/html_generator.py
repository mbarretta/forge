"""
HTML generator for vulnerability assessment summaries.

Generates professional HTML assessment summary reports optimized for PDF conversion.
These reports provide an executive overview of vulnerability findings, comparing
Chainguard images against alternatives, with executive summaries and appendixes.
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import markdown

from forge_gauge.constants import GRADE_TO_CSS_CLASS
from forge_gauge.utils.paths import get_styles_path
from forge_gauge.core.models import ImageAnalysis, ScanResult
from forge_gauge.utils.formatting import format_number
from forge_gauge.utils.markdown_utils import load_and_convert_markdown
from forge_gauge.utils.metrics_calculator import MetricsCalculator

logger = logging.getLogger(__name__)

# Cached base64-encoded logo data URI
_logo_data_uri_cache: Optional[str] = None


def _get_logo_data_uri() -> str:
    """Get the Chainguard logo as a base64 data URI for embedding in HTML.

    The result is cached so the file is only read once per process.
    Falls back to an empty string if the logo file cannot be read.
    """
    global _logo_data_uri_cache
    if _logo_data_uri_cache is not None:
        return _logo_data_uri_cache

    import base64

    logo_path = Path(__file__).resolve().parent / "linky-white.png"
    try:
        logo_bytes = logo_path.read_bytes()
        encoded = base64.b64encode(logo_bytes).decode("ascii")
        _logo_data_uri_cache = f"data:image/png;base64,{encoded}"
    except Exception as e:
        logger.warning(f"Could not read logo file {logo_path}: {e}")
        _logo_data_uri_cache = ""

    return _logo_data_uri_cache


def _apply_template_variables(content: str, metrics: dict, customer_name: str) -> str:
    """
    Apply template variable substitution to content.

    Replaces {{variable_name}} placeholders with actual values.

    Args:
        content: Content string with template variables
        metrics: Dictionary containing metric values
        customer_name: Customer name for substitution

    Returns:
        Content with variables replaced
    """
    template_vars = {
        "customer_name": customer_name,
        "images_scanned": str(metrics["images_scanned"]),
        "total_customer_vulns": str(metrics["total_customer_vulns"]),
        "total_chainguard_vulns": str(metrics["total_chainguard_vulns"]),
        "reduction_percentage": f"{metrics['reduction_percentage']:.1f}%",
        "total_reduction": str(metrics["total_reduction"]),
        "images_with_reduction": str(metrics["images_with_reduction"]),
        "average_reduction_per_image": f"{metrics['average_reduction_per_image']:.1f}",
        # KEV-related variables (available when --with-kevs is used)
        "total_customer_kevs": str(metrics.get("total_customer_kevs", 0)),
        "total_chainguard_kevs": str(metrics.get("total_chainguard_kevs", 0)),
        "kev_reduction": str(metrics.get("kev_reduction", 0)),
        "images_with_customer_kevs": str(metrics.get("images_with_customer_kevs", 0)),
        "images_with_chainguard_kevs": str(
            metrics.get("images_with_chainguard_kevs", 0)
        ),
    }

    for key, value in template_vars.items():
        content = content.replace(f"{{{{{key}}}}}", value)

    return content


class HTMLGenerator:
    """
    Vulnerability assessment summary generator (HTML format).

    Generates professional Chainguard-branded assessment summaries matching
    the cg_assessment template with:
    - Executive summary (from markdown file)
    - CVE reduction metrics with large reduction percentage display
    - Side-by-side vulnerability count comparison
    - Images scanned table with vulnerability badges
    - CHPS scoring section (when available)
    - Custom appendix support
    - PDF-optimized styling
    """

    # Severity order for consistent display
    SEVERITY_ORDER = ["Critical", "High", "Medium", "Low", "Negligible"]

    def supports_format(self) -> str:
        """Return format identifier."""
        return "html"

    def generate(
        self,
        results: list[ScanResult],
        output_path: Path,
        config: "HTMLGeneratorConfig",
    ) -> None:
        """
        Generate vulnerability assessment summary report (HTML).

        Args:
            results: Scan results for image pairs
            output_path: Output file path
            config: HTML generator configuration
        """
        from forge_gauge.core.exceptions import OutputException
        from forge_gauge.outputs.config import HTMLGeneratorConfig

        # Validate config
        if not isinstance(config, HTMLGeneratorConfig):
            raise OutputException(
                "html", f"Expected HTMLGeneratorConfig, got {type(config).__name__}"
            )

        config.validate()

        logger.info(f"Generating vulnerability assessment summary: {output_path}")

        # Filter successful scans
        successful = [r for r in results if r.scan_successful]
        if not successful:
            raise OutputException("html", "No successful scan results to report")

        # Calculate metrics
        metrics = self._calculate_metrics(successful, config.include_negligible)

        # Load executive summary and appendix
        exec_summary = self._load_exec_summary(
            config.exec_summary_path, metrics, config.customer_name
        )
        appendix_content = self._load_appendix(
            config.appendix_path, metrics, config.customer_name
        )

        # Build image pairs for table
        image_pairs = []
        for result in successful:
            image_pairs.append(
                {
                    "customer": result.alternative_analysis,
                    "chainguard": result.chainguard_analysis,
                }
            )

        # Get CSS
        css_content = self._get_embedded_css()

        # Build HTML
        html_content = self._build_html_template(
            customer_name=config.customer_name,
            css_content=css_content,
            exec_summary=exec_summary,
            metrics=metrics,
            image_pairs=image_pairs,
            appendix_content=appendix_content,
            results=successful,
            platform=config.platform,
            kev_catalog=config.kev_catalog,
        )

        # Clean up chainguard image references
        html_content = re.sub(
            r"cgr\.dev/chainguard-private/([^<\s]+)", r"\1", html_content
        )
        html_content = re.sub(r"cgr\.dev/chainguard/([^<\s]+)", r"\1", html_content)
        html_content = re.sub(r"cgr\.dev/cg/([^<\s]+)", r"\1", html_content)

        # Write to file
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        logger.info(f"Vulnerability assessment summary generated: {output_path}")

    def _calculate_metrics(self, results: list[ScanResult], include_negligible: bool = False) -> dict:
        """Calculate CVE reduction metrics using MetricsCalculator."""
        return MetricsCalculator.calculate_metrics(results, include_negligible)

    def _build_html_template(
        self,
        customer_name: str,
        css_content: str,
        exec_summary: Optional[str],
        metrics: dict,
        image_pairs: list,
        appendix_content: Optional[str],
        results: list[ScanResult],
        platform: str = "linux/amd64",
        kev_catalog: Optional["KEVCatalog"] = None,
    ) -> str:
        """Build complete HTML document."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Build document sections
        header_section = self._build_header_section(platform)
        exec_summary_section = self._build_exec_summary_section(exec_summary)
        cve_reduction_section = self._build_cve_reduction_section(metrics)
        images_scanned_section = self._build_images_scanned_section(image_pairs)
        chps_section = self._build_chps_section_if_needed(results)
        kev_section = self._build_kev_section_if_needed(results, kev_catalog)
        footer_section = self._build_footer_section(
            customer_name, timestamp, appendix_content
        )

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Chainguard Vulnerability Report</title>
    <style>
{css_content}
    </style>
</head>
<body>
    <div class="container">
{header_section}
{exec_summary_section}
{cve_reduction_section}
{images_scanned_section}
{chps_section}
{kev_section}
{footer_section}
    </div>
</body>
</html>"""

    def _build_header_section(self, platform: str) -> str:
        """Build the header section of the HTML document."""
        logo_data_uri = _get_logo_data_uri()
        return f"""        <div class="header-section">
            <img class="header-logo" src="{logo_data_uri}" alt="Chainguard Logo">
            <h1>Vulnerability Comparison Report</h1>
            <p>A comprehensive analysis comparing vulnerabilities in your container images versus Chainguard's hardened alternatives. <em>(Platform: {platform})</em></p>
        </div>"""

    def _build_exec_summary_section(self, exec_summary: Optional[str]) -> str:
        """Build the executive summary section if content is provided."""
        if not exec_summary:
            return ""

        return f"""
        <!-- Executive Summary -->
        <div class="image-comparison-section no-break">
            <h2>Executive Summary</h2>
            {exec_summary}
        </div>"""

    def _build_cve_reduction_section(self, metrics: dict) -> str:
        """Build the CVE reduction analysis section."""
        return f"""
        <!-- CVE Reduction Metrics -->
        <div class="image-comparison-section no-break cve-reduction-section">
            <h2>CVE Reduction Analysis</h2>
            <div style="text-align: center; margin-bottom: 30px;">
                <div class="total-box reduction-box" style="display: block; margin: 0 auto 20px auto; width: 300px;">
                    {metrics["reduction_percentage"]}%
                    <span>CVE Reduction</span>
                </div>
                <p style="text-align: center; margin: 0; font-size: 16px; color: var(--cg-primary);"><strong>{format_number(metrics["total_reduction"])}</strong> fewer vulnerabilities with Chainguard images</p>
            </div>

            <!-- Overview Section within CVE Reduction Analysis -->
            <div class="overview-grid" style="margin-top: 40px;">
                <!-- Customer Images Column -->
                <div class="summary-column">
                    <div class="summary-column-content">
                        <h2>Your Images</h2>
                        <div class="total-box customer-total">
                            {format_number(metrics["total_customer_vulns"])}
                            <span>Total Vulnerabilities</span>
                        </div>
                        {self._generate_severity_table(metrics["alternative_summary"])}
                    </div>
                </div>

                <!-- Chainguard Images Column -->
                <div class="summary-column">
                    <div class="summary-column-content">
                        <h2>Chainguard Images</h2>
                        <div class="total-box chainguard-total">
                            {format_number(metrics["total_chainguard_vulns"])}
                            <span>Total Vulnerabilities</span>
                        </div>
                        {self._generate_severity_table(metrics["chainguard_summary"])}
                    </div>
                </div>
            </div>
        </div>"""

    def _generate_fallback_note(
        self, has_fallback: bool, margin_top: str = "20px"
    ) -> str:
        """
        Generate fallback note HTML if needed.

        Args:
            has_fallback: Whether any images used fallback
            margin_top: CSS margin-top value for the note

        Returns:
            HTML string for fallback note, or empty string if not needed
        """
        if not has_fallback:
            return ""

        return (
            f'<p style="margin-top: {margin_top}; font-size: 12px; color: #6b7280;">'
            '<span style="color: #7545fb; font-weight: bold;">*</span> '
            "Image was not built in the last 30 days; <code>:latest</code> tag was used for comparison."
            "</p>"
        )

    def _build_images_scanned_section(self, image_pairs: list) -> str:
        """Build the images scanned comparison table section."""
        # Check if any Chainguard images used fallback
        has_fallback = any(
            pair["chainguard"].used_latest_fallback for pair in image_pairs
        )
        fallback_note = self._generate_fallback_note(has_fallback, margin_top="20px")

        return f"""
        <!-- Image Comparison Table -->
        <div class="images-scanned-section">
            <h2>Images Scanned</h2>
            {self._generate_vulnerability_legend()}
            <div class="image-table-container">
                <table>
                    <thead>
                        <tr>
                            <th>Your Image</th>
                            <th>Total Vulnerabilities</th>
                            <th>Chainguard Image <span style="font-size: 0.8em; font-weight: normal;">(cgr.dev)</span></th>
                            <th>Total Vulnerabilities</th>
                        </tr>
                    </thead>
                    <tbody>
                        {self._generate_comparison_table_rows(image_pairs)}
                    </tbody>
                </table>
            </div>
            {fallback_note}
        </div>"""

    def _build_chps_section_if_needed(self, results: list[ScanResult]) -> str:
        """Build CHPS section if any results have CHPS scores."""
        has_chps = any(
            (r.chainguard_analysis and r.chainguard_analysis.chps_score)
            or (r.alternative_analysis and r.alternative_analysis.chps_score)
            for r in results
        )

        if has_chps:
            logger.info("CHPS scores detected, adding CHPS section to HTML report")
            return self._generate_chps_section(results)

        return ""

    def _build_footer_section(
        self, customer_name: str, timestamp: str, appendix_content: Optional[str]
    ) -> str:
        """Build the footer section, optionally with appendix."""
        footer_text = f"This report is {customer_name} & Chainguard Confidential | Generated on {timestamp}"

        if appendix_content:
            return f"""
        <!-- Appendix Section -->
        <div class="appendix-content">
            <h2>Appendix</h2>
            {appendix_content}

            <!-- Footer integrated within appendix container -->
            <div class="footer">
                <p>{footer_text}</p>
            </div>
        </div>"""
        else:
            return f"""
        <!-- Footer -->
        <div class="footer">
            <p>{footer_text}</p>
        </div>"""

    def _generate_severity_table(self, summary: dict) -> str:
        """Generate HTML for severity summary table."""
        rows = []
        for severity in self.SEVERITY_ORDER:
            count = summary.get(severity, 0)
            severity_lower = severity.lower()
            rows.append(f"""                                <tr>
                                    <td><span class="severity-indicator {severity_lower}"></span>{severity}</td>
                                    <td class="severity-count">{format_number(count)}</td>
                                </tr>""")

        return f"""<table class="summary-table">
                            <thead>
                                <tr>
                                    <th>Severity</th>
                                    <th>Count</th>
                                </tr>
                            </thead>
                            <tbody>
{chr(10).join(rows)}
                            </tbody>
                        </table>"""

    def _generate_comparison_table_rows(self, image_pairs: list) -> str:
        """Generate HTML table rows for image comparisons."""
        rows = []
        for pair in image_pairs:
            customer = pair["customer"]
            chainguard = pair["chainguard"]

            # Format vulnerability breakdowns with badges
            customer_breakdown = self._format_vulnerability_breakdown(customer)
            chainguard_breakdown = self._format_vulnerability_breakdown(chainguard)

            # Add asterisk if Chainguard image used fallback to :latest
            chainguard_name = chainguard.name
            if chainguard.used_latest_fallback:
                chainguard_name += (
                    ' <span style="color: #7545fb; font-weight: bold;">*</span>'
                )

            rows.append(f"""
                <tr class="image-comparison-row">
                    <td class="image-name-cell">
                        <code class="image-name">{customer.name}</code>
                    </td>
                    <td class="vulnerability-count">{customer_breakdown}</td>
                    <td class="image-name-cell">
                        <code class="image-name">{chainguard_name}</code>
                    </td>
                    <td class="vulnerability-count">{chainguard_breakdown}</td>
                </tr>
            """)
        return "".join(rows)

    # Severity levels in display order for badge generation
    SEVERITY_LEVELS = ["critical", "high", "medium", "low", "negligible"]

    def _format_vulnerability_breakdown(self, analysis: ImageAnalysis) -> str:
        """Format vulnerability count with severity breakdown badges."""
        if analysis.vulnerabilities.total == 0:
            return '<div class="vuln-breakdown-container"><span class="vuln-badge vuln-clean">Clean</span></div>'

        # Create badges for each severity with count > 0
        badges = [
            f'<span class="vuln-badge vuln-{sev}">{format_number(count)}</span>'
            for sev in self.SEVERITY_LEVELS
            if (count := getattr(analysis.vulnerabilities, sev, 0)) > 0
        ]

        # Add KEV badge if KEVs are present
        if hasattr(analysis, "kev_count") and analysis.kev_count > 0:
            badges.append(
                f'<span class="vuln-badge vuln-kev" title="{analysis.kev_count} Known Exploited Vulnerabilities">KEV:{analysis.kev_count}</span>'
            )

        if not badges:
            return '<div class="vuln-breakdown-container"><span class="vuln-badge vuln-clean">Clean</span></div>'

        return f'<div class="vuln-breakdown-container">{"".join(badges)}</div>'

    def _generate_vulnerability_legend(self) -> str:
        """Generate HTML for vulnerability severity color legend."""
        return """
            <div class="vulnerability-legend">
                <h3>Vulnerability Severity Legend</h3>
                <div class="legend-items">
                    <div class="legend-item">
                        <span class="vuln-badge vuln-critical legend-badge">C</span>
                        <span class="legend-label">Critical</span>
                    </div>
                    <div class="legend-item">
                        <span class="vuln-badge vuln-high legend-badge">H</span>
                        <span class="legend-label">High</span>
                    </div>
                    <div class="legend-item">
                        <span class="vuln-badge vuln-medium legend-badge">M</span>
                        <span class="legend-label">Medium</span>
                    </div>
                    <div class="legend-item">
                        <span class="vuln-badge vuln-low legend-badge">L</span>
                        <span class="legend-label">Low</span>
                    </div>
                    <div class="legend-item">
                        <span class="vuln-badge vuln-negligible legend-badge">N</span>
                        <span class="legend-label">Negligible</span>
                    </div>
                    <div class="legend-item">
                        <span class="vuln-badge vuln-clean legend-badge">Clean</span>
                        <span class="legend-label">No Vulnerabilities</span>
                    </div>
                    <div class="legend-item">
                        <span class="vuln-badge vuln-kev legend-badge">KEV</span>
                        <span class="legend-label">Known Exploited Vulnerability</span>
                    </div>
                </div>
            </div>
        """

    def _get_grade_badge_class(self, grade: str) -> str:
        """Get CSS class for CHPS grade badge."""
        grade_upper = grade.upper()
        return GRADE_TO_CSS_CLASS.get(grade_upper, "vuln-critical")

    def _format_chps_score_display(self, chps_score) -> str:
        """Format CHPS score for display with styled grade badge and component breakdown."""
        if not chps_score:
            return "N/A"

        # Get all score components from details
        scores = chps_score.details.get("scores", {})

        # Build component lines
        components = []
        component_order = ["minimalism", "provenance", "configuration"]
        component_labels = {
            "minimalism": "Minimalism",
            "provenance": "Provenance",
            "configuration": "Configuration",
        }

        for component in component_order:
            if component in scores:
                comp_data = scores[component]
                comp_grade = comp_data.get("grade", "F")
                # Fix E→F for components too
                if comp_grade == "E":
                    comp_grade = "F"
                grade_class = self._get_grade_badge_class(comp_grade)
                components.append(
                    f'<div style="display: flex; justify-content: space-between; align-items: center;">'
                    f"<span>{component_labels[component]}:</span>"
                    f'<span class="vuln-badge {grade_class}">{comp_grade}</span>'
                    f"</div>"
                )

        # Build the overall grade (larger)
        overall_grade_class = self._get_grade_badge_class(chps_score.grade)
        # Overall uses chps-overall-badge (not vuln-badge)
        overall_classes = f"chps-overall-badge {overall_grade_class}"
        overall = (
            f'<div style="display: flex; justify-content: space-between; align-items: center; margin-top: 8px;">'
            f"<strong>Overall:</strong>"
            f'<span class="{overall_classes}" style="font-size: 1.2em; padding: 4px 6px;">{chps_score.grade}</span>'
            f"</div>"
        )

        # Combine all components
        return "".join(components) + overall

    def _generate_chps_section(self, results: list[ScanResult]) -> str:
        """Generate CHPS scoring section."""
        rows = []
        has_fallback = False
        for result in results:
            alternative = result.alternative_analysis
            chainguard = result.chainguard_analysis

            # Format CHPS displays for both images
            alternative_score = (
                alternative.chps_score
                if alternative and alternative.chps_score
                else None
            )
            alternative_display = self._format_chps_score_display(alternative_score)

            chainguard_score = (
                chainguard.chps_score if chainguard and chainguard.chps_score else None
            )
            chainguard_display = self._format_chps_score_display(chainguard_score)

            # Add asterisk if Chainguard image used fallback to :latest
            chainguard_name = chainguard.name if chainguard else "N/A"
            if chainguard and chainguard.used_latest_fallback:
                chainguard_name += (
                    ' <span style="color: #7545fb; font-weight: bold;">*</span>'
                )
                has_fallback = True

            # Build single row with image pair
            rows.append(f"""
                <tr class="image-comparison-row">
                    <td class="image-name-cell">
                        <code class="image-name">{alternative.name if alternative else "N/A"}</code>
                    </td>
                    <td class="vulnerability-count">{alternative_display}</td>
                    <td class="image-name-cell">
                        <code class="image-name">{chainguard_name}</code>
                    </td>
                    <td class="vulnerability-count">{chainguard_display}</td>
                </tr>
            """)

        fallback_note = self._generate_fallback_note(has_fallback, margin_top="10px")

        return f"""
        <!-- CHPS Scoring Section -->
        <div class="images-scanned-section">
            <h2>CHPS Hardening & Provenance Scores</h2>
            <p>CHPS (Container Hardening and Provenance Scanner) evaluates container images for security hardening and provenance best practices. Grades range from A+ (best) to F (worst).</p>
            <div class="image-table-container">
                <table>
                    <thead>
                        <tr>
                            <th>Your Image</th>
                            <th>CHPS Grade</th>
                            <th>Chainguard Image <span style="font-size: 0.8em; font-weight: normal;">(cgr.dev)</span></th>
                            <th>CHPS Grade</th>
                        </tr>
                    </thead>
                    <tbody>
                        {"".join(rows)}
                    </tbody>
                </table>
            </div>
            {fallback_note}
            <p><em>Note: CHPS scoring evaluates non-CVE security factors including provenance, SBOM quality, signing, and container hardening practices.</em></p>
        </div>
"""

    def _build_kev_section_if_needed(
        self, results: list[ScanResult], kev_catalog: Optional["KEVCatalog"]
    ) -> str:
        """Build KEV section if KEV catalog is provided (always shows table when --with-kevs is used)."""
        if not kev_catalog:
            return ""

        # Always generate the section when kev_catalog is provided (--with-kevs was used)
        logger.info("KEV checking enabled, adding KEV section to HTML report")
        return self._generate_kev_section(results, kev_catalog)

    def _generate_kev_section(
        self, results: list[ScanResult], kev_catalog: "KEVCatalog"
    ) -> str:
        """Generate KEV details section with table of all found KEVs."""
        rows = []

        for result in results:
            # Check alternative/customer image
            alt_analysis = result.alternative_analysis
            if alt_analysis and getattr(alt_analysis, "kev_cves", []):
                for cve_id in alt_analysis.kev_cves:
                    kev_entry = kev_catalog.get_kev_entry(cve_id)
                    if kev_entry:
                        cve_url = f"https://www.cve.org/CVERecord?id={cve_id}"
                        kev_url = f"https://www.cisa.gov/known-exploited-vulnerabilities-catalog?search_api_fulltext={cve_id}"
                        rows.append(f"""
                <tr>
                    <td class="image-name-cell"><code class="image-name">{alt_analysis.name}</code></td>
                    <td><a href="{cve_url}" target="_blank" class="kev-link">{cve_id}</a></td>
                    <td><a href="{kev_url}" target="_blank" class="kev-link">{kev_entry.vulnerability_name}</a></td>
                    <td>{kev_entry.vendor}</td>
                    <td>{kev_entry.product}</td>
                    <td>{kev_entry.date_added}</td>
                </tr>
                        """)

            # Check Chainguard image
            cg_analysis = result.chainguard_analysis
            if cg_analysis and getattr(cg_analysis, "kev_cves", []):
                for cve_id in cg_analysis.kev_cves:
                    kev_entry = kev_catalog.get_kev_entry(cve_id)
                    if kev_entry:
                        cve_url = f"https://www.cve.org/CVERecord?id={cve_id}"
                        kev_url = f"https://www.cisa.gov/known-exploited-vulnerabilities-catalog?search_api_fulltext={cve_id}"
                        rows.append(f"""
                <tr>
                    <td class="image-name-cell"><code class="image-name">{cg_analysis.name}</code></td>
                    <td><a href="{cve_url}" target="_blank" class="kev-link">{cve_id}</a></td>
                    <td><a href="{kev_url}" target="_blank" class="kev-link">{kev_entry.vulnerability_name}</a></td>
                    <td>{kev_entry.vendor}</td>
                    <td>{kev_entry.product}</td>
                    <td>{kev_entry.date_added}</td>
                </tr>
                        """)

        # If no KEVs found, show a positive message
        if not rows:
            table_body = """
                        <tr>
                            <td colspan="6" style="text-align: center; padding: 20px; color: #059669; font-weight: 600;">
                                ✓ No Known Exploited Vulnerabilities found in scanned images
                            </td>
                        </tr>
"""
        else:
            table_body = "".join(rows)

        return f"""
        <!-- KEV Details Section -->
        <div class="images-scanned-section">
            <h2>Known Exploited Vulnerabilities (KEV)</h2>
            <p>The following CVEs are listed in CISA's Known Exploited Vulnerabilities catalog, indicating they are actively being exploited in the wild.</p>
            <div class="image-table-container kev-table">
                <table>
                    <thead>
                        <tr>
                            <th>Image</th>
                            <th>CVE ID</th>
                            <th>Vulnerability Name</th>
                            <th>Vendor</th>
                            <th>Product</th>
                            <th>Date Added</th>
                        </tr>
                    </thead>
                    <tbody>
                        {table_body}
                    </tbody>
                </table>
            </div>
            <p><em>Source: <a href="https://www.cisa.gov/known-exploited-vulnerabilities-catalog" target="_blank">CISA Known Exploited Vulnerabilities Catalog</a></em></p>
        </div>
"""

    def _load_exec_summary(
        self, path: Optional[Path], metrics: dict, customer_name: str
    ) -> Optional[str]:
        """Load and format executive summary with template variable substitution."""
        return load_and_convert_markdown(
            path,
            section_name="executive summary",
            template_processor=lambda content: _apply_template_variables(
                content, metrics, customer_name
            ),
        )

    def _load_appendix(
        self, path: Optional[Path], metrics: dict, customer_name: str
    ) -> Optional[str]:
        """Load and format appendix with template variable substitution."""
        return load_and_convert_markdown(
            path,
            section_name="appendix",
            template_processor=lambda content: _apply_template_variables(
                content, metrics, customer_name
            ),
        )

    def _get_embedded_css(self) -> str:
        """Return embedded CSS content loaded from external file."""
        return load_embedded_css()


def load_embedded_css() -> str:
    """Load the shared CSS stylesheet content.

    Resolves the styles.css path via get_styles_path().

    Returns:
        CSS content as string, or empty string on error.
    """
    css_path = get_styles_path()
    try:
        with open(css_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        logger.error(f"CSS file not found: {css_path}")
        return ""
    except Exception as e:
        logger.error(f"Error loading CSS file: {e}")
        return ""
