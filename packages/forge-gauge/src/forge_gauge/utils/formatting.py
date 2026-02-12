"""
Formatting utilities for gauge output.

Provides common formatting functions for dates, currency, numbers, and other display values.
"""

from datetime import datetime


def format_number(num: int) -> str:
    """
    Format number with thousands separators.

    Args:
        num: Integer to format

    Returns:
        Formatted number string with commas (e.g., "1,234,567")

    Examples:
        >>> format_number(1234567)
        '1,234,567'
        >>> format_number(100)
        '100'
        >>> format_number(0)
        '0'
    """
    return f"{num:,}"


def format_currency(amount: int, currency: str = "USD") -> str:
    """
    Format amount as currency string.

    Args:
        amount: Amount in cents
        currency: Currency code (currently only USD is formatted)

    Returns:
        Formatted currency string (e.g., "$29,000.00")

    Examples:
        >>> format_currency(29000)
        '$290.00'
        >>> format_currency(145000)
        '$1,450.00'
        >>> format_currency(1000000)
        '$10,000.00'
    """
    # Convert cents to dollars
    dollars = amount / 100.0
    return f"${dollars:,.2f}"


def format_percentage(value: float, decimals: int = 1) -> str:
    """
    Format value as percentage string.

    Args:
        value: Percentage value (e.g., 85.5 for 85.5%)
        decimals: Number of decimal places to display

    Returns:
        Formatted percentage string (e.g., "85.5%")

    Examples:
        >>> format_percentage(85.5)
        '85.5%'
        >>> format_percentage(100.0)
        '100.0%'
        >>> format_percentage(33.333, decimals=2)
        '33.33%'
    """
    return f"{value:.{decimals}f}%"


def format_date_with_ordinal(date: datetime) -> str:
    """
    Format date with ordinal suffix (e.g., "November 4th, 2025").

    Args:
        date: datetime object to format

    Returns:
        Formatted date string with ordinal suffix

    Examples:
        >>> from datetime import datetime
        >>> format_date_with_ordinal(datetime(2025, 11, 4))
        'November 4th, 2025'
        >>> format_date_with_ordinal(datetime(2025, 12, 1))
        'December 1st, 2025'
        >>> format_date_with_ordinal(datetime(2025, 12, 22))
        'December 22nd, 2025'
    """
    day = date.day

    # Determine ordinal suffix
    if 10 <= day % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")

    return date.strftime(f"%B {day}{suffix}, %Y")
