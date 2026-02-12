"""FORGE plugin: hello world test."""

from forge_hello.plugin import HelloPlugin


def create_plugin() -> HelloPlugin:
    """Entry point for FORGE plugin discovery."""
    return HelloPlugin()
