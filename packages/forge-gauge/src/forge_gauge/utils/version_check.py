"""
Version checking utilities for Gauge.

Checks GitHub releases for newer versions and provides update notifications.
"""

import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

from forge_gauge.constants import GITHUB_RELEASES_URL

logger = logging.getLogger(__name__)

# Cache file for version check results (avoid checking on every invocation)
CACHE_DIR = Path.home() / ".cache" / "gauge"
VERSION_CACHE_FILE = CACHE_DIR / "version_check.txt"
VERSION_CHECK_INTERVAL = 86400  # Check at most once per day (in seconds)


def _parse_version(version_str: str) -> tuple[int, ...]:
    """
    Parse a version string into a tuple for comparison.

    Args:
        version_str: Version string like "2.0.0" or "v2.0.0"

    Returns:
        Tuple of integers for comparison
    """
    # Strip leading 'v' if present
    version_str = version_str.lstrip("v")

    # Remove any pre-release suffix (-rc.1, -beta, etc.)
    version_str = re.split(r"[-+]", version_str)[0]

    # Parse into tuple of integers
    try:
        return tuple(int(x) for x in version_str.split("."))
    except ValueError:
        return (0,)


def _is_newer_version(current: str, latest: str) -> bool:
    """
    Check if latest version is newer than current.

    Args:
        current: Current version string
        latest: Latest version string

    Returns:
        True if latest is newer than current
    """
    current_tuple = _parse_version(current)
    latest_tuple = _parse_version(latest)
    return latest_tuple > current_tuple


def _should_check_version() -> bool:
    """
    Determine if we should check for a new version.

    Returns:
        True if enough time has passed since last check
    """
    # Skip in CI environments
    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
        return False

    # Skip if user has disabled update checks
    if os.environ.get("GAUGE_NO_UPDATE_CHECK"):
        return False

    try:
        if VERSION_CACHE_FILE.exists():
            mtime = VERSION_CACHE_FILE.stat().st_mtime
            if time.time() - mtime < VERSION_CHECK_INTERVAL:
                return False
    except OSError:
        pass

    return True


def _read_cached_version() -> Optional[str]:
    """Read the cached latest version if available and fresh."""
    try:
        if VERSION_CACHE_FILE.exists():
            mtime = VERSION_CACHE_FILE.stat().st_mtime
            if time.time() - mtime < VERSION_CHECK_INTERVAL:
                content = VERSION_CACHE_FILE.read_text().strip()
                if content:
                    return content
    except OSError:
        pass
    return None


def _write_cached_version(version: str) -> None:
    """Write the latest version to cache."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        VERSION_CACHE_FILE.write_text(version)
    except OSError:
        pass


def _fetch_latest_release() -> Optional[str]:
    """
    Fetch the latest release version from GitHub.

    Uses GITHUB_TOKEN env var for authentication (required for private repos).

    Returns:
        Latest version string or None if fetch failed
    """
    try:
        import urllib.request
        import json

        from forge_gauge.utils.github_utils import github_api_headers

        request = urllib.request.Request(
            GITHUB_RELEASES_URL,
            headers=github_api_headers(),
        )

        with urllib.request.urlopen(request, timeout=5) as response:
            data = json.loads(response.read().decode())
            tag_name = data.get("tag_name", "")
            if tag_name:
                return tag_name.lstrip("v")
    except Exception as e:
        logger.debug(f"Failed to fetch latest release: {e}")

    return None


def check_for_updates(current_version: str) -> Optional[str]:
    """
    Check if a newer version of Gauge is available.

    This function is designed to be fast and non-disruptive:
    - Returns immediately if checked recently (cached)
    - Uses a short timeout for the HTTP request
    - Never raises exceptions to callers

    Args:
        current_version: Current installed version

    Returns:
        Latest version string if an update is available, None otherwise
    """
    try:
        # Skip if current version is a dev/unknown version
        if current_version in ("unknown", "dev") or "-" in current_version:
            return None

        # Check cache first
        cached_version = _read_cached_version()
        if cached_version:
            if _is_newer_version(current_version, cached_version):
                return cached_version
            return None

        # Skip fetch if we checked recently
        if not _should_check_version():
            return None

        # Fetch latest release
        latest_version = _fetch_latest_release()
        if latest_version:
            _write_cached_version(latest_version)
            if _is_newer_version(current_version, latest_version):
                return latest_version

    except Exception as e:
        logger.debug(f"Version check failed: {e}")

    return None


def print_update_notice(current_version: str, latest_version: str) -> None:
    """
    Print a notice about available updates.

    Args:
        current_version: Current installed version
        latest_version: Latest available version
    """
    print(f"\n  A new version of Gauge is available: {latest_version} (current: {current_version})")
    print("  Run 'gauge update' to update.\n")
