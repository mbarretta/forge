"""
Tests for plugin discovery.

Verifies that plugins are correctly discovered from the filesystem.
"""

from pathlib import Path

from forge_gauge.core.plugin_registry import PluginRegistry


class TestPluginDiscovery:
    """Tests that discover_plugins() finds plugins from the filesystem."""

    def test_discovers_plugins_from_filesystem(self):
        """Plugins are discovered from the filesystem."""
        registry = PluginRegistry()
        registry.discover_plugins()
        # gauge-core should always be registered
        assert "gauge-core" in registry.list_plugins()

    def test_discovers_core_commands(self):
        """Core commands should be available after discovery."""
        registry = PluginRegistry()
        registry.discover_plugins()
        assert registry.get_command("scan") is not None
        assert registry.get_command("update") is not None
        assert registry.get_command("match") is not None
