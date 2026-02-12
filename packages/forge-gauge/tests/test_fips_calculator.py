"""
Tests for FIPSCalculator - FIPS compliance cost calculations.

Verifies cost calculations for initial FIPS implementation and ongoing maintenance.
"""

import pytest

from forge_gauge.utils.fips_calculator import FIPSCalculator, FIPSCosts, FIPSPhase
from forge_gauge.constants import DEFAULT_HOURLY_RATE


@pytest.fixture
def calculator():
    """FIPS calculator with default rates."""
    return FIPSCalculator()


@pytest.fixture
def custom_calculator():
    """FIPS calculator with custom hourly rate."""
    return FIPSCalculator(hourly_rate=150.0)


class TestFIPSPhase:
    """Tests for FIPSPhase dataclass."""

    def test_fips_phase_hours_saved_min(self):
        """Minimum hours saved calculation."""
        phase = FIPSPhase(
            name="Test Phase",
            before_min_hours=10.0,
            before_max_hours=20.0,
            after_min_hours=2.0,
            after_max_hours=4.0,
        )

        # 10 - 2 = 8 hours saved (minimum)
        assert phase.hours_saved_min == 8.0

    def test_fips_phase_hours_saved_max(self):
        """Maximum hours saved calculation."""
        phase = FIPSPhase(
            name="Test Phase",
            before_min_hours=10.0,
            before_max_hours=20.0,
            after_min_hours=2.0,
            after_max_hours=4.0,
        )

        # 20 - 4 = 16 hours saved (maximum)
        assert phase.hours_saved_max == 16.0

    def test_fips_phase_hours_saved_avg(self):
        """Average hours saved calculation."""
        phase = FIPSPhase(
            name="Test Phase",
            before_min_hours=10.0,
            before_max_hours=20.0,
            after_min_hours=2.0,
            after_max_hours=4.0,
        )

        # (8 + 16) / 2 = 12 hours saved (average)
        assert phase.hours_saved_avg == 12.0

    def test_fips_phase_zero_after_hours(self):
        """Phase where Chainguard eliminates all work."""
        phase = FIPSPhase(
            name="Eliminated Phase",
            before_min_hours=8.0,
            before_max_hours=16.0,
            after_min_hours=0.0,
            after_max_hours=0.0,
        )

        assert phase.hours_saved_min == 8.0
        assert phase.hours_saved_max == 16.0
        assert phase.hours_saved_avg == 12.0


class TestCalculateInitialImplementation:
    """Tests for initial FIPS implementation cost calculation."""

    def test_calculate_initial_implementation(self, calculator):
        """Initial cost calculation for one image."""
        hours, cost = calculator.calculate_initial_implementation(num_fips_images=1)

        # Should be positive values based on phase calculations
        assert hours > 0
        assert cost > 0
        # Cost should be hours * default rate
        assert cost == hours * DEFAULT_HOURLY_RATE

    def test_calculate_initial_implementation_multiple(self, calculator):
        """Initial cost scales with number of images."""
        hours_1, cost_1 = calculator.calculate_initial_implementation(num_fips_images=1)
        hours_3, cost_3 = calculator.calculate_initial_implementation(num_fips_images=3)

        assert hours_3 == hours_1 * 3
        assert cost_3 == cost_1 * 3

    def test_calculate_initial_zero_images(self, calculator):
        """Zero images returns zero cost."""
        hours, cost = calculator.calculate_initial_implementation(num_fips_images=0)

        assert hours == 0.0
        assert cost == 0.0

    def test_calculate_initial_uses_avg_hours(self, calculator):
        """Verify calculation uses average hours saved from phases."""
        # Calculate expected total from phases
        expected_hours_per_image = sum(
            phase.hours_saved_avg for phase in FIPSCalculator.INITIAL_PHASES
        )

        hours, _ = calculator.calculate_initial_implementation(num_fips_images=1)

        assert hours == expected_hours_per_image


