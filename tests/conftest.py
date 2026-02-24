"""Pytest configuration and fixtures."""

import pytest


@pytest.fixture
def sample_tool_params():
    """Sample tool parameters for testing."""
    from forge_core.plugin import ToolParam

    return [
        ToolParam(name="org", description="Organization name", required=True),
        ToolParam(name="limit", description="Max items", type="int", default=10),
        ToolParam(name="verbose", description="Verbose output", type="bool"),
    ]


@pytest.fixture
def mock_plugin():
    """Mock plugin for testing."""
    from forge_core.plugin import ToolParam, ToolResult, ResultStatus

    class MockPlugin:
        name = "mock"
        description = "Mock plugin for testing"
        version = "0.1.0"
        requires_auth = False

        def get_params(self):
            return [
                ToolParam(name="input", description="Input value", required=True),
            ]

        def run(self, args, ctx):
            return ToolResult(
                status=ResultStatus.SUCCESS,
                summary=f"Processed: {args['input']}",
                data={"input": args["input"]},
            )

    return MockPlugin()
