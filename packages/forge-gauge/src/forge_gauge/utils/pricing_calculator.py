"""
Pricing calculator for Chainguard image subscriptions.

Loads pricing policies from YAML files and calculates costs based on
image tiers and quantities with volume discounts.
"""

import logging
from pathlib import Path
from typing import Optional

import yaml

from forge_gauge.core.models import ImageTier

logger = logging.getLogger(__name__)


class PricingTier:
    """Represents a pricing tier with volume-based pricing."""

    def __init__(self, tier_name: str, ranges: list[dict]):
        """
        Initialize pricing tier.

        Args:
            tier_name: Name of the tier (e.g., "base", "application")
            ranges: List of pricing ranges with min, max, price, description
        """
        self.tier_name = tier_name
        self.ranges = sorted(ranges, key=lambda r: r["min"])

    def get_price(self, quantity: int) -> tuple[int, float, int]:
        """
        Get pricing information for given quantity.

        Args:
            quantity: Number of images

        Returns:
            Tuple of (list_price_per_image, discount_percent, discounted_price_per_image)
            - list_price_per_image: List price in cents before discount
            - discount_percent: Discount as decimal (e.g., 0.10 for 10%)
            - discounted_price_per_image: Final price in cents after discount

        Raises:
            ValueError: If quantity is invalid or no matching range found
        """
        if quantity < 1:
            raise ValueError(f"Quantity must be at least 1, got {quantity}")

        for range_config in self.ranges:
            min_qty = range_config["min"]
            max_qty = range_config.get("max")

            if max_qty is None:
                # Unlimited range
                if quantity >= min_qty:
                    # Convert discount_percent to decimal (e.g., 10 -> 0.10)
                    discount_percent = range_config.get("discount_percent", 0)
                    discount = discount_percent / 100.0
                    list_price = range_config["list_price"]
                    # Calculate discounted price
                    discounted_price = int(list_price * (1 - discount))
                    return (list_price, discount, discounted_price)
            else:
                # Bounded range
                if min_qty <= quantity <= max_qty:
                    # Convert discount_percent to decimal (e.g., 10 -> 0.10)
                    discount_percent = range_config.get("discount_percent", 0)
                    discount = discount_percent / 100.0
                    list_price = range_config["list_price"]
                    # Calculate discounted price
                    discounted_price = int(list_price * (1 - discount))
                    return (list_price, discount, discounted_price)

        raise ValueError(
            f"No pricing range found for {self.tier_name} tier with quantity {quantity}"
        )


class PricingPolicy:
    """Represents a complete pricing policy with all tiers."""

    def __init__(self, policy_data: dict):
        """
        Initialize pricing policy.

        Args:
            policy_data: Dictionary loaded from YAML policy file
        """
        self.policy_name = policy_data.get("policy_name", "Unnamed Policy")
        self.effective_date = policy_data.get("effective_date", "N/A")
        self.currency = policy_data.get("currency", "USD")
        self.pricing_unit = policy_data.get("pricing_unit", "per image per year")
        self.notes = policy_data.get("notes", "")

        # Load tier pricing
        self.tiers: dict[str, PricingTier] = {}
        for tier_value in ImageTier:
            tier_name = tier_value.value
            if tier_name in policy_data:
                self.tiers[tier_name] = PricingTier(tier_name, policy_data[tier_name])
            else:
                logger.warning(f"Pricing policy missing tier: {tier_name}")

    @classmethod
    def load_from_file(cls, policy_path: Path) -> "PricingPolicy":
        """
        Load pricing policy from YAML file.

        Args:
            policy_path: Path to YAML policy file

        Returns:
            PricingPolicy instance

        Raises:
            FileNotFoundError: If policy file doesn't exist
            ValueError: If policy file is invalid
        """
        if not policy_path.exists():
            raise FileNotFoundError(f"Pricing policy file not found: {policy_path}")

        try:
            with open(policy_path, "r") as f:
                policy_data = yaml.safe_load(f)

            if not isinstance(policy_data, dict):
                raise ValueError("Pricing policy must be a YAML dictionary")

            return cls(policy_data)

        except yaml.YAMLError as e:
            raise ValueError(f"Failed to parse pricing policy YAML: {e}")
        except Exception as e:
            raise ValueError(f"Failed to load pricing policy: {e}")


