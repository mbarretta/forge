"""Discover and load ToolPlugin implementations via entry_points."""

from __future__ import annotations

import importlib.metadata
import json
import logging
from pathlib import Path

from forge_core.plugin import ToolPlugin

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "forge.plugins"


def discover_plugins() -> dict[str, ToolPlugin]:
    """Find all installed packages that declare a forge.plugins entry point,
    plus any binary plugins cached at ~/.config/forge/binary-plugins.json.

    Each Python entry point must resolve to a callable that returns a ToolPlugin
    instance. Convention: the entry point value is a namespaced module path:

        [project.entry-points."forge.plugins"]
        gauge = "gauge.forge_plugin:create_plugin"

    Returns:
        Dict mapping plugin name to plugin instance.
    """
    plugins: dict[str, ToolPlugin] = {}

    # --- Python entry-point plugins ---
    eps = importlib.metadata.entry_points()
    forge_eps = eps.select(group=ENTRY_POINT_GROUP)

    for ep in forge_eps:
        try:
            # Warn on the reserved bare module name that causes collisions (B1)
            module_path = ep.value.split(":")[0]
            if module_path == "forge_plugin":
                logger.warning(
                    "Plugin '%s' uses the reserved module name 'forge_plugin'. "
                    "Use a namespaced path like '%s.forge_plugin:create_plugin' "
                    "to avoid collisions with other plugins.",
                    ep.name,
                    ep.name,
                )

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

    # --- Binary-protocol plugins ---
    for name, plugin in _discover_binary_plugins().items():
        if name in plugins:
            logger.warning(
                "Binary plugin '%s' conflicts with an existing Python plugin. Skipping.",
                name,
            )
        else:
            plugins[name] = plugin

    return plugins


def _discover_binary_plugins() -> dict[str, ToolPlugin]:
    """Load binary plugins from ~/.config/forge/binary-plugins.json."""
    from forge_core.binary_plugin import BinaryPlugin

    cache_path = Path.home() / ".config" / "forge" / "binary-plugins.json"
    if not cache_path.exists():
        return {}

    try:
        cache = json.loads(cache_path.read_text())
    except Exception:
        logger.warning("Failed to load binary plugin cache at %s", cache_path)
        return {}

    plugins: dict[str, ToolPlugin] = {}
    for name, data in cache.items():
        try:
            binary_path = data["binary_path"]
            introspect_data = data["introspect_data"]
            plugin = BinaryPlugin(binary_path, introspect_data)
            plugins[plugin.name] = plugin
            logger.info("Loaded binary plugin: %s v%s", plugin.name, plugin.version)
        except Exception:
            logger.exception("Failed to load binary plugin '%s' from cache", name)

    return plugins
