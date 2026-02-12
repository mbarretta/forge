"""
FIPS (Federal Information Processing Standards) cost calculations.

Estimates the cost of implementing and maintaining FIPS-compliant images,
including initial implementation phases and ongoing maintenance.
"""

from dataclasses import dataclass

from forge_gauge.constants import DEFAULT_HOURLY_RATE


@dataclass
class FIPSPhase:
    """A phase in FIPS implementation."""

    name: str
    before_min_hours: float
    before_max_hours: float
    after_min_hours: float
    after_max_hours: float

    @property
    def hours_saved_min(self) -> float:
        """Minimum hours saved with Chainguard."""
        return self.before_min_hours - self.after_min_hours

    @property
    def hours_saved_max(self) -> float:
        """Maximum hours saved with Chainguard."""
        return self.before_max_hours - self.after_max_hours

    @property
    def hours_saved_avg(self) -> float:
        """Average hours saved with Chainguard."""
        return (self.hours_saved_min + self.hours_saved_max) / 2


@dataclass
class FIPSCosts:
    """FIPS implementation and maintenance costs."""

    initial_hours: float
    initial_cost: float
    monthly_hours: float
    monthly_cost: float
    yearly_hours: float
    yearly_cost: float
    total_cost: float


class FIPSCalculator:
    """
    Calculate costs for FIPS-compliant image implementation.

    Provides estimates for both initial implementation effort and
    ongoing maintenance costs.
    """

    # Initial implementation phases (per image)
    INITIAL_PHASES = [
        FIPSPhase("Initial Assessment", 4, 8, 0.5, 1),
        FIPSPhase("Container Ownership Check", 2, 4, 0.5, 1),
        FIPSPhase("3rd Party Assessment", 8, 16, 0, 0),
        FIPSPhase("Package FIPS Requirements Evaluation", 8, 16, 1, 2),
        FIPSPhase("Configuration Assessment", 2, 4, 1, 2),
        FIPSPhase("Compatibility Study", 2, 4, 0, 0),
        FIPSPhase("Base Image Configuration", 4, 10, 0, 0),
        FIPSPhase("Language Specific Implementation", 16, 24, 0, 0),
        FIPSPhase("Create Patches", 8, 16, 1, 2),
        FIPSPhase("Repository Setup", 16, 24, 0, 0),
        FIPSPhase("FIPS Customization", 16, 24, 0, 0),
        FIPSPhase("Conflict Resolution", 24, 40, 0, 0),
        FIPSPhase("Functionality Testing", 2, 5, 1, 2),
        FIPSPhase("Security Testing", 2, 5, 0, 0),
        FIPSPhase("Deployment Customization", 2, 5, 0, 0),
    ]

    # Monthly maintenance phases (per image)
    MAINTENANCE_PHASES = [
        FIPSPhase("Regular Updates & Dependency Management", 6, 16, 1, 2),
        FIPSPhase("Compliance Monitoring", 6, 16, 2, 4),
    ]

    def __init__(self, hourly_rate: float = DEFAULT_HOURLY_RATE):
        """
        Initialize FIPS calculator.

        Args:
            hourly_rate: Engineering hourly rate in USD
        """
        self.hourly_rate = hourly_rate

    def calculate_initial_implementation(
        self, num_fips_images: int
    ) -> tuple[float, float]:
        """
        Calculate initial FIPS implementation costs.

        Args:
            num_fips_images: Number of FIPS images to implement

        Returns:
            Tuple of (total_hours, total_cost)
        """
        if num_fips_images == 0:
            return 0.0, 0.0

        # Calculate hours saved per image
        hours_per_image = sum(
            phase.hours_saved_avg for phase in self.INITIAL_PHASES
        )

        total_hours = hours_per_image * num_fips_images
        total_cost = total_hours * self.hourly_rate

        return total_hours, total_cost

    def calculate_monthly_maintenance(
        self, num_fips_images: int
    ) -> tuple[float, float]:
        """
        Calculate monthly FIPS maintenance costs.

        Args:
            num_fips_images: Number of FIPS images to maintain

        Returns:
            Tuple of (monthly_hours, monthly_cost)
        """
        if num_fips_images == 0:
            return 0.0, 0.0

        # Calculate hours saved per image per month
        hours_per_image = sum(
            phase.hours_saved_avg for phase in self.MAINTENANCE_PHASES
        )

        monthly_hours = hours_per_image * num_fips_images
        monthly_cost = monthly_hours * self.hourly_rate

        return monthly_hours, monthly_cost

    def calculate_full_fips_cost(self, num_fips_images: int) -> FIPSCosts:
        """
        Calculate complete FIPS costs (initial + ongoing).

        Args:
            num_fips_images: Number of FIPS images

        Returns:
            FIPSCosts with all calculations
        """
        if num_fips_images == 0:
            return FIPSCosts(
                initial_hours=0,
                initial_cost=0,
                monthly_hours=0,
                monthly_cost=0,
                yearly_hours=0,
                yearly_cost=0,
                total_cost=0,
            )

        initial_hours, initial_cost = self.calculate_initial_implementation(
            num_fips_images
        )
        monthly_hours, monthly_cost = self.calculate_monthly_maintenance(
            num_fips_images
        )

        yearly_hours = monthly_hours * 12
        yearly_cost = monthly_cost * 12
        total_cost = initial_cost + yearly_cost

        return FIPSCosts(
            initial_hours=initial_hours,
            initial_cost=initial_cost,
            monthly_hours=monthly_hours,
            monthly_cost=monthly_cost,
            yearly_hours=yearly_hours,
            yearly_cost=yearly_cost,
            total_cost=total_cost,
        )

    def get_initial_phases(self) -> list[FIPSPhase]:
        """Get list of initial implementation phases."""
        return self.INITIAL_PHASES.copy()

    def get_maintenance_phases(self) -> list[FIPSPhase]:
        """Get list of maintenance phases."""
        return self.MAINTENANCE_PHASES.copy()
