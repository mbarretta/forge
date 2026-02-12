"""FORGE CLI entry point.

Usage:
    forge                           Show help and list available tools
    forge <tool> [args]             Run a tool
    forge <tool> --help             Show tool-specific help
    forge serve                     Start the web server (requires forge-api)
    forge update                    Update FORGE and all plugins
    forge version                   Show FORGE and plugin versions
    forge --version                 Show version (short)
"""

from __future__ import annotations

import argparse
import subprocess
import sys

from forge_core.registry import discover_plugins

FORGE_BANNER = r"""
   ███████╗ ██████╗ ██████╗  ██████╗ ███████╗
   ██╔════╝██╔═══██╗██╔══██╗██╔════╝ ██╔════╝
   █████╗  ██║   ██║██████╔╝██║  ███╗█████╗
   ██╔══╝  ██║   ██║██╔══██╗██║   ██║██╔══╝
   ██║     ╚██████╔╝██║  ██║╚██████╔╝███████╗
   ╚═╝      ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚══════╝
"""

__version__ = "0.1.0"


def show_help(plugins: dict) -> None:
    """Print help with available tools."""
    print(FORGE_BANNER)
    print(f"  FORGE v{__version__} — Chainguard Field Engineering Toolkit\n")
    print("Usage: forge <tool> [options]\n")
    print("Available tools:")
    for name, plugin in sorted(plugins.items()):
        print(f"  {name:<20} {plugin.description}")
    print()
    print("Built-in commands:")
    print(f"  {'update':<20} Update FORGE and all plugins to latest")
    print(f"  {'version':<20} Show FORGE and plugin versions")
    print(f"  {'serve':<20} Start the web server (requires forge-api)")
    print()
    print("Global options:")
    print("  --version, -V        Show version (short)")
    print("  --help, -h           Show this help")
    print()
    print("Use 'forge <tool> --help' for tool-specific options.")


def _show_version(plugins: dict) -> None:
    """Show FORGE version and all installed plugin versions."""
    print(f"FORGE v{__version__}")
    for name, plugin in sorted(plugins.items()):
        print(f"  {name:<20} {plugin.version}")


def _run_update(argv: list[str]) -> int:
    """Update FORGE and all plugins via uv tool upgrade."""
    parser = argparse.ArgumentParser(prog="forge update")
    parser.add_argument(
        "--dry-run", action="store_true", help="Check for updates without applying"
    )
    args = parser.parse_args(argv)

    repo_url = "git+https://github.com/chainguard/forge"
    cmd = ["uv", "tool", "upgrade", "forge", "--from", repo_url]

    if args.dry_run:
        print("Checking for updates...")
        # uv tool upgrade with --dry-run is not supported, so we show current state
        print("Current versions:")
        plugins = discover_plugins()
        _show_version(plugins)
        return 0

    print("Updating FORGE...")
    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        print("Update failed.", file=sys.stderr)
        return 1

    # Show updated versions
    print()
    plugins = discover_plugins()
    _show_version(plugins)
    return 0


def _launch_server(argv: list[str]) -> None:
    """Start the FORGE API server. Requires forge-api to be installed."""
    try:
        from forge_api.app import create_app

        import uvicorn
    except ImportError:
        print("Error: forge-api is not installed.")
        print("Install it with: uv pip install -e packages/forge-api")
        sys.exit(1)

    # Parse serve-specific args
    parser = argparse.ArgumentParser(prog="forge serve")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Bind port (default: 8080)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for dev")
    args = parser.parse_args(argv)

    app = create_app()
    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)


def main() -> None:
    """Main entry point."""
    plugins = discover_plugins()

    # No arguments — show help
    if len(sys.argv) < 2:
        show_help(plugins)
        sys.exit(0)

    command = sys.argv[1]

    # Global flags
    if command in ("-h", "--help"):
        show_help(plugins)
        sys.exit(0)

    if command in ("-V", "--version"):
        print(f"forge {__version__}")
        sys.exit(0)

    # Built-in commands (not plugins)
    if command == "version":
        _show_version(plugins)
        sys.exit(0)

    if command == "update":
        sys.exit(_run_update(sys.argv[2:]))

    if command == "serve":
        _launch_server(sys.argv[2:])
        return

    # Tool dispatch
    if command not in plugins:
        print(f"Unknown tool: {command}")
        print()
        show_help(plugins)
        sys.exit(1)

    plugin = plugins[command]

    # Build argparse from plugin params
    parser = argparse.ArgumentParser(
        prog=f"forge {plugin.name}",
        description=plugin.description,
    )

    from forge_cli.runner import add_params_to_parser, run_plugin

    add_params_to_parser(parser, plugin.get_params())

    # Remove the tool name from argv so argparse sees only the tool's args
    args = parser.parse_args(sys.argv[2:])
    exit_code = run_plugin(plugin, vars(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
