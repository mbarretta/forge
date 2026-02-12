"""
Cache directory utilities for Gauge.

This module provides centralized cache directory management to avoid
duplicated cache initialization logic across multiple files.
"""

from pathlib import Path
from typing import Optional


DEFAULT_CACHE_DIR = Path.home() / ".cache" / "gauge"
"""Default cache directory path."""


def ensure_cache_dir(cache_dir: Optional[Path] = None, subdir: str = "") -> Path:
    """
    Initialize and return cache directory, creating if needed.

    Args:
        cache_dir: Optional custom cache directory path. If None, uses ~/.cache/gauge
        subdir: Optional subdirectory within the cache directory

    Returns:
        Path to the cache directory (created if it didn't exist)

    Examples:
        >>> cache_dir = ensure_cache_dir()
        >>> cache_dir == Path.home() / ".cache" / "gauge"
        True

        >>> cache_dir = ensure_cache_dir(subdir="llm")
        >>> cache_dir == Path.home() / ".cache" / "gauge" / "llm"
        True

        >>> cache_dir = ensure_cache_dir(Path("/custom/cache"))
        >>> cache_dir == Path("/custom/cache")
        True
    """
    base_dir = cache_dir or DEFAULT_CACHE_DIR

    if subdir:
        result_dir = base_dir / subdir
    else:
        result_dir = base_dir

    result_dir.mkdir(parents=True, exist_ok=True)
    return result_dir
