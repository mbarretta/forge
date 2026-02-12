"""Authentication helpers for Chainguard tools."""

from __future__ import annotations

import shutil
import subprocess


def get_chainctl_token(timeout: int = 30) -> str:
    """Get an auth token from chainctl.

    Returns:
        Token string.

    Raises:
        RuntimeError: If chainctl is not installed or not authenticated.
    """
    if shutil.which("chainctl") is None:
        raise RuntimeError(
            "chainctl is not installed. "
            "Install from https://edu.chainguard.dev/chainguard/administration/how-to-install-chainctl/"
        )

    try:
        result = subprocess.run(
            ["chainctl", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"chainctl auth failed. Run 'chainctl auth login' first. Error: {e.stderr}"
        ) from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"chainctl auth timed out after {timeout}s") from e


def check_tool_available(tool_name: str) -> bool:
    """Check if a CLI tool is available on PATH."""
    return shutil.which(tool_name) is not None