class TestCalculateMonthlyMaintenance:
    """Tests for monthly FIPS maintenance cost calculation."""

    def test_calculate_monthly_maintenance(self, calculator):
        """Monthly maintenance costs for one image."""
        hours, cost = calculator.calculate_monthly_maintenance(num_fips_images=1)

        assert hours > 0
        assert cost > 0
        assert cost == hours * DEFAULT_HOURLY_RATE

    def test_calculate_monthly_maintenance_multiple(self, calculator):
        """Monthly maintenance scales with number of images."""
        hours_1, cost_1 = calculator.calculate_monthly_maintenance(num_fips_images=1)
        hours_5, cost_5 = calculator.calculate_monthly_maintenance(num_fips_images=5)

        assert hours_5 == hours_1 * 5
        assert cost_5 == cost_1 * 5

    def test_calculate_monthly_zero_images(self, calculator):
        """Zero images returns zero maintenance cost."""
        hours, cost = calculator.calculate_monthly_maintenance(num_fips_images=0)

        assert hours == 0.0
        assert cost == 0.0

    def test_calculate_monthly_uses_maintenance_phases(self, calculator):
        """Verify calculation uses maintenance phases."""
        expected_hours_per_image = sum(
            phase.hours_saved_avg for phase in FIPSCalculator.MAINTENANCE_PHASES
        )

        hours, _ = calculator.calculate_monthly_maintenance(num_fips_images=1)

        assert hours == expected_hours_per_image


class TestCalculateFullFipsCost:
    """Tests for complete FIPS cost calculation."""

    def test_calculate_full_fips_cost(self, calculator):
        """Complete FIPS costs include initial and ongoing."""
        costs = calculator.calculate_full_fips_cost(num_fips_images=1)

        assert isinstance(costs, FIPSCosts)
        assert costs.initial_hours > 0
        assert costs.initial_cost > 0
        assert costs.monthly_hours > 0
        assert costs.monthly_cost > 0
        assert costs.yearly_hours == costs.monthly_hours * 12
        assert costs.yearly_cost == costs.monthly_cost * 12
        assert costs.total_cost == costs.initial_cost + costs.yearly_cost

    def test_calculate_full_fips_cost_multiple(self, calculator):
        """Full FIPS costs scale with images."""
        costs_1 = calculator.calculate_full_fips_cost(num_fips_images=1)
        costs_3 = calculator.calculate_full_fips_cost(num_fips_images=3)

        assert costs_3.initial_hours == costs_1.initial_hours * 3
        assert costs_3.monthly_hours == costs_1.monthly_hours * 3
        assert costs_3.total_cost == costs_1.total_cost * 3

    def test_calculate_full_fips_zero_images(self, calculator):
        """Zero images returns zero FIPSCosts."""
        costs = calculator.calculate_full_fips_cost(num_fips_images=0)

        assert costs.initial_hours == 0
        assert costs.initial_cost == 0
        assert costs.monthly_hours == 0
        assert costs.monthly_cost == 0
        assert costs.yearly_hours == 0
        assert costs.yearly_cost == 0
        assert costs.total_cost == 0

    def test_calculate_full_fips_consistency(self, calculator):
        """Full calculation matches individual calculations."""
        num_images = 2

        initial_hours, initial_cost = calculator.calculate_initial_implementation(
            num_images
        )
        monthly_hours, monthly_cost = calculator.calculate_monthly_maintenance(
            num_images
        )
        full_costs = calculator.calculate_full_fips_cost(num_images)

        assert full_costs.initial_hours == initial_hours
        assert full_costs.initial_cost == initial_cost
        assert full_costs.monthly_hours == monthly_hours
        assert full_costs.monthly_cost == monthly_cost


