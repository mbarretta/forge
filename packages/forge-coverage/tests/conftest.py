"""
Shared pytest fixtures and configuration for forge-coverage tests.
"""

import pytest
from pathlib import Path

from forge_core.context import ExecutionContext
from forge_coverage import create_plugin


# Shared fixtures directory
@pytest.fixture
def fixtures_dir():
    """Path to test fixtures directory."""
    return Path(__file__).parent / "fixtures"


# Shared plugin instance
@pytest.fixture
def plugin():
    """Create a coverage plugin instance."""
    return create_plugin()


# Shared execution context
@pytest.fixture
def ctx():
    """Create an execution context."""
    return ExecutionContext()
