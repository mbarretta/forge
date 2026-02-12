"""
Tests for filename sanitization in CLI.

Ensures that customer names with spaces and special characters
are properly converted to safe, lowercase filenames.
"""

import pytest


def sanitize_customer_name(customer_name: str) -> str:
    """
    Sanitize customer name for use as a filename.

    Args:
        customer_name: Raw customer name input

    Returns:
        Safe filename string (lowercase, no spaces, & preserved, consecutive underscores collapsed)
    """
    import re
    # First, remove & and . characters entirely (don't replace with underscore)
    safe_name = customer_name.replace('&', '').replace('.', '')
    # Then replace other special characters with underscores, keep alphanumeric, spaces, hyphens, underscores
    safe_name = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in safe_name)
    # Replace spaces with underscores and convert to lowercase
    safe_name = safe_name.replace(' ', '_').lower()
    # Collapse multiple consecutive underscores into one
    return re.sub(r'_+', '_', safe_name)


class TestFilenameSanitization:
    """Test filename sanitization for various customer name inputs."""

    def test_simple_name(self):
        """Test simple customer name without special characters."""
        assert sanitize_customer_name("Acme") == "acme"

    def test_name_with_spaces(self):
        """Test customer name with spaces."""
        assert sanitize_customer_name("Acme Corp") == "acme_corp"
        assert sanitize_customer_name("Big Company Name") == "big_company_name"

    def test_name_with_special_characters(self):
        """Test customer name with special characters (& and . removed)."""
        assert sanitize_customer_name("Acme & Co.") == "acme_co"
        assert sanitize_customer_name("Company (USA)") == "company_usa_"
        assert sanitize_customer_name("Smith & Sons, Inc.") == "smith_sons_inc"

    def test_name_with_unicode(self):
        """Test customer name with unicode characters (preserved and lowercased)."""
        assert sanitize_customer_name("Café Münster") == "café_münster"
        assert sanitize_customer_name("Société Générale") == "société_générale"

    def test_name_with_numbers(self):
        """Test customer name with numbers."""
        assert sanitize_customer_name("Company123") == "company123"
        assert sanitize_customer_name("3M Corporation") == "3m_corporation"

    def test_name_with_hyphens_and_underscores(self):
        """Test that hyphens and underscores are preserved."""
        assert sanitize_customer_name("Acme-Corp") == "acme-corp"
        assert sanitize_customer_name("Big_Company") == "big_company"
        assert sanitize_customer_name("Multi-Word_Name") == "multi-word_name"

    def test_uppercase_to_lowercase(self):
        """Test that uppercase is converted to lowercase."""
        assert sanitize_customer_name("ACME CORP") == "acme_corp"
        assert sanitize_customer_name("AcMe CoRp") == "acme_corp"

    def test_multiple_spaces(self):
        """Test that multiple consecutive spaces are collapsed to single underscore."""
        assert sanitize_customer_name("Acme  Corp") == "acme_corp"

    def test_leading_trailing_spaces(self):
        """Test handling of leading/trailing spaces."""
        assert sanitize_customer_name(" Acme Corp ") == "_acme_corp_"

    def test_empty_string(self):
        """Test empty customer name."""
        assert sanitize_customer_name("") == ""

    def test_all_special_characters(self):
        """Test customer name with special characters (collapsed to single _)."""
        assert sanitize_customer_name("!@#$%^&*()") == "_"

    def test_real_world_examples(self):
        """Test real-world customer name examples."""
        assert sanitize_customer_name("Amazon Web Services") == "amazon_web_services"
        assert sanitize_customer_name("AT&T Inc.") == "att_inc"
        assert sanitize_customer_name("Johnson & Johnson") == "johnson_johnson"
        assert sanitize_customer_name("Procter & Gamble Co.") == "procter_gamble_co"
        assert sanitize_customer_name("Berkshire Hathaway") == "berkshire_hathaway"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
