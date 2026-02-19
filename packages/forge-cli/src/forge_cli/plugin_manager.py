"""Plugin management for external FORGE plugins.

Manages installation, updates, and removal of external plugins from git repositories.
Uses UV for git-based package installation with support for private GitHub repos.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from forge_cli.system_deps import install_system_deps, parse_system_deps


class PluginManager:
    """Manages external FORGE plugins from git repositories."""

    def __init__(self, registry_path: Path | None = None):
        """Initialize plugin manager.

        Args:
            registry_path: Path to plugins-registry.yaml. If None, searches for it
                          in the FORGE root directory.
        """
        if registry_path is None:
            if env_path := os.environ.get("FORGE_PLUGIN_REGISTRY"):
                registry_path = Path(env_path)
            else:
                # Walk up from this file to find the FORGE root containing the registry.
                # Expected layout: packages/forge-cli/src/forge_cli/plugin_manager.py
                registry_path = Path(__file__).parents[4] / "plugins-registry.yaml"

        self.registry_path = registry_path
        self._registry: dict[str, dict[str, Any]] | None = None

    def _load_registry(self) -> dict[str, dict[str, Any]]:
        """Load plugin registry from YAML file (result is cached)."""
        if self._registry is not None:
            return self._registry

        if not self.registry_path.exists():
            print(f"Warning: Plugin registry not found at {self.registry_path}", file=sys.stderr)
            self._registry = {}
            return self._registry

        try:
            with open(self.registry_path) as f:
                data = yaml.safe_load(f)
                self._registry = data.get("external_plugins", {}) if data else {}
                return self._registry
        except Exception as e:
            print(f"Error loading plugin registry: {e}", file=sys.stderr)
            self._registry = {}
            return self._registry

    def _resolve_plugin(self, name: str) -> dict[str, Any] | None:
        """Look up a plugin by name, printing an error if not found.

        Returns:
            Plugin info dict, or None if the plugin is not in the registry.
        """
        registry = self._load_registry()
        if name in registry:
            return registry[name]

        print(f"Error: Plugin '{name}' not found in registry", file=sys.stderr)
        if registry:
            print(f"\nAvailable plugins: {', '.join(sorted(registry))}", file=sys.stderr)
        return None

    @staticmethod
    def _run_uv(args: list[str]) -> int | None:
        """Run a UV command, returning the exit code or None if UV is not installed."""
        try:
            result = subprocess.run(["uv", *args], capture_output=False, check=False)
            return result.returncode
        except FileNotFoundError:
            print(
                "Error: 'uv' command not found. Please install UV first:\n"
                "  curl -LsSf https://astral.sh/uv/install.sh | sh",
                file=sys.stderr,
            )
            return None

    def list_available(self, tag_filter: str | None = None) -> dict[str, dict[str, Any]]:
        """List available external plugins from registry.

        Args:
            tag_filter: Optional tag to filter plugins by.

        Returns:
            Dict mapping plugin name to plugin info.
        """
        registry = self._load_registry()

        if tag_filter:
            return {
                name: info
                for name, info in registry.items()
                if tag_filter in info.get("tags", [])
            }

        return registry

    def install(self, name: str, ref: str | None = None, strict: bool = False) -> int:
        """Install an external plugin from the registry.

        Args:
            name: Plugin name from registry.
            ref: Optional git ref (tag/branch/commit) to install. Overrides registry default.
            strict: If True, return non-zero when any system dependency fails to install.

        Returns:
            Exit code: 0 on success, non-zero on failure.
        """
        plugin_info = self._resolve_plugin(name)
        if plugin_info is None:
            return 1

        git_url = plugin_info["source"]
        is_private = plugin_info.get("private", False)

        # Use provided ref, or fall back to registry default
        ref_to_use = ref or plugin_info.get("ref")
        if ref_to_use:
            git_url = f"{git_url}@{ref_to_use}"

        print(f"Installing plugin '{name}' from {git_url}...")

        if is_private:
            print(
                "\nNote: This is a private repository. Ensure you have access via SSH key or GitHub token.",
                file=sys.stderr,
            )

        specs = parse_system_deps(plugin_info)
        system_dep_failures = []
        if specs:
            print(f"\nInstalling system dependencies for '{name}'...")
            for r in install_system_deps(specs):
                if r.already_installed:
                    print(f"  {r.spec.binary}: already installed, skipping")
                elif r.success:
                    print(f"  {r.spec.binary}: installed via {r.spec.manager}")
                else:
                    system_dep_failures.append(r)
                    print(f"  Warning: {r.spec.binary}: {r.error_message}", file=sys.stderr)

        rc = self._run_uv(["pip", "install", git_url])
        if rc is None:
            return 1

        if rc != 0:
            print(f"\nError: Failed to install plugin '{name}'", file=sys.stderr)
            if is_private:
                print(
                    "\nAuthentication help:\n"
                    "  - For SSH: Ensure your SSH key is added to GitHub (https://github.com/settings/keys)\n"
                    "  - For HTTPS: Configure git credentials (git config --global credential.helper store)\n"
                    "  - Test access: gh repo view <org>/<repo>",
                    file=sys.stderr,
                )
            return rc

        print(f"\n✓ Plugin '{name}' installed successfully")
        print(f"\nUsage: forge {plugin_info['package']} --help")

        if system_dep_failures:
            print(f"\nWarning: '{name}' installed but these system deps need manual setup:")
            for r in system_dep_failures:
                print(f"  {r.spec.binary} ({r.spec.manager}): {r.spec.package}")
                if r.error_message:
                    for line in r.error_message.splitlines():
                        print(f"    {line}")
            print("\nThe plugin is installed but may not function until the above are resolved.")
            if strict:
                print(
                    "\nError: system dependency installation failed (--strict mode)",
                    file=sys.stderr,
                )
                return 1

        return 0

    def update(self, name: str, ref: str | None = None, strict: bool = False) -> int:
        """Update an external plugin to the latest version.

        Args:
            name: Plugin name from registry.
            ref: Optional git ref to update to. Overrides registry default.
            strict: If True, return non-zero when any system dependency fails to install.

        Returns:
            Exit code: 0 on success, non-zero on failure.
        """
        plugin_info = self._resolve_plugin(name)
        if plugin_info is None:
            return 1

        package_name = plugin_info["package"]

        # First uninstall the current version
        print(f"Removing current version of '{name}'...")
        rc = self._run_uv(["pip", "uninstall", "-y", package_name])
        if rc is None:
            return 1

        # Then install the updated version
        return self.install(name, ref, strict=strict)

    def update_all(self, strict: bool = False) -> int:
        """Update all installed external plugins.

        Args:
            strict: If True, return non-zero when any system dependency fails to install.

        Returns:
            Exit code: 0 if all succeeded, non-zero if any failed.
        """
        registry = self._load_registry()

        if not registry:
            print("No external plugins in registry to update")
            return 0

        print(f"Updating {len(registry)} external plugin(s)...\n")

        failed = []
        for name in sorted(registry):
            result = self.update(name, strict=strict)
            if result != 0:
                failed.append(name)
            print()  # Blank line between updates

        if failed:
            print(f"\n✗ Failed to update: {', '.join(failed)}", file=sys.stderr)
            return 1

        print("\n✓ All plugins updated successfully")
        return 0

    def remove(self, name: str) -> int:
        """Remove an external plugin.

        Args:
            name: Plugin name from registry.

        Returns:
            Exit code: 0 on success, non-zero on failure.
        """
        plugin_info = self._resolve_plugin(name)
        if plugin_info is None:
            return 1

        package_name = plugin_info["package"]

        print(f"Removing plugin '{name}'...")

        rc = self._run_uv(["pip", "uninstall", "-y", package_name])
        if rc is None:
            return 1

        if rc != 0:
            print(f"\nError: Failed to remove plugin '{name}'", file=sys.stderr)
            return rc

        print(f"\n✓ Plugin '{name}' removed successfully")

        specs = parse_system_deps(plugin_info)
        if specs:
            binaries = ", ".join(s.binary for s in specs)
            print(f"\nNote: System dependencies were not removed (they may be shared): {binaries}")
            print("Remove them manually if no longer needed.")

        return 0


def format_plugin_list(plugins: dict[str, dict[str, Any]], verbose: bool = False) -> str:
    """Format plugin list for display.

    Args:
        plugins: Dict of plugin name to info.
        verbose: Show detailed information.

    Returns:
        Formatted string for display.
    """
    if not plugins:
        return "No external plugins available in registry"

    lines = ["Available external plugins:\n"]

    for name in sorted(plugins):
        info = plugins[name]
        desc = info.get("description", "No description")
        plugin_type = info.get("plugin_type", "unknown")
        is_private = info.get("private", False)

        privacy_marker = " [PRIVATE]" if is_private else ""
        type_marker = f" [{plugin_type}]"

        lines.append(f"  {name:<20} {desc}{type_marker}{privacy_marker}")

        if verbose:
            lines.append(f"    Package: {info['package']}")
            lines.append(f"    Source:  {info['source']}")
            if info.get("ref"):
                lines.append(f"    Ref:     {info['ref']}")
            if info.get("tags"):
                lines.append(f"    Tags:    {', '.join(info['tags'])}")
            specs = parse_system_deps(info)
            if specs:
                lines.append("    System deps:")
                for s in specs:
                    lines.append(f"      {s.binary:<20} ({s.manager}) {s.package}")
            lines.append("")

    return "\n".join(lines)
