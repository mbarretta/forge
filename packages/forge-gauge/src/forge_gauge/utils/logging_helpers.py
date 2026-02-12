"""
Logging helper utilities for gauge CLI.

Provides consistent formatting for error messages, warnings, and informational output.
"""

import logging
from typing import List, Optional


def log_error_section(
    title: str,
    messages: List[str],
    logger: Optional[logging.Logger] = None,
    width: int = 60
) -> None:
    """
    Log an error section with separator lines and multiple messages.

    Args:
        title: Title message for the error section
        messages: List of error messages to display
        logger: Logger instance (defaults to root logger if not provided)
        width: Width of separator line in characters

    Examples:
        >>> log_error_section(
        ...     "Authentication Failed",
        ...     ["GitHub token not found", "Run: gh auth login"]
        ... )
        ============================================================
        Authentication Failed
        GitHub token not found
        Run: gh auth login
        ============================================================
    """
    if logger is None:
        logger = logging.getLogger()

    logger.error("=" * width)
    logger.error(title)

    for message in messages:
        if message:  # Allow empty strings for blank lines
            logger.error(message)
        else:
            logger.error("")

    logger.error("=" * width)


def log_warning_section(
    title: str,
    messages: List[str],
    logger: Optional[logging.Logger] = None,
    width: int = 60
) -> None:
    """
    Log a warning section with separator lines and multiple messages.

    Args:
        title: Title message for the warning section
        messages: List of warning messages to display
        logger: Logger instance (defaults to root logger if not provided)
        width: Width of separator line in characters

    Examples:
        >>> log_warning_section(
        ...     "SAML Authorization Required",
        ...     ["GitHub token needs SAML SSO authorization", "Attempting to refresh..."]
        ... )
        ============================================================
        SAML Authorization Required
        GitHub token needs SAML SSO authorization
        Attempting to refresh...
        ============================================================
    """
    if logger is None:
        logger = logging.getLogger()

    logger.warning("=" * width)
    logger.warning(title)

    for message in messages:
        if message:  # Allow empty strings for blank lines
            logger.warning(message)
        else:
            logger.warning("")

    logger.warning("=" * width)
