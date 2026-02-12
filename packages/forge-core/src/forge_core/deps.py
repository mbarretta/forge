"""Check external tool dependencies."""

from __future__ import annotations

import shutil
from dataclasses import dataclass


@dataclass(frozen=True)
class DependencyCheck:
    """Result of checking a required external tool."""

    name: str
    available: bool
    path: str | None


def check_dependencies(required: list[str]) -> list[DependencyCheck]:
    """Check that all required CLI tools are installed.

    Args:
        required: List of tool names (e.g. ["chainctl", "crane", "cosign"]).

    Returns:
        List of DependencyCheck results.
    """
    results = []
    for tool in required:
        path = shutil.which(tool)
        results.append(DependencyCheck(name=tool, available=path is not None, path=path))
    return results


def assert_dependencies(required: list[str]) -> None:
    """Check dependencies and raise if any are missing.

    Raises:
        RuntimeError: With list of missing tools.
    """
    checks = check_dependencies(required)
    missing = [c.name for c in checks if not c.available]
    if missing:
        raise RuntimeError(f"Missing required tools: {', '.join(missing)}")
