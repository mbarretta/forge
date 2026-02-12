"""Tests for pricing calculator."""

import pytest
from pathlib import Path
import tempfile

from forge_gauge.core.models import ImageTier
from forge_gauge.utils.pricing_calculator import (
    PricingTier,
    PricingPolicy,
    PricingCalculator,
)


class TestPricingTier:
    """Tests for PricingTier class."""

    def test_single_range(self):
        """Test tier with single pricing range."""
        ranges = [{"min": 1, "max": None, "list_price": 29000, "discount_percent": 0}]
        tier = PricingTier("base", ranges)

        list_price, discount, discounted_price = tier.get_price(1)
        assert list_price == 29000
        assert discount == 0.0
        assert discounted_price == 29000

        list_price, discount, discounted_price = tier.get_price(100)
        assert list_price == 29000
        assert discount == 0.0
        assert discounted_price == 29000

    def test_multiple_ranges(self):
        """Test tier with multiple pricing ranges."""
        ranges = [
            {"min": 1, "max": 10, "list_price": 29000, "discount_percent": 0},
            {"min": 11, "max": 25, "list_price": 26000, "discount_percent": 10},
            {"min": 26, "max": None, "list_price": 23000, "discount_percent": 20},
        ]
        tier = PricingTier("base", ranges)

        # Test first range
        list_price, discount, discounted_price = tier.get_price(1)
        assert list_price == 29000
        assert discount == 0.0
        assert discounted_price == 29000

        list_price, discount, discounted_price = tier.get_price(10)
        assert list_price == 29000
        assert discount == 0.0
        assert discounted_price == 29000

        # Test second range
        list_price, discount, discounted_price = tier.get_price(11)
        assert list_price == 26000
        assert discount == 0.10
        assert discounted_price == 23400  # 26000 * 0.9

        list_price, discount, discounted_price = tier.get_price(25)
        assert list_price == 26000
        assert discount == 0.10
        assert discounted_price == 23400  # 26000 * 0.9

        # Test third range
        list_price, discount, discounted_price = tier.get_price(26)
        assert list_price == 23000
        assert discount == 0.20
        assert discounted_price == 18400  # 23000 * 0.8

        list_price, discount, discounted_price = tier.get_price(1000)
        assert list_price == 23000
        assert discount == 0.20
        assert discounted_price == 18400  # 23000 * 0.8

    def test_invalid_quantity_zero(self):
        """Test that zero quantity raises error."""
        ranges = [{"min": 1, "max": None, "list_price": 29000, "discount_percent": 0}]
        tier = PricingTier("base", ranges)

        with pytest.raises(ValueError) as exc_info:
            tier.get_price(0)
        assert "must be at least 1" in str(exc_info.value)

    def test_invalid_quantity_negative(self):
        """Test that negative quantity raises error."""
        ranges = [{"min": 1, "max": None, "list_price": 29000, "discount_percent": 0}]
        tier = PricingTier("base", ranges)

        with pytest.raises(ValueError) as exc_info:
            tier.get_price(-5)
        assert "must be at least 1" in str(exc_info.value)

    def test_fractional_discount_percent(self):
        """Test that fractional discount percentages work (e.g., 20.5%)."""
        ranges = [
            {"min": 1, "max": 10, "list_price": 29000, "discount_percent": 0},
            {"min": 11, "max": None, "list_price": 26000, "discount_percent": 20.5},
        ]
        tier = PricingTier("base", ranges)

        # First range: no discount
        list_price, discount, discounted_price = tier.get_price(5)
        assert list_price == 29000
        assert discount == 0.0
        assert discounted_price == 29000

        # Second range: 20.5% discount (should be 0.205 as decimal)
        list_price, discount, discounted_price = tier.get_price(15)
        assert list_price == 26000
        assert discount == 0.205
        assert discounted_price == 20670  # 26000 * 0.795


class TestPricingPolicy:
    """Tests for PricingPolicy class."""

    @pytest.fixture
    def sample_policy_data(self):
        """Sample policy data for testing."""
        return {
            "policy_name": "Test Policy",
            "effective_date": "2025-01-01",
            "currency": "USD",
            "pricing_unit": "per image per year",
            "notes": "Test notes",
            "base": [
                {"min": 1, "max": 10, "list_price": 29000, "discount_percent": 0}
            ],
            "application": [
                {"min": 1, "max": 10, "list_price": 35000, "discount_percent": 0}
            ],
            "fips": [
                {"min": 1, "max": 5, "list_price": 45000, "discount_percent": 0}
            ],
            "ai": [
                {"min": 1, "max": 5, "list_price": 50000, "discount_percent": 0}
            ],
        }

    def test_load_from_dict(self, sample_policy_data):
        """Test loading policy from dictionary."""
        policy = PricingPolicy(sample_policy_data)

        assert policy.policy_name == "Test Policy"
        assert policy.effective_date == "2025-01-01"
        assert policy.currency == "USD"
        assert policy.pricing_unit == "per image per year"
        assert policy.notes == "Test notes"

        assert "base" in policy.tiers
        assert "application" in policy.tiers
        assert "fips" in policy.tiers
        assert "ai" in policy.tiers

    def test_load_from_file(self, sample_policy_data, tmp_path):
        """Test loading policy from YAML file."""
        import yaml

        policy_file = tmp_path / "test-policy.yaml"
        with open(policy_file, "w") as f:
            yaml.dump(sample_policy_data, f)

        policy = PricingPolicy.load_from_file(policy_file)
        assert policy.policy_name == "Test Policy"
        assert len(policy.tiers) == 4

    def test_load_from_file_not_found(self):
        """Test that loading nonexistent file raises error."""
        with pytest.raises(FileNotFoundError):
            PricingPolicy.load_from_file(Path("/nonexistent/policy.yaml"))

    def test_missing_tier_logs_warning(self, caplog):
        """Test that missing tier logs a warning."""
        policy_data = {
            "policy_name": "Incomplete Policy",
            "base": [{"min": 1, "max": None, "list_price": 29000}],
            # Missing application, fips, ai tiers
        }

        policy = PricingPolicy(policy_data)

        # Should have base tier
        assert "base" in policy.tiers

        # Should warn about missing tiers
        assert any("missing tier" in record.message.lower() for record in caplog.records)