class PricingCalculator:
    """Calculator for Chainguard image subscription costs."""

    def __init__(self, policy: PricingPolicy):
        """
        Initialize pricing calculator.

        Args:
            policy: Pricing policy to use for calculations
        """
        self.policy = policy

    @classmethod
    def from_policy_file(cls, policy_path: Path) -> "PricingCalculator":
        """
        Create calculator from policy file.

        Args:
            policy_path: Path to YAML policy file

        Returns:
            PricingCalculator instance
        """
        policy = PricingPolicy.load_from_file(policy_path)
        return cls(policy)

    def calculate_tier_cost(
        self, tier: ImageTier, quantity: int
    ) -> tuple[int, int, float, int]:
        """
        Calculate cost for a specific tier.

        Args:
            tier: Image tier
            quantity: Number of images

        Returns:
            Tuple of (list_price_per_image, discounted_price_per_image, total_cost, discount_percent)
            - list_price_per_image: List price in cents before discount
            - discounted_price_per_image: Price in cents after discount
            - total_cost: Total cost in cents (discounted_price_per_image * quantity)
            - discount_percent: Discount as decimal (e.g., 0.10 for 10%)

        Raises:
            ValueError: If tier not in policy or quantity invalid
        """
        tier_name = tier.value

        if tier_name not in self.policy.tiers:
            raise ValueError(
                f"Tier '{tier_name}' not found in pricing policy. "
                f"Available tiers: {list(self.policy.tiers.keys())}"
            )

        pricing_tier = self.policy.tiers[tier_name]
        list_price, discount, discounted_price = pricing_tier.get_price(quantity)
        total_cost = discounted_price * quantity

        return list_price, discounted_price, total_cost, discount

    def calculate_quote(
        self, tier_quantities: dict[ImageTier, int], tier_images: Optional[dict[ImageTier, list[str]]] = None
    ) -> dict:
        """
        Calculate complete pricing quote for multiple tiers.

        Args:
            tier_quantities: Dictionary mapping ImageTier to quantity
            tier_images: Optional dictionary mapping ImageTier to list of image names

        Returns:
            Dictionary with quote details including:
            - policy_name, effective_date, currency, pricing_unit
            - line_items: List of dicts with tier, quantity, price_per_image, total, images
            - subtotal: Sum of all line items
            - grand_total: Final total (same as subtotal, extensible for taxes/fees)
        """
        line_items = []
        subtotal = 0

        # Calculate cost for each tier
        for tier, quantity in sorted(tier_quantities.items(), key=lambda x: x[0].value):
            if quantity == 0:
                continue

            try:
                list_price, discounted_price, total_cost, discount = self.calculate_tier_cost(
                    tier, quantity
                )

                # Get image names for this tier
                images = tier_images.get(tier, []) if tier_images else []

                line_items.append({
                    "tier": tier.value,
                    "tier_display": tier.value.title(),
                    "quantity": quantity,
                    "list_price_per_image": list_price,
                    "discounted_price_per_image": discounted_price,
                    "discount": discount,
                    "total": total_cost,
                    "images": images,
                })

                subtotal += total_cost

            except ValueError as e:
                logger.error(f"Failed to calculate cost for {tier.value}: {e}")
                raise

        return {
            "policy_name": self.policy.policy_name,
            "effective_date": self.policy.effective_date,
            "currency": self.policy.currency,
            "pricing_unit": self.policy.pricing_unit,
            "notes": self.policy.notes,
            "line_items": line_items,
            "subtotal": subtotal,
            "grand_total": subtotal,  # Extensible for taxes/fees later
        }
