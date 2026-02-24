"""Plugin protocol that all FORGE tools must implement."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from forge_core.context import ExecutionContext


class ResultStatus(Enum):
    """Outcome of a tool run."""

    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ToolResult:
    """Returned by every plugin run.

    Attributes:
        status: Overall outcome.
        summary: Human-readable one-line summary.
        data: Arbitrary structured output (must be JSON-serializable).
        artifacts: Mapping of artifact name to file path for any files
                   the tool produced (reports, CSVs, SBOMs, etc.).
    """

    status: ResultStatus
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)


ParamType = Literal["str", "int", "float", "bool", "path"]


@dataclass(frozen=True)
class ToolParam:
    """Declares a parameter that the tool accepts.

    Used by the CLI to build argparse arguments.

    Attributes:
        name: Parameter name (used as CLI flag --name and JSON key).
        description: Help text.
        type: Python type name: "str", "int", "float", "bool", or "path".
        required: Whether the parameter must be provided.
        default: Default value if not required.
        choices: Optional list of allowed values.
    """

    name: str
    description: str
    type: ParamType = "str"
    required: bool = False
    default: Any = None
    choices: list[str] | None = None


@runtime_checkable
class ToolPlugin(Protocol):
    """Protocol that every FORGE tool must implement.

    A tool plugin provides:
    - Metadata (name, description, version, requires_auth)
    - Parameter declarations (so the CLI can auto-generate interfaces)
    - A run method that does the actual work

    Example implementation:

        class MyPlugin:
            name = "my-tool"
            description = "Does something useful"
            version = "1.0.0"
            requires_auth = True   # set False if chainctl is not needed

            def get_params(self) -> list[ToolParam]:
                return [
                    ToolParam(name="org", description="Target org", required=True),
                    ToolParam(name="limit", description="Max items", type="int", default=0),
                ]

            def run(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
                org = args["org"]
                ctx.progress(0.0, f"Starting scan of {org}")
                # ... do work ...
                ctx.progress(1.0, "Done")
                return ToolResult(status=ResultStatus.SUCCESS, summary="Scanned 42 images")
    """

    name: str
    description: str
    version: str
    requires_auth: bool

    def get_params(self) -> list[ToolParam]:
        """Declare the parameters this tool accepts."""
        ...

    def run(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        """Execute the tool.

        Args:
            args: Dictionary of parameter values. Keys match ToolParam.name.
                  Values are already coerced to the declared types.
            ctx: Execution context providing auth, progress reporting,
                 and cancellation.

        Returns:
            ToolResult with status, summary, optional data and artifacts.
        """
        ...
