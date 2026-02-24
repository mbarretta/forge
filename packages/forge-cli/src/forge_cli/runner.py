"""Run a plugin in-process with console progress output."""

from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path
from typing import Any

import yaml

from forge_core.auth import get_chainctl_token
from forge_core.context import ExecutionContext
from forge_core.plugin import ResultStatus, ToolParam, ToolPlugin

# Map ToolParam.type strings to Python types for argparse
TYPE_MAP: dict[str, type] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "path": Path,
}

# Exit codes per status
_STATUS_EXIT_CODES: dict[ResultStatus, int] = {
    ResultStatus.SUCCESS: 0,
    ResultStatus.FAILURE: 1,
    ResultStatus.PARTIAL: 2,
    ResultStatus.CANCELLED: 130,
}


def detect_subcommand(params: list[ToolParam]) -> ToolParam | None:
    """Detect if a plugin uses subcommands.

    Returns the "command" parameter if it exists and has choices, otherwise None.
    """
    for param in params:
        if param.name == "command" and param.choices:
            return param
    return None


def add_params_to_parser(
    parser: argparse.ArgumentParser, params: list[ToolParam]
) -> None:
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
            kwargs["action"] = argparse.BooleanOptionalAction
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


def _load_config() -> dict:
    """Load forge config from ~/.config/forge/config.yaml, if present."""
    config_path = Path.home() / ".config" / "forge" / "config.yaml"
    if config_path.exists():
        try:
            return yaml.safe_load(config_path.read_text()) or {}
        except Exception:
            pass
    return {}


def run_plugin(plugin: ToolPlugin, args: dict[str, Any]) -> int:
    """Run a plugin in-process and return an exit code.

    Args:
        plugin: The plugin to run.
        args: Dict of parsed arguments.

    Returns:
        0 on SUCCESS, 1 on FAILURE, 2 on PARTIAL, 130 on CANCELLED.
    """
    # Only fetch auth token when the plugin declares it needs one
    auth_token = ""
    if getattr(plugin, "requires_auth", True):
        try:
            auth_token = get_chainctl_token()
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    ctx = ExecutionContext(
        auth_token=auth_token,
        config=_load_config(),
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

    # Print result — show "output" from data if present, else fall back to summary
    output = result.data.get("output") if result.data else None
    if output:
        print(f"\n{output}")
    else:
        print(f"\n{result.summary}")

    if result.artifacts:
        print("\nArtifacts:")
        for name, path in result.artifacts.items():
            print(f"  {name}: {path}")

    return _STATUS_EXIT_CODES.get(result.status, 1)
