"""
Console output utilities for consistent user messaging.

Provides standardized formatting for status messages, prompts, and visual separators.
These are for direct user interaction and should NOT be replaced with logger calls.
"""

import sys


def separator(width: int = 60) -> str:
    """Return a visual separator line."""
    return "=" * width


def print_header(title: str, width: int = 60) -> None:
    """Print a header with separators."""
    print(f"\n{separator(width)}")
    print(title)
    print(f"{separator(width)}")


def print_success(message: str) -> None:
    """Print a success message with checkmark."""
    print(f"\u2713 {message}")


def print_error(message: str) -> None:
    """Print an error message with X mark."""
    print(f"\u2717 {message}")


def print_info(message: str) -> None:
    """Print an informational message."""
    print(message)


def prompt_yes_no(question: str, default: bool = False) -> bool:
    """
    Prompt user for yes/no confirmation.

    Args:
        question: Question to ask
        default: Default value if user just presses Enter

    Returns:
        True for yes, False for no
    """
    default_hint = "[Y/n]" if default else "[y/N]"
    try:
        response = input(f"{question} {default_hint}: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return default

    if not response:
        return default

    return response in ("y", "yes")


def is_interactive() -> bool:
    """Check if running in an interactive terminal."""
    return sys.stdin.isatty() and sys.stdout.isatty()
