"""
XLSX generator for vulnerability cost analysis.

Generates comprehensive Excel cost analysis spreadsheets with ROI calculations,
CVE remediation cost estimates, and FIPS implementation cost analysis.
This format is designed for financial planning and business case development.
"""

import logging
from pathlib import Path

import xlsxwriter
from xlsxwriter.utility import xl_rowcol_to_cell

from forge_gauge.constants import (
    CHAINGUARD_IMAGE_COST,
    DEFAULT_HOURS_PER_VULNERABILITY,
    DEFAULT_HOURLY_RATE,
    DEFAULT_PLATFORM,
)
from forge_gauge.core.models import ScanResult
from forge_gauge.outputs.base import OutputGenerator
from forge_gauge.outputs.xlsx_formats import OutputFormatter
from forge_gauge.outputs.xlsx_writers import (
    ImageComparisonWriter,
    ROISectionWriter,
    CHPSSectionWriter,
    KEVSectionWriter,
    FIPSSectionWriter,
)

logger = logging.getLogger(__name__)


class XLSXGenerator(OutputGenerator):
    """
    Vulnerability cost analysis generator (XLSX format).

    Generates comprehensive financial analysis spreadsheets with:
    - Image comparison data with vulnerability counts
    - Roll-up metrics and summary statistics
    - CVE backlog remediation cost calculations
    - Projected future CVE cost estimates
    - Optional FIPS implementation cost analysis
    - ROI calculations and business case metrics

    This generator focuses on cost analysis and ROI calculations, not just
    vulnerability findings. For assessment summaries, use HTMLGenerator.
    """

    def supports_format(self) -> str:
        """Return format identifier."""
        return "xlsx"

    def generate(
        self,
        results: list[ScanResult],
        output_path: Path,
        config: "XLSXGeneratorConfig",
    ) -> None:
        """
        Generate vulnerability cost analysis report (XLSX).

        Args:
            results: Scan results for image pairs
            output_path: Output file path
            config: XLSX generator configuration
        """
        from core.exceptions import OutputException
        from outputs.config import XLSXGeneratorConfig

        # Validate config
        if not isinstance(config, XLSXGeneratorConfig):
            raise OutputException(
                "xlsx",
                f"Expected XLSXGeneratorConfig, got {type(config).__name__}"
            )

        config.validate()

        logger.info(f"Generating vulnerability cost analysis: {output_path}")

        # Filter successful scans
        successful = [r for r in results if r.scan_successful]
        if not successful:
            raise OutputException("xlsx", "No successful scan results to report")

        # Extract analyses
        alternative_analyses = [r.alternative_analysis for r in successful]
        chainguard_analyses = [r.chainguard_analysis for r in successful]

        # Auto-detect FIPS if requested
        fips_count = None
        if config.auto_detect_fips:
            fips_count = sum(
                1 for analysis in chainguard_analyses if "-fips" in analysis.name.lower()
            )
            if fips_count > 0:
                logger.info(f"Auto-detected {fips_count} FIPS images")
            else:
                fips_count = None

        # Create workbook
        workbook = xlsxwriter.Workbook(str(output_path))
        worksheet = workbook.add_worksheet("image-list")
        formatter = OutputFormatter(workbook)

        # Track current row
        row = 0

        # Image comparison section
        image_writer = ImageComparisonWriter(worksheet, formatter, row)
        alternative_cells, chainguard_cells, row = image_writer.write(
            alternative_analyses, chainguard_analyses, config.platform, config.include_negligible
        )

        # ROI sections
        roi_writer = ROISectionWriter(
            worksheet, formatter, row, config.hours_per_vuln, config.hourly_rate
        )
        backlog_cost_cell, yearly_cost_cell, row = roi_writer.write(successful, config.include_negligible)

        # FIPS sections
        fips_initial_cost_cell = None
        fips_yearly_cost_cell = None
        if fips_count and fips_count > 0:
            fips_writer = FIPSSectionWriter(
                worksheet, formatter, row, config.hourly_rate, roi_writer.hourly_rate_cell
            )
            fips_initial_cost_cell, fips_yearly_cost_cell, row = fips_writer.write(fips_count)

        # Final totals
        self._write_final_totals(
            worksheet,
            formatter,
            row,
            len(chainguard_analyses),
            fips_count or 0,
            backlog_cost_cell,
            yearly_cost_cell,
            fips_initial_cost_cell,
            fips_yearly_cost_cell,
        )

        # CHPS section if any images have CHPS scores (after final totals)
        if any(a.chps_score for a in alternative_analyses + chainguard_analyses):
            chps_writer = CHPSSectionWriter(worksheet, formatter, row)
            row = chps_writer.write(alternative_analyses, chainguard_analyses)

        # KEV section if KEV catalog is provided (after CHPS section)
        if config.kev_catalog:
            kev_writer = KEVSectionWriter(worksheet, formatter, row, config.kev_catalog)
            row = kev_writer.write(alternative_analyses, chainguard_analyses)

        # Finalize
        worksheet.autofit()
        workbook.close()

        logger.info(f"Vulnerability cost analysis generated: {output_path}")

    def _write_final_totals(
        self,
        worksheet: xlsxwriter.worksheet.Worksheet,
        formatter: OutputFormatter,
        row: int,
        num_images: int,
        fips_count: int,
        backlog_cost_cell: str,
        yearly_cost_cell: str,
        fips_initial_cost_cell: str = None,
        fips_yearly_cost_cell: str = None,
    ):
        """Write final cost comparison section."""
        row += 2

        # Header
        worksheet.write_row(
            row, 7, ["Hours", "Cost"], formatter.get("header_lightgrey")
        )
        row += 1

        # Total DIY cost
        if fips_count > 0:
            total_formula = f"={backlog_cost_cell} + {yearly_cost_cell} + {fips_initial_cost_cell} + {fips_yearly_cost_cell}"
            label = "Total (CVE backlog + next year + FIPS initial + next year)"
        else:
            total_formula = f"={backlog_cost_cell} + {yearly_cost_cell}"
            label = "Total (CVE backlog + next year)"

        worksheet.write_formula(
            row, 8, total_formula, formatter.get("body_green_money")
        )
        total_cost_cell = xl_rowcol_to_cell(row, 8)

        worksheet.write(row, 9, label, formatter.get("body_green"))
        row += 1

        # Chainguard cost
        cgr_cost = num_images * CHAINGUARD_IMAGE_COST
        worksheet.write(
            row, 8, cgr_cost, formatter.get("body_yellow_money")
        )
        cgr_cost_cell = xl_rowcol_to_cell(row, 8)

        worksheet.write(
            row, 9, "Cost of Chainguard Images", formatter.get("body_white")
        )
        row += 1

        # Total savings
        savings_formula = f"={total_cost_cell} - {cgr_cost_cell}"
        worksheet.write_formula(
            row, 8, savings_formula, formatter.get("body_white_money")
        )
        worksheet.write(
            row, 9, "Total Savings", formatter.get("header_white")
        )
        row += 1

        # Percent savings
        percent_formula = f"=(({total_cost_cell} - {cgr_cost_cell}) / {total_cost_cell})"
        worksheet.write_formula(
            row, 8, percent_formula, formatter.get("body_white_percent")
        )
        worksheet.write(
            row, 9, "Percent Savings", formatter.get("header_white")
        )
