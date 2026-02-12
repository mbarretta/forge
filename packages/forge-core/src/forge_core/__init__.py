"""FORGE Core — Plugin protocol and shared utilities."""

from forge_core.context import ExecutionContext
from forge_core.plugin import ResultStatus, ToolParam, ToolPlugin, ToolResult

__all__ = [
    "ExecutionContext",
    "ResultStatus",
    "ToolParam",
    "ToolPlugin",
    "ToolResult",
]
