"""Hello world test plugin."""

from __future__ import annotations

import time
from typing import Any

from forge_core.context import ExecutionContext
from forge_core.plugin import ResultStatus, ToolParam, ToolResult


class HelloPlugin:
    """Simple test plugin to verify FORGE plugin system works."""

    name = "hello"
    description = "Hello world test plugin"
    version = "0.1.0"
    requires_auth = False  # runs without chainctl installed

    def get_params(self) -> list[ToolParam]:
        return [
            ToolParam(name="name", description="Name to greet", required=True),
            ToolParam(
                name="count", description="Number of greetings", type="int", default=1
            ),
            ToolParam(name="verbose", description="Verbose output", type="bool"),
        ]

    def run(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        name = args["name"]
        count = args.get("count", 1)
        verbose = args.get("verbose", False)

        ctx.progress(0.0, "Starting greetings")

        greetings = []
        for i in range(count):
            if ctx.is_cancelled:
                return ToolResult(
                    status=ResultStatus.CANCELLED, summary="Cancelled by user"
                )

            greeting = f"Hello, {name}!"
            greetings.append(greeting)

            if verbose:
                ctx.progress((i + 1) / count, f"Greeting {i + 1}/{count}: {greeting}")
            else:
                ctx.progress((i + 1) / count, f"Progress: {i + 1}/{count}")

            # Simulate some work
            time.sleep(0.1)

        ctx.progress(1.0, "Done")

        return ToolResult(
            status=ResultStatus.SUCCESS,
            summary=f"Generated {count} greeting(s) for {name}",
            data={"name": name, "count": count, "greetings": greetings},
        )