class TestGetPhases:
    """Tests for phase list retrieval."""

    def test_get_initial_phases_returns_copies(self, calculator):
        """Phase list is a copy to prevent modification."""
        phases1 = calculator.get_initial_phases()
        phases2 = calculator.get_initial_phases()

        # Should be different list objects
        assert phases1 is not phases2
        # But contain same phases
        assert len(phases1) == len(phases2)
        assert len(phases1) == len(FIPSCalculator.INITIAL_PHASES)

    def test_get_maintenance_phases_returns_copies(self, calculator):
        """Maintenance phase list is a copy."""
        phases1 = calculator.get_maintenance_phases()
        phases2 = calculator.get_maintenance_phases()

        assert phases1 is not phases2
        assert len(phases1) == len(FIPSCalculator.MAINTENANCE_PHASES)

    def test_get_initial_phases_content(self, calculator):
        """Initial phases contain expected phase names."""
        phases = calculator.get_initial_phases()
        phase_names = [p.name for p in phases]

        assert "Initial Assessment" in phase_names
        assert "Configuration Assessment" in phase_names
        assert "Functionality Testing" in phase_names

    def test_get_maintenance_phases_content(self, calculator):
        """Maintenance phases contain expected phase names."""
        phases = calculator.get_maintenance_phases()
        phase_names = [p.name for p in phases]

        assert "Regular Updates & Dependency Management" in phase_names
        assert "Compliance Monitoring" in phase_names


class TestCustomHourlyRate:
    """Tests for custom hourly rate configuration."""

    def test_custom_hourly_rate_initial(self, custom_calculator):
        """Custom rate applies to initial implementation."""
        hours, cost = custom_calculator.calculate_initial_implementation(num_fips_images=1)

        assert cost == hours * 150.0

    def test_custom_hourly_rate_maintenance(self, custom_calculator):
        """Custom rate applies to maintenance."""
        hours, cost = custom_calculator.calculate_monthly_maintenance(num_fips_images=1)

        assert cost == hours * 150.0

    def test_custom_hourly_rate_full(self, custom_calculator):
        """Custom rate applies to full calculation."""
        costs = custom_calculator.calculate_full_fips_cost(num_fips_images=1)

        assert costs.initial_cost == costs.initial_hours * 150.0
        assert costs.monthly_cost == costs.monthly_hours * 150.0

    def test_default_hourly_rate(self, calculator):
        """Default rate matches constant."""
        assert calculator.hourly_rate == DEFAULT_HOURLY_RATE


class TestFIPSCostsDataclass:
    """Tests for FIPSCosts dataclass."""

    def test_fips_costs_creation(self):
        """FIPSCosts can be created with all fields."""
        costs = FIPSCosts(
            initial_hours=100.0,
            initial_cost=10000.0,
            monthly_hours=10.0,
            monthly_cost=1000.0,
            yearly_hours=120.0,
            yearly_cost=12000.0,
            total_cost=22000.0,
        )

        assert costs.initial_hours == 100.0
        assert costs.total_cost == 22000.0

    def test_fips_costs_all_zero(self):
        """FIPSCosts with all zeros."""
        costs = FIPSCosts(
            initial_hours=0,
            initial_cost=0,
            monthly_hours=0,
            monthly_cost=0,
            yearly_hours=0,
            yearly_cost=0,
            total_cost=0,
        )

        assert costs.total_cost == 0


class TestPhaseConfiguration:
    """Tests for phase configuration constants."""

    def test_initial_phases_have_positive_before_hours(self):
        """All initial phases should have positive before hours."""
        for phase in FIPSCalculator.INITIAL_PHASES:
            assert phase.before_min_hours >= 0
            assert phase.before_max_hours >= phase.before_min_hours

    def test_maintenance_phases_have_positive_before_hours(self):
        """All maintenance phases should have positive before hours."""
        for phase in FIPSCalculator.MAINTENANCE_PHASES:
            assert phase.before_min_hours >= 0
            assert phase.before_max_hours >= phase.before_min_hours

    def test_after_hours_not_greater_than_before(self):
        """After hours should not exceed before hours (savings should be positive)."""
        all_phases = FIPSCalculator.INITIAL_PHASES + FIPSCalculator.MAINTENANCE_PHASES
        for phase in all_phases:
            assert phase.after_min_hours <= phase.before_min_hours
            assert phase.after_max_hours <= phase.before_max_hours
