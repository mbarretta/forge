"""FORGE plugin: provenance - verify Chainguard image delivery authenticity."""

from forge_provenance.plugin import ProvenancePlugin


def create_plugin() -> ProvenancePlugin:
    """Entry point for FORGE plugin discovery."""
    return ProvenancePlugin()
