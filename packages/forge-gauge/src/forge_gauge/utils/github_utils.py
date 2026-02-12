"""
Shared GitHub utilities for authentication and token management.

This module provides common GitHub-related functions used across integrations.
"""

import logging
import os
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)


def get_github_token_from_gh_cli() -> Optional[str]:
    """
    Attempt to get GitHub token from gh CLI.

    Returns:
        GitHub token if gh CLI is installed and authenticated, None otherwise
    """
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            token = result.stdout.strip()
            if token:
                logger.debug("Using GitHub token from gh CLI")
                return token
    except FileNotFoundError:
        logger.debug("gh CLI not found")
    except subprocess.TimeoutExpired:
        logger.debug("gh CLI token fetch timed out")
    except Exception as e:
        logger.debug(f"Failed to get token from gh CLI: {e}")

    return None


def github_api_headers(accept: str = "application/vnd.github.v3+json") -> dict[str, str]:
    """Build HTTP headers for GitHub API requests with token auth.

    Token resolution order: GITHUB_TOKEN env var, then gh CLI.
    """
    headers = {"Accept": accept}
    token = os.environ.get("GITHUB_TOKEN") or get_github_token_from_gh_cli()
    if token:
        headers["Authorization"] = f"token {token}"
    return headers
