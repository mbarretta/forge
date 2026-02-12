"""
FORGE coverage checking plugin for Python and JavaScript packages.

Checks package availability in Chainguard's Python and JavaScript registries.
"""

from forge_coverage.plugin import CoveragePlugin


def create_plugin() -> CoveragePlugin:
    """Entry point for FORGE plugin discovery."""
    return CoveragePlugin()


__all__ = ["create_plugin", "CoveragePlugin"]
