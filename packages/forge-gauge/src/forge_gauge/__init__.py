"""FORGE plugin: gauge - container vulnerability scanning and image matching."""

from forge_gauge.plugin import GaugePlugin


def create_plugin() -> GaugePlugin:
    """Entry point for FORGE plugin discovery."""
    return GaugePlugin()
