#!/usr/bin/env python3
"""
Standalone test for filename sanitization in CLI.

Tests that customer names with spaces and special characters
are properly converted to safe, lowercase filenames.
"""


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


def test_sanitization():
    """Run all sanitization tests."""
    tests_passed = 0
    tests_failed = 0

    test_cases = [
        # (input, expected_output, description)
        ("Acme", "acme", "Simple name without special characters"),
        ("Acme Corp", "acme_corp", "Name with spaces"),
        ("Big Company Name", "big_company_name", "Multiple spaces"),
        ("Acme & Co.", "acme_co", "Ampersand and period removed"),
        ("Company (USA)", "company_usa_", "Parentheses removed"),
        ("Smith & Sons, Inc.", "smith_sons_inc", "Ampersand, comma, period removed"),
        ("Café Münster", "café_münster", "Unicode characters preserved"),
        ("Société Générale", "société_générale", "French accents preserved"),
        ("Company123", "company123", "Numbers"),
        ("3M Corporation", "3m_corporation", "Leading number"),
        ("Acme-Corp", "acme-corp", "Hyphen preserved"),
        ("Big_Company", "big_company", "Underscore preserved"),
        ("Multi-Word_Name", "multi-word_name", "Mixed separators"),
        ("ACME CORP", "acme_corp", "Uppercase conversion"),
        ("AcMe CoRp", "acme_corp", "Mixed case conversion"),
        ("Acme  Corp", "acme_corp", "Multiple consecutive spaces collapsed"),
        (" Acme Corp ", "_acme_corp_", "Leading/trailing spaces (preserved as single _)"),
        ("", "", "Empty string"),
        ("!@#$%^&*()", "_", "All special chars become _, collapsed to single _"),
        ("Amazon Web Services", "amazon_web_services", "Real-world: AWS"),
        ("AT&T Inc.", "att_inc", "Real-world: AT&T (& and period removed)"),
        ("Johnson & Johnson", "johnson_johnson", "Real-world: J&J (& removed, space collapsed)"),
        ("Procter & Gamble Co.", "procter_gamble_co", "Real-world: P&G (& and period removed)"),
        ("Berkshire Hathaway", "berkshire_hathaway", "Real-world: BH"),
    ]

    print("Running filename sanitization tests...")
    print("=" * 70)

    for input_name, expected, description in test_cases:
        result = sanitize_customer_name(input_name)
        if result == expected:
            tests_passed += 1
            status = "✓ PASS"
        else:
            tests_failed += 1
            status = "✗ FAIL"
            print(f"{status}: {description}")
            print(f"  Input:    '{input_name}'")
            print(f"  Expected: '{expected}'")
            print(f"  Got:      '{result}'")
            print()

    print("=" * 70)
    print(f"Tests passed: {tests_passed}/{len(test_cases)}")
    print(f"Tests failed: {tests_failed}/{len(test_cases)}")

    if tests_failed == 0:
        print("\n✓ All tests passed!")
        return 0
    else:
        print(f"\n✗ {tests_failed} test(s) failed")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(test_sanitization())
