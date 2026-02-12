"""
Tests for ROICalculator - ROI calculations for vulnerability remediation.

Verifies cost calculations for CVE backlog, ongoing costs, and savings.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import patch

from forge_gauge.core.models import ImageAnalysis, VulnerabilityCount
from forge_gauge.utils.roi_calculator import ROICalculator, ROIMetrics
from forge_gauge.constants import DEFAULT_HOURS_PER_VULNERABILITY, DEFAULT_HOURLY_RATE


@pytest.fixture
def calculator():
    """ROI calculator with default rates."""
    return ROICalculator()


@pytest.fixture
def custom_calculator():
    """ROI calculator with custom rates."""
    return ROICalculator(hours_per_vulnerability=5.0, hourly_rate=150.0)


@pytest.fixture
def sample_analysis():
    """Sample ImageAnalysis for testing."""
    return ImageAnalysis(
        name="python:3.12",
        size_mb=950.0,
        package_count=427,
        vulnerabilities=VulnerabilityCount(
            total=100,
            critical=5,
            high=20,
            medium=40,
            low=25,
            negligible=10,
        ),
        scan_timestamp=datetime.now(timezone.utc),
        digest="sha256:abc123",
    )


@pytest.fixture
def sample_analysis_small():
    """Sample ImageAnalysis with fewer vulnerabilities."""
    return ImageAnalysis(
        name="nginx:1.25",
        size_mb=150.0,
        package_count=100,
        vulnerabilities=VulnerabilityCount(
            total=20,
            critical=1,
            high=4,
            medium=8,
            low=5,
            negligible=2,
        ),
        scan_timestamp=datetime.now(timezone.utc),
        digest="sha256:def456",
    )


@pytest.fixture
def zero_vuln_analysis():
    """ImageAnalysis with zero vulnerabilities."""
    return ImageAnalysis(
        name="cgr.dev/chainguard/python:latest",
        size_mb=45.0,
        package_count=35,
        vulnerabilities=VulnerabilityCount(
            total=0,
            critical=0,
            high=0,
            medium=0,
            low=0,
            negligible=0,
        ),
        scan_timestamp=datetime.now(timezone.utc),
        digest="sha256:ghi789",
    )


# Mock CVE ratios for predictable testing
MOCK_CVE_RATIOS = {
    "CRITICAL": 0.1,
    "HIGH": 0.1,
    "MEDIUM": 0.1,
    "LOW": 0.1,
    "NEGLIGIBLE": 0.1,
}


class TestCalculateBacklogCost:
    """Tests for backlog cost calculation."""

    def test_calculate_backlog_cost(self, calculator, sample_analysis):
        """Basic backlog calculation."""
        hours, cost = calculator.calculate_backlog_cost([sample_analysis])

        # 100 CVEs * 3.0 hours = 300 hours
        assert hours == 300.0
        # 300 hours * $100/hour = $30,000
        assert cost == 30000.0

    def test_calculate_backlog_cost_multiple_images(
        self, calculator, sample_analysis, sample_analysis_small
    ):
        """Backlog calculation with multiple images."""
        hours, cost = calculator.calculate_backlog_cost(
            [sample_analysis, sample_analysis_small]
        )

        # (100 + 20) CVEs * 3.0 hours = 360 hours
        assert hours == 360.0
        # 360 hours * $100/hour = $36,000
        assert cost == 36000.0

    def test_calculate_backlog_cost_empty(self, calculator):
        """Empty analysis list returns zero."""
        hours, cost = calculator.calculate_backlog_cost([])

        assert hours == 0.0
        assert cost == 0.0

    def test_calculate_backlog_cost_zero_vulns(self, calculator, zero_vuln_analysis):
        """Zero vulnerability image returns zero cost."""
        hours, cost = calculator.calculate_backlog_cost([zero_vuln_analysis])

        assert hours == 0.0
        assert cost == 0.0


class TestEstimateMonthlyNewCves:
    """Tests for monthly CVE estimation."""

    @patch("utils.roi_calculator.get_cve_monthly_ratios")
    def test_estimate_monthly_new_cves(self, mock_ratios, calculator, sample_analysis):
        """Per-image monthly CVE estimate."""
        mock_ratios.return_value = MOCK_CVE_RATIOS

        monthly_cves = calculator.estimate_monthly_new_cves(sample_analysis)

        # (5 + 20 + 40 + 25 + 10) * 0.1 = 10 new CVEs per month
        assert monthly_cves == 10.0

    @patch("utils.roi_calculator.get_cve_monthly_ratios")
    def test_estimate_monthly_new_cves_zero_vulns(
        self, mock_ratios, calculator, zero_vuln_analysis
    ):
        """Zero vulns means zero monthly estimate."""
        mock_ratios.return_value = MOCK_CVE_RATIOS

        monthly_cves = calculator.estimate_monthly_new_cves(zero_vuln_analysis)

        assert monthly_cves == 0.0


class TestCalculateOngoingCost:
    """Tests for ongoing cost calculations."""

    @patch("utils.roi_calculator.get_cve_monthly_ratios")
    def test_calculate_ongoing_cost(self, mock_ratios, calculator, sample_analysis):
        """Monthly/yearly projections."""
        mock_ratios.return_value = MOCK_CVE_RATIOS

        monthly_hours, monthly_cost, yearly_hours, yearly_cost = (
            calculator.calculate_ongoing_cost([sample_analysis])
        )

        # 10 CVEs/month * 3.0 hours = 30 hours/month
        assert monthly_hours == 30.0
        # 30 hours * $100 = $3,000/month
        assert monthly_cost == 3000.0
        # 30 hours * 12 = 360 hours/year
        assert yearly_hours == 360.0
        # $3,000 * 12 = $36,000/year
        assert yearly_cost == 36000.0

    @patch("utils.roi_calculator.get_cve_monthly_ratios")
    def test_calculate_ongoing_cost_multiple_images(
        self, mock_ratios, calculator, sample_analysis, sample_analysis_small
    ):
        """Ongoing cost with multiple images."""
        mock_ratios.return_value = MOCK_CVE_RATIOS

        monthly_hours, monthly_cost, yearly_hours, yearly_cost = (
            calculator.calculate_ongoing_cost([sample_analysis, sample_analysis_small])
        )

        # (10 + 2) CVEs/month * 3.0 hours = 36 hours/month
        assert monthly_hours == 36.0
        assert monthly_cost == 3600.0
        assert yearly_hours == 432.0
        assert yearly_cost == 43200.0


class TestCalculateFullRoi:
    """Tests for complete ROI calculation."""

    @patch("utils.roi_calculator.get_cve_monthly_ratios")
    def test_calculate_full_roi(self, mock_ratios, calculator, sample_analysis):
        """Complete ROI metrics."""
        mock_ratios.return_value = MOCK_CVE_RATIOS

        roi = calculator.calculate_full_roi([sample_analysis])

        assert isinstance(roi, ROIMetrics)
        # Backlog: 100 * 3 = 300 hours, $30,000
        assert roi.backlog_hours == 300.0
        assert roi.backlog_cost == 30000.0
        # Monthly: 10 * 3 = 30 hours, $3,000
        assert roi.monthly_hours == 30.0
        assert roi.monthly_cost == 3000.0
        # Yearly: 30 * 12 = 360 hours, $36,000
        assert roi.yearly_hours == 360.0
        assert roi.yearly_cost == 36000.0
        # Total: backlog + yearly = $66,000
        assert roi.total_cost == 66000.0

    @patch("utils.roi_calculator.get_cve_monthly_ratios")
    def test_calculate_full_roi_empty(self, mock_ratios, calculator):
        """ROI with empty list."""
        mock_ratios.return_value = MOCK_CVE_RATIOS

        roi = calculator.calculate_full_roi([])

        assert roi.backlog_hours == 0.0
        assert roi.backlog_cost == 0.0
        assert roi.total_cost == 0.0


class TestCalculateSavings:
    """Tests for savings calculations."""

    def test_calculate_savings_positive(self, calculator):
        """Savings when CGR cheaper."""
        # $100,000 DIY vs $29,000 per image * 2 images = $58,000
        absolute, percent = calculator.calculate_savings(
            alternative_cost=100000.0,
            chainguard_image_cost=29000.0,
            num_images=2,
        )

        assert absolute == 42000.0  # $100,000 - $58,000
        assert percent == 42.0  # 42% savings

    def test_calculate_savings_negative(self, calculator):
        """Negative savings when CGR more expensive."""
        # $50,000 DIY vs $29,000 * 2 = $58,000
        absolute, percent = calculator.calculate_savings(
            alternative_cost=50000.0,
            chainguard_image_cost=29000.0,
            num_images=2,
        )

        assert absolute == -8000.0  # $50,000 - $58,000
        assert percent == -16.0  # -16% (costs more)

    def test_calculate_savings_zero_alternative(self, calculator):
        """Division by zero protection."""
        absolute, percent = calculator.calculate_savings(
            alternative_cost=0.0,
            chainguard_image_cost=29000.0,
            num_images=2,
        )

        assert absolute == -58000.0
        assert percent == 0.0  # Protected from division by zero

    def test_calculate_savings_zero_images(self, calculator):
        """Zero images means zero CGR cost."""
        absolute, percent = calculator.calculate_savings(
            alternative_cost=100000.0,
            chainguard_image_cost=29000.0,
            num_images=0,
        )

        assert absolute == 100000.0  # Full savings
        assert percent == 100.0


class TestCustomRates:
    """Tests for custom rate configuration."""

    def test_custom_rates_backlog(self, custom_calculator, sample_analysis):
        """Custom hours_per_vuln and hourly_rate."""
        hours, cost = custom_calculator.calculate_backlog_cost([sample_analysis])

        # 100 CVEs * 5.0 hours = 500 hours
        assert hours == 500.0
        # 500 hours * $150/hour = $75,000
        assert cost == 75000.0

    @patch("utils.roi_calculator.get_cve_monthly_ratios")
    def test_custom_rates_ongoing(self, mock_ratios, custom_calculator, sample_analysis):
        """Custom rates apply to ongoing costs."""
        mock_ratios.return_value = MOCK_CVE_RATIOS

        monthly_hours, monthly_cost, yearly_hours, yearly_cost = (
            custom_calculator.calculate_ongoing_cost([sample_analysis])
        )

        # 10 CVEs/month * 5.0 hours = 50 hours/month
        assert monthly_hours == 50.0
        # 50 hours * $150 = $7,500/month
        assert monthly_cost == 7500.0

    def test_default_rates(self, calculator):
        """Verify default rates match constants."""
        assert calculator.hours_per_vuln == DEFAULT_HOURS_PER_VULNERABILITY
        assert calculator.hourly_rate == DEFAULT_HOURLY_RATE


class TestROIMetricsDataclass:
    """Tests for ROIMetrics dataclass."""

    def test_roi_metrics_creation(self):
        """ROIMetrics can be created with all fields."""
        metrics = ROIMetrics(
            backlog_hours=100.0,
            backlog_cost=10000.0,
            monthly_hours=10.0,
            monthly_cost=1000.0,
            yearly_hours=120.0,
            yearly_cost=12000.0,
            total_cost=22000.0,
        )

        assert metrics.backlog_hours == 100.0
        assert metrics.total_cost == 22000.0
