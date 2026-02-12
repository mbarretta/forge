"""Tests for pricing quote generator."""

import pytest
from pathlib import Path

from forge_gauge.outputs.pricing_quote_generator import PricingQuoteGenerator
from forge_gauge.utils.formatting import format_currency


class TestPricingQuoteGenerator:
    """Tests for PricingQuoteGenerator class."""

    @pytest.fixture
    def sample_quote_data(self):
        """Sample quote data for testing."""
        return {
            "policy_name": "Standard Enterprise Pricing",
            "effective_date": "2025-01-01",
            "currency": "USD",
            "pricing_unit": "per image per year",
            "notes": "- All prices are annual subscription fees\n- Volume discounts apply within each tier",
            "line_items": [
                {
                    "tier": "base",
                    "tier_display": "Base",
                    "quantity": 5,
                    "list_price_per_image": 29000,
                    "discounted_price_per_image": 29000,
                    "discount": 0.0,
                    "total": 145000,
                    "images": [],
                },
                {
                    "tier": "application",
                    "tier_display": "Application",
                    "quantity": 3,
                    "list_price_per_image": 35000,
                    "discounted_price_per_image": 35000,
                    "discount": 0.0,
                    "total": 105000,
                    "images": [],
                },
                {
                    "tier": "fips",
                    "tier_display": "Fips",
                    "quantity": 2,
                    "list_price_per_image": 45000,
                    "discounted_price_per_image": 45000,
                    "discount": 0.0,
                    "total": 90000,
                    "images": [],
                },
            ],
            "subtotal": 340000,
            "grand_total": 340000,
        }

    def test_format_currency(self):
        """Test currency formatting."""
        assert format_currency(29000) == "$290.00"
        assert format_currency(145000) == "$1,450.00"
        assert format_currency(1000000) == "$10,000.00"
        assert format_currency(0) == "$0.00"

    def test_generate_text_quote(self, sample_quote_data, tmp_path):
        """Test generating text-based quote."""
        generator = PricingQuoteGenerator(customer_name="Acme Corp")
        output_path = tmp_path / "quote.txt"

        result_path = generator.generate_text_quote(sample_quote_data, output_path)

        assert result_path.exists()
        assert result_path == output_path

        content = result_path.read_text()

        # Check header
        assert "CHAINGUARD CONTAINER SUBSCRIPTION PRICING QUOTE" in content
        assert "Acme Corp" in content

        # Check policy info
        assert "Standard Enterprise Pricing" in content
        assert "2025-01-01" in content

        # Check line items
        assert "Base" in content
        assert "5" in content
        assert "$290.00" in content
        assert "$1,450.00" in content

        assert "Application" in content
        assert "3" in content
        assert "$350.00" in content
        assert "$1,050.00" in content

        assert "Fips" in content
        assert "2" in content
        assert "$450.00" in content
        assert "$900.00" in content

        # Check totals
        assert "$3,400.00" in content

        # Check notes
        assert "All prices are annual subscription fees" in content
        assert "Volume discounts apply" in content

        # Check footer
        assert "Generated on" in content

    def test_generate_html_quote(self, sample_quote_data, tmp_path):
        """Test generating HTML-based quote."""
        generator = PricingQuoteGenerator(customer_name="Acme Corp")
        output_path = tmp_path / "quote.html"

        result_path = generator.generate_html_quote(sample_quote_data, output_path)

        assert result_path.exists()
        assert result_path == output_path

        content = result_path.read_text()

        # Check HTML structure
        assert "<!DOCTYPE html>" in content
        assert "<html" in content
        assert "</html>" in content

        # Check title
        assert "<title>Chainguard Pricing Quote</title>" in content

        # Check customer name
        assert "Acme Corp" in content

        # Check policy info
        assert "Standard Enterprise Pricing" in content
        assert "2025-01-01" in content

        # Check table structure
        assert "<table>" in content
        assert "<thead>" in content
        assert "<tbody>" in content

        # Check line items in table
        assert "Base" in content
        assert "Application" in content
        assert "Fips" in content

        # Check prices
        assert "$290.00" in content
        assert "$1,450.00" in content
        assert "$350.00" in content
        assert "$1,050.00" in content
        assert "$450.00" in content
        assert "$900.00" in content

        # Check totals
        assert "$3,400.00" in content
        assert "Grand Total" in content

        # Check notes
        assert "All prices are annual subscription fees" in content

        # Check footer
        assert "Generated on" in content

        # Check CSS is included
        assert "<style>" in content
        assert ".header" in content
        assert ".grand-total-row" in content

    def test_generate_text_quote_creates_directory(self, sample_quote_data, tmp_path):
        """Test that generator creates output directory if needed."""
        generator = PricingQuoteGenerator()
        output_path = tmp_path / "subdir" / "nested" / "quote.txt"

        # Directory doesn't exist yet
        assert not output_path.parent.exists()

        generator.generate_text_quote(sample_quote_data, output_path)

        # Directory should be created
        assert output_path.parent.exists()
        assert output_path.exists()

    def test_generate_html_quote_creates_directory(self, sample_quote_data, tmp_path):
        """Test that generator creates output directory if needed."""
        generator = PricingQuoteGenerator()
        output_path = tmp_path / "subdir" / "nested" / "quote.html"

        # Directory doesn't exist yet
        assert not output_path.parent.exists()

        generator.generate_html_quote(sample_quote_data, output_path)

        # Directory should be created
        assert output_path.parent.exists()
        assert output_path.exists()

    def test_empty_quote_data(self, tmp_path):
        """Test generating quote with no line items."""
        generator = PricingQuoteGenerator()
        quote_data = {
            "policy_name": "Test Policy",
            "effective_date": "2025-01-01",
            "currency": "USD",
            "pricing_unit": "per image per year",
            "notes": "",
            "line_items": [],
            "subtotal": 0,
            "grand_total": 0,
        }

        output_path = tmp_path / "empty_quote.txt"
        generator.generate_text_quote(quote_data, output_path)

        content = output_path.read_text()
        assert "Test Policy" in content
        assert "$0.00" in content

    def test_custom_customer_name(self, sample_quote_data, tmp_path):
        """Test that custom customer name appears in quote."""
        generator = PricingQuoteGenerator(customer_name="Custom Client Inc.")
        output_path = tmp_path / "quote.txt"

        generator.generate_text_quote(sample_quote_data, output_path)

        content = output_path.read_text()
        assert "Custom Client Inc." in content
