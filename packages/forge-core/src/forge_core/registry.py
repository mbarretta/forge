"""Discover and load ToolPlugin implementations via entry_points."""

from __future__ import annotations

import importlib.metadata
import logging
from typing import Any

from forge_core.plugin import ToolPlugin

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "forge.plugins"


def discover_plugins() -> dict[str, ToolPlugin]:
    """Find all installed packages that declare a forge.plugins entry point.

    Each entry point must resolve to a callable that returns a ToolPlugin instance.
    Convention: the entry point value is a module-level function called `create_plugin`.

    Example pyproject.toml entry in a tool plugin package:

        [project.entry-points."forge.plugins"]
        gauge = "forge_gauge:create_plugin"

    Returns:
        Dict mapping plugin name to plugin instance.
    """
    plugins: dict[str, ToolPlugin] = {}

    eps = importlib.metadata.entry_points()
    forge_eps = eps.select(group=ENTRY_POINT_GROUP)

    for ep in forge_eps:
        try:
            factory = ep.load()
            plugin = factory()

            if not isinstance(plugin, ToolPlugin):
                logger.warning(
                    "Entry point '%s' returned %s, expected ToolPlugin. Skipping.",
                    ep.name,
                    type(plugin).__name__,
                )
                continue

            if plugin.name in plugins:
                logger.warning(
                    "Duplicate plugin name '%s' from entry point '%s'. Skipping.",
                    plugin.name,
                    ep.name,
                )
                continue

            plugins[plugin.name] = plugin
            logger.info("Loaded plugin: %s v%s", plugin.name, plugin.version)

        except Exception:
            logger.exception("Failed to load plugin from entry point '%s'", ep.name)

    return plugins
