"""Tests for formatting utilities."""

from datetime import datetime

import pytest

from forge_gauge.utils.formatting import format_date_with_ordinal


class TestFormatDateWithOrdinal:
    """Tests for format_date_with_ordinal function."""

    def test_first_of_month(self):
        """Test 1st suffix."""
        date = datetime(2025, 11, 1)
        assert format_date_with_ordinal(date) == "November 1st, 2025"

    def test_second_of_month(self):
        """Test 2nd suffix."""
        date = datetime(2025, 11, 2)
        assert format_date_with_ordinal(date) == "November 2nd, 2025"

    def test_third_of_month(self):
        """Test 3rd suffix."""
        date = datetime(2025, 11, 3)
        assert format_date_with_ordinal(date) == "November 3rd, 2025"

    def test_fourth_of_month(self):
        """Test 4th suffix."""
        date = datetime(2025, 11, 4)
        assert format_date_with_ordinal(date) == "November 4th, 2025"

    def test_eleventh_special_case(self):
        """Test 11th (not 11st)."""
        date = datetime(2025, 11, 11)
        assert format_date_with_ordinal(date) == "November 11th, 2025"

    def test_twelfth_special_case(self):
        """Test 12th (not 12nd)."""
        date = datetime(2025, 11, 12)
        assert format_date_with_ordinal(date) == "November 12th, 2025"

    def test_thirteenth_special_case(self):
        """Test 13th (not 13rd)."""
        date = datetime(2025, 11, 13)
        assert format_date_with_ordinal(date) == "November 13th, 2025"

    def test_twenty_first(self):
        """Test 21st (ends in 1 but not in teen range)."""
        date = datetime(2025, 11, 21)
        assert format_date_with_ordinal(date) == "November 21st, 2025"

    def test_twenty_second(self):
        """Test 22nd (ends in 2 but not in teen range)."""
        date = datetime(2025, 11, 22)
        assert format_date_with_ordinal(date) == "November 22nd, 2025"

    def test_twenty_third(self):
        """Test 23rd (ends in 3 but not in teen range)."""
        date = datetime(2025, 11, 23)
        assert format_date_with_ordinal(date) == "November 23rd, 2025"

    def test_thirty_first(self):
        """Test 31st (last day of month)."""
        date = datetime(2025, 12, 31)
        assert format_date_with_ordinal(date) == "December 31st, 2025"

    def test_different_months(self):
        """Test various months format correctly."""
        dates_and_expected = [
            (datetime(2025, 1, 5), "January 5th, 2025"),
            (datetime(2025, 2, 10), "February 10th, 2025"),
            (datetime(2025, 3, 15), "March 15th, 2025"),
            (datetime(2025, 4, 20), "April 20th, 2025"),
            (datetime(2025, 5, 25), "May 25th, 2025"),
            (datetime(2025, 6, 30), "June 30th, 2025"),
            (datetime(2025, 7, 1), "July 1st, 2025"),
            (datetime(2025, 8, 2), "August 2nd, 2025"),
            (datetime(2025, 9, 3), "September 3rd, 2025"),
            (datetime(2025, 10, 14), "October 14th, 2025"),
        ]

        for date, expected in dates_and_expected:
            assert format_date_with_ordinal(date) == expected

    def test_different_years(self):
        """Test year formatting works correctly."""
        date_2024 = datetime(2024, 11, 4)
        assert format_date_with_ordinal(date_2024) == "November 4th, 2024"

        date_2026 = datetime(2026, 11, 4)
        assert format_date_with_ordinal(date_2026) == "November 4th, 2026"

    def test_all_days_have_valid_suffix(self):
        """Test that all days 1-31 produce valid suffixes."""
        # Map of day -> expected suffix
        expected_suffixes = {
            1: "st", 2: "nd", 3: "rd",
            4: "th", 5: "th", 6: "th", 7: "th", 8: "th", 9: "th", 10: "th",
            11: "th", 12: "th", 13: "th",  # Special teen cases
            14: "th", 15: "th", 16: "th", 17: "th", 18: "th", 19: "th", 20: "th",
            21: "st", 22: "nd", 23: "rd",
            24: "th", 25: "th", 26: "th", 27: "th", 28: "th", 29: "th", 30: "th",
            31: "st",
        }

        for day, expected_suffix in expected_suffixes.items():
            date = datetime(2025, 1, day)
            result = format_date_with_ordinal(date)
            # Check that the result contains the day with correct suffix
            assert f"{day}{expected_suffix}" in result, f"Day {day} should have suffix '{expected_suffix}'"
