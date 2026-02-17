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

from forge_cli import __version__
from forge_core.registry import discover_plugins

FORGE_BANNER = r"""
   ███████╗ ██████╗ ██████╗  ██████╗ ███████╗
   ██╔════╝██╔═══██╗██╔══██╗██╔════╝ ██╔════╝
   █████╗  ██║   ██║██████╔╝██║  ███╗█████╗
   ██╔══╝  ██║   ██║██╔══██╗██║   ██║██╔══╝
   ██║     ╚██████╔╝██║  ██║╚██████╔╝███████╗
   ╚═╝      ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚══════╝
"""


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
    print(f"  {'plugin':<20} Manage external plugins (install, update, list)")
    print()
    print("Global options:")
    print("  --version, -V        Show version (short)")
    print("  --help, -h           Show this help")
    print()
    print("Use 'forge <tool> --help' for tool-specific options.")
    print("Use 'forge plugin --help' for plugin management.")


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


def _manage_plugins(argv: list[str]) -> int:
    """Manage external plugins."""
    from forge_cli.plugin_manager import PluginManager, format_plugin_list

    parser = argparse.ArgumentParser(
        prog="forge plugin",
        description="Manage external FORGE plugins from git repositories",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Plugin management commands")

    # list command
    list_parser = subparsers.add_parser("list", help="List available external plugins")
    list_parser.add_argument(
        "--tag", help="Filter plugins by tag (e.g., security, compliance)"
    )
    list_parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show detailed plugin information"
    )

    # install command
    install_parser = subparsers.add_parser(
        "install", help="Install an external plugin from the registry"
    )
    install_parser.add_argument("name", help="Plugin name from registry")
    install_parser.add_argument(
        "--ref", help="Git ref (tag/branch/commit) to install (overrides registry default)"
    )

    # update command
    update_parser = subparsers.add_parser("update", help="Update an external plugin")
    update_parser.add_argument("name", nargs="?", help="Plugin name (omit to update all)")
    update_parser.add_argument(
        "--all", action="store_true", help="Update all external plugins"
    )
    update_parser.add_argument(
        "--ref", help="Git ref to update to (overrides registry default)"
    )

    # remove command
    remove_parser = subparsers.add_parser("remove", help="Remove an external plugin")
    remove_parser.add_argument("name", help="Plugin name from registry")

    args = parser.parse_args(argv)

    if not args.subcommand:
        parser.print_help()
        return 0

    manager = PluginManager()

    if args.subcommand == "list":
        plugins = manager.list_available(tag_filter=args.tag)
        print(format_plugin_list(plugins, verbose=args.verbose))
        return 0

    if args.subcommand == "install":
        return manager.install(args.name, ref=args.ref)

    if args.subcommand == "update":
        if args.all or not args.name:
            return manager.update_all()
        return manager.update(args.name, ref=args.ref)

    if args.subcommand == "remove":
        return manager.remove(args.name)

    return 0


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

    if command == "plugin":
        sys.exit(_manage_plugins(sys.argv[2:]))

    # Tool dispatch
    if command not in plugins:
        print(f"Unknown tool: {command}")
        print()
        show_help(plugins)
        sys.exit(1)

    plugin = plugins[command]

    from forge_cli.runner import add_params_to_parser, run_plugin, detect_subcommand

    # Check if plugin supports subcommands
    params = plugin.get_params()
    subcommand_param = detect_subcommand(params)

    if subcommand_param:
        # Plugin uses subcommands (e.g., forge gauge scan)
        if len(sys.argv) < 3 or sys.argv[2].startswith("-"):
            # No subcommand provided or looks like a flag
            print(f"Error: {plugin.name} requires a subcommand")
            print(f"Available commands: {', '.join(subcommand_param.choices)}")
            print(f"\nUsage: forge {plugin.name} <command> [options]")
            sys.exit(1)

        subcommand = sys.argv[2]

        # Validate subcommand
        if subcommand_param.choices and subcommand not in subcommand_param.choices:
            print(f"Unknown {plugin.name} command: {subcommand}")
            print(f"Available commands: {', '.join(subcommand_param.choices)}")
            sys.exit(1)

        # Build parser without the command parameter (it's positional)
        parser = argparse.ArgumentParser(
            prog=f"forge {plugin.name} {subcommand}",
            description=plugin.description,
        )

        # Add all params except the command param
        other_params = [p for p in params if p.name != subcommand_param.name]
        add_params_to_parser(parser, other_params)

        # Parse args starting after the subcommand
        args = parser.parse_args(sys.argv[3:])
        args_dict = vars(args)

        # Add the subcommand back to args
        args_dict[subcommand_param.name] = subcommand

        exit_code = run_plugin(plugin, args_dict)
        sys.exit(exit_code)
    else:
        # Standard plugin without subcommands
        # Usage: forge coverage --requirements-file file.txt
        parser = argparse.ArgumentParser(
            prog=f"forge {plugin.name}",
            description=plugin.description,
        )

        add_params_to_parser(parser, params)

        # Remove the tool name from argv so argparse sees only the tool's args
        args = parser.parse_args(sys.argv[2:])
        exit_code = run_plugin(plugin, vars(args))
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