class TestPricingCalculator:
    """Tests for PricingCalculator class."""

    @pytest.fixture
    def sample_policy(self):
        """Create sample pricing policy."""
        policy_data = {
            "policy_name": "Test Policy",
            "effective_date": "2025-01-01",
            "currency": "USD",
            "pricing_unit": "per image per year",
            "base": [
                {"min": 1, "max": 10, "list_price": 29000, "discount_percent": 0},
                {"min": 11, "max": None, "list_price": 26000, "discount_percent": 10},
            ],
            "application": [
                {"min": 1, "max": 10, "list_price": 35000, "discount_percent": 0},
                {"min": 11, "max": None, "list_price": 31500, "discount_percent": 10},
            ],
            "fips": [
                {"min": 1, "max": None, "list_price": 45000, "discount_percent": 0}
            ],
            "ai": [
                {"min": 1, "max": None, "list_price": 50000, "discount_percent": 0}
            ],
        }
        return PricingPolicy(policy_data)

    def test_calculate_tier_cost_single(self, sample_policy):
        """Test calculating cost for single tier."""
        calc = PricingCalculator(sample_policy)

        list_price, discounted_price, total, discount = calc.calculate_tier_cost(ImageTier.BASE, 5)

        assert list_price == 29000
        assert discounted_price == 29000
        assert total == 145000  # 5 * 29000
        assert discount == 0.0

    def test_calculate_tier_cost_volume_discount(self, sample_policy):
        """Test that volume discount is applied correctly."""
        calc = PricingCalculator(sample_policy)

        # First tier: 10 images at 29000
        list_price, discounted_price, total, discount = calc.calculate_tier_cost(ImageTier.BASE, 10)
        assert list_price == 29000
        assert discounted_price == 29000
        assert total == 290000
        assert discount == 0.0

        # Second tier: 15 images at 26000 with 10% discount
        list_price, discounted_price, total, discount = calc.calculate_tier_cost(ImageTier.BASE, 15)
        assert list_price == 26000
        assert discounted_price == 23400  # 26000 * 0.9
        assert total == 351000  # 15 * 23400
        assert discount == 0.10

    def test_calculate_quote_single_tier(self, sample_policy):
        """Test calculating quote with single tier."""
        calc = PricingCalculator(sample_policy)

        quote = calc.calculate_quote({ImageTier.BASE: 5})

        assert quote["policy_name"] == "Test Policy"
        assert quote["currency"] == "USD"
        assert len(quote["line_items"]) == 1

        item = quote["line_items"][0]
        assert item["tier"] == "base"
        assert item["quantity"] == 5
        assert item["list_price_per_image"] == 29000
        assert item["discounted_price_per_image"] == 29000
        assert item["discount"] == 0.0
        assert item["total"] == 145000

        assert quote["subtotal"] == 145000
        assert quote["grand_total"] == 145000

    def test_calculate_quote_multiple_tiers(self, sample_policy):
        """Test calculating quote with multiple tiers."""
        calc = PricingCalculator(sample_policy)

        quote = calc.calculate_quote({
            ImageTier.BASE: 5,
            ImageTier.APPLICATION: 3,
            ImageTier.FIPS: 2,
        })

        assert len(quote["line_items"]) == 3

        # Verify each line item
        items_by_tier = {item["tier"]: item for item in quote["line_items"]}

        assert items_by_tier["base"]["total"] == 145000  # 5 * 29000
        assert items_by_tier["application"]["total"] == 105000  # 3 * 35000
        assert items_by_tier["fips"]["total"] == 90000  # 2 * 45000

        expected_total = 145000 + 105000 + 90000
        assert quote["subtotal"] == expected_total
        assert quote["grand_total"] == expected_total

    def test_calculate_quote_skips_zero_quantity(self, sample_policy):
        """Test that zero quantities are skipped."""
        calc = PricingCalculator(sample_policy)

        quote = calc.calculate_quote({
            ImageTier.BASE: 5,
            ImageTier.APPLICATION: 0,  # Should be skipped
            ImageTier.FIPS: 2,
        })

        assert len(quote["line_items"]) == 2
        tiers = [item["tier"] for item in quote["line_items"]]
        assert "base" in tiers
        assert "fips" in tiers
        assert "application" not in tiers

    def test_from_policy_file(self, sample_policy, tmp_path):
        """Test creating calculator from policy file."""
        import yaml

        policy_data = {
            "policy_name": "File Test",
            "base": [{"min": 1, "max": None, "list_price": 29000, "discount_percent": 0}],
            "application": [{"min": 1, "max": None, "list_price": 35000, "discount_percent": 0}],
            "fips": [{"min": 1, "max": None, "list_price": 45000, "discount_percent": 0}],
            "ai": [{"min": 1, "max": None, "list_price": 50000, "discount_percent": 0}],
        }

        policy_file = tmp_path / "policy.yaml"
        with open(policy_file, "w") as f:
            yaml.dump(policy_data, f)

        calc = PricingCalculator.from_policy_file(policy_file)

        assert calc.policy.policy_name == "File Test"

        # Test calculation works
        quote = calc.calculate_quote({ImageTier.BASE: 1})
        assert quote["grand_total"] == 29000
