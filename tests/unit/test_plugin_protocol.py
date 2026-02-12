"""Tests for the ToolPlugin protocol."""

from forge_core.plugin import ResultStatus, ToolParam, ToolPlugin, ToolResult


def test_tool_param_creation():
    """Test ToolParam creation."""
    param = ToolParam(
        name="test",
        description="Test parameter",
        type="str",
        required=True,
        default="default",
        choices=["a", "b", "c"],
    )

    assert param.name == "test"
    assert param.description == "Test parameter"
    assert param.type == "str"
    assert param.required is True
    assert param.default == "default"
    assert param.choices == ["a", "b", "c"]


def test_tool_param_defaults():
    """Test ToolParam default values."""
    param = ToolParam(name="test", description="Test parameter")

    assert param.type == "str"
    assert param.required is False
    assert param.default is None
    assert param.choices is None


def test_tool_result_creation():
    """Test ToolResult creation."""
    result = ToolResult(
        status=ResultStatus.SUCCESS,
        summary="Test completed",
        data={"count": 42},
        artifacts={"report": "/path/to/report.txt"},
    )

    assert result.status == ResultStatus.SUCCESS
    assert result.summary == "Test completed"
    assert result.data == {"count": 42}
    assert result.artifacts == {"report": "/path/to/report.txt"}


def test_tool_result_defaults():
    """Test ToolResult default values."""
    result = ToolResult(status=ResultStatus.SUCCESS, summary="Done")

    assert result.data == {}
    assert result.artifacts == {}


def test_plugin_protocol_compliance(mock_plugin):
    """Test that mock plugin implements ToolPlugin protocol."""
    assert isinstance(mock_plugin, ToolPlugin)
    assert hasattr(mock_plugin, "name")
    assert hasattr(mock_plugin, "description")
    assert hasattr(mock_plugin, "version")
    assert callable(mock_plugin.get_params)
    assert callable(mock_plugin.run)


def test_plugin_get_params(mock_plugin):
    """Test plugin parameter declaration."""
    params = mock_plugin.get_params()

    assert len(params) == 1
    assert params[0].name == "input"
    assert params[0].required is True


def test_plugin_run(mock_plugin):
    """Test plugin execution."""
    from forge_core.context import ExecutionContext

    ctx = ExecutionContext()
    args = {"input": "test-value"}

    result = mock_plugin.run(args, ctx)

    assert result.status == ResultStatus.SUCCESS
    assert "test-value" in result.summary
    assert result.data["input"] == "test-value"
