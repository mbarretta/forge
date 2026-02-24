"""BinaryPlugin adapter: wraps any binary that speaks the forge stdio protocol.

The protocol uses two flags:

  Introspection:
    binary --forge-introspect
    stdout → {"name":"...", "description":"...", "version":"...",
               "requires_auth":false, "params":[...]}

  Execution:
    binary --forge-run '{"param1":"val"}'
    stderr → newline-delimited {"progress":0.5, "message":"Scanning..."}
    stdout → {"status":"success", "summary":"...", "data":{}, "artifacts":{}}

This module uses only the Python standard library so that forge-core remains
dependency-free.
"""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING, Any

from forge_core.plugin import ResultStatus, ToolParam, ToolResult

if TYPE_CHECKING:
    from forge_core.context import ExecutionContext


class BinaryPlugin:
    """ToolPlugin adapter for any binary that speaks the forge stdio protocol."""

    def __init__(self, binary_path: str, introspect_data: dict[str, Any]) -> None:
        self.name: str = introspect_data["name"]
        self.description: str = introspect_data["description"]
        self.version: str = introspect_data["version"]
        self.requires_auth: bool = introspect_data.get("requires_auth", False)
        self._binary = binary_path
        self._raw_params: list[dict[str, Any]] = introspect_data.get("params", [])

    def get_params(self) -> list[ToolParam]:
        return [ToolParam(**p) for p in self._raw_params]

    def run(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        proc = subprocess.Popen(
            [self._binary, "--forge-run", json.dumps(args)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        if proc.stderr is None:
            raise RuntimeError("subprocess.Popen stderr is None despite stderr=PIPE")
        for line in proc.stderr:
            if not stripped:
                continue
            try:
                event = json.loads(stripped)
                ctx.progress(
                    float(event.get("progress", 0.0)),
                    str(event.get("message", "")),
                )
            except json.JSONDecodeError:
                pass  # pass non-JSON stderr lines silently
            if ctx.is_cancelled:
                proc.kill()
                return ToolResult(status=ResultStatus.CANCELLED, summary="Cancelled by user")

        stdout, _ = proc.communicate()

        try:
            result = json.loads(stdout)
        except json.JSONDecodeError:
            return ToolResult(
                status=ResultStatus.FAILURE,
                summary=f"Binary returned invalid JSON: {stdout[:200]}",
            )

        try:
            status = ResultStatus(result.get("status", "failure"))
        except ValueError:
            status = ResultStatus.FAILURE

        return ToolResult(
            status=status,
            summary=result.get("summary", ""),
            data=result.get("data", {}),
            artifacts=result.get("artifacts", {}),
        )
