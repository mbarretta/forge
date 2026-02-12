"""Integrations with external services."""

from forge_gauge.integrations.kev_catalog import KEVCatalog
from forge_gauge.integrations.chainguard_api import ChainguardAPI

__all__ = [
    "KEVCatalog",
    "ChainguardAPI",
]
