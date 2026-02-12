"""Run a plugin in-process with console progress output."""

from __future__ import annotations

import sys
import threading
from typing import Any

from forge_core.auth import get_chainctl_token
from forge_core.context import ExecutionContext
from forge_core.plugin import ResultStatus, ToolParam, ToolPlugin

# Map ToolParam.type strings to Python types for argparse
TYPE_MAP: dict[str, type] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
}


def add_params_to_parser(parser, params: list[ToolParam]) -> None:
    """Add ToolParam declarations to an argparse.ArgumentParser.

    Args:
        parser: The ArgumentParser to add arguments to.
        params: List of ToolParam from plugin.get_params().
    """
    for param in params:
        flag = f"--{param.name}"
        kwargs: dict[str, Any] = {
            "help": param.description,
        }

        if param.type == "bool":
            # Boolean params become --flag / --no-flag
            kwargs["action"] = "store_true"
            kwargs["default"] = param.default if param.default is not None else False
        else:
            kwargs["type"] = TYPE_MAP.get(param.type, str)
            kwargs["required"] = param.required
            if param.default is not None:
                kwargs["default"] = param.default
            if param.choices:
                kwargs["choices"] = param.choices

        parser.add_argument(flag, **kwargs)


def _console_progress(fraction: float, message: str) -> None:
    """Print progress to stderr."""
    pct = int(fraction * 100)
    print(f"  [{pct:3d}%] {message}", file=sys.stderr, flush=True)


def run_plugin(plugin: ToolPlugin, args: dict[str, Any]) -> int:
    """Run a plugin in-process and return an exit code.

    Args:
        plugin: The plugin to run.
        args: Dict of parsed arguments.

    Returns:
        0 on success, 1 on failure.
    """
    # Get auth token
    try:
        token = get_chainctl_token()
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    ctx = ExecutionContext(
        auth_token=token,
        on_progress=_console_progress,
        cancel_event=threading.Event(),
    )

    try:
        result = plugin.run(args, ctx)
    except KeyboardInterrupt:
        ctx.cancel_event.set()
        print("\nCancelled.", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Print result summary
    print(f"\n{result.summary}")

    if result.artifacts:
        print("\nArtifacts:")
        for name, path in result.artifacts.items():
            print(f"  {name}: {path}")

    return 0 if result.status == ResultStatus.SUCCESS else 1
