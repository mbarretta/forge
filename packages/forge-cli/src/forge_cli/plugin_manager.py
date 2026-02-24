"""Plugin management for external FORGE plugins.

Manages installation, updates, and removal of external plugins from git repositories.
Uses UV for git-based package installation with support for private GitHub repos.
"""

from __future__ import annotations

import importlib.metadata
import importlib.resources
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from forge_cli.system_deps import SystemDepSpec, install_system_deps, parse_system_deps


class PluginManager:
    """Manages external FORGE plugins from git repositories."""

    def __init__(self, registry_path: Path | None = None):
        """Initialize plugin manager.

        Args:
            registry_path: Explicit path to plugins-registry.yaml (for testing/CI).
                          If None, uses the standard resolution order:
                          FORGE_PLUGIN_REGISTRY env var → user config → bundled default.
        """
        self._explicit_registry_path = registry_path
        self._registry: dict[str, dict[str, Any]] | None = None

    def _get_registry_content(self) -> str:
        """Read registry YAML content using the resolution order."""
        # 1. Explicit path (testing / constructor override)
        if self._explicit_registry_path is not None:
            if not self._explicit_registry_path.exists():
                print(
                    f"Warning: Registry not found at {self._explicit_registry_path}",
                    file=sys.stderr,
                )
                return ""
            return self._explicit_registry_path.read_text()

        # 2. FORGE_PLUGIN_REGISTRY env var (CI / custom overrides)
        if env_path := os.environ.get("FORGE_PLUGIN_REGISTRY"):
            path = Path(env_path)
            if not path.exists():
                print(
                    f"Warning: FORGE_PLUGIN_REGISTRY path not found: {path}",
                    file=sys.stderr,
                )
                return ""
            return path.read_text()

        # 3. User-local additions and overrides
        user_path = Path.home() / ".config" / "forge" / "plugins-registry.yaml"
        if user_path.exists():
            return user_path.read_text()

        # 4. Bundled default (works after `uv tool install`, no env var needed)
        return (
            importlib.resources.files("forge_cli")
            .joinpath("data/plugins-registry.yaml")
            .read_text(encoding="utf-8")
        )

    def _load_registry(self) -> dict[str, dict[str, Any]]:
        """Load plugin registry from YAML (result is cached)."""
        if self._registry is not None:
            return self._registry

        try:
            content = self._get_registry_content()
            if not content:
                self._registry = {}
                return self._registry
            data = yaml.safe_load(content)
            self._registry = data.get("external_plugins", {}) if data else {}
        except Exception as e:
            print(f"Error loading plugin registry: {e}", file=sys.stderr)
            self._registry = {}

        return self._registry

    def _resolve_plugin(self, name: str) -> dict[str, Any] | None:
        """Look up a plugin by name, printing an error if not found."""
        registry = self._load_registry()
        if name in registry:
            return registry[name]

        print(f"Error: Plugin '{name}' not found in registry", file=sys.stderr)
        if registry:
            print(
                f"\nAvailable plugins: {', '.join(sorted(registry))}", file=sys.stderr
            )
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

    @staticmethod
    def _running_as_uv_tool() -> bool:
        """Return True when forge is installed as a uv tool (isolated venv)."""
        tools_path = Path.home() / ".local" / "share" / "uv" / "tools"
        return tools_path in Path(sys.executable).parents

    def _install_package(self, package_url: str) -> int | None:
        """Install a Python package into the correct environment."""
        if self._running_as_uv_tool():
            # Target forge's isolated tool venv directly via its Python executable.
            # This works regardless of uv version (no 'uv tool inject' needed).
            return self._run_uv(
                ["pip", "install", "--python", sys.executable, package_url]
            )
        return self._run_uv(["pip", "install", package_url])

    def _uninstall_package(self, package_name: str) -> int | None:
        """Uninstall a Python package from the correct environment."""
        if self._running_as_uv_tool():
            return self._run_uv(
                ["pip", "uninstall", "--python", sys.executable, "-y", package_name]
            )
        return self._run_uv(["pip", "uninstall", "-y", package_name])

    def list_available(
        self, tag_filter: str | None = None
    ) -> dict[str, dict[str, Any]]:
        """List available external plugins from registry."""
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

        plugin_type = plugin_info.get("plugin_type", "native")

        if plugin_type == "binary":
            return self._install_binary_plugin(name, plugin_info)

        return self._install_python_plugin(name, plugin_info, ref, strict)

    def _install_python_plugin(
        self, name: str, plugin_info: dict[str, Any], ref: str | None, strict: bool
    ) -> int:
        """Install a native/wrapper Python plugin."""
        git_url = plugin_info["source"]
        is_private = plugin_info.get("private", False)

        ref_to_use = ref or plugin_info.get("ref")
        if ref_to_use:
            # @ref must come before any # fragment (e.g. #subdirectory=...)
            if "#" in git_url:
                base, fragment = git_url.split("#", 1)
                git_url = f"{base}@{ref_to_use}#{fragment}"
            else:
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
                    print(
                        f"  Warning: {r.spec.binary}: {r.error_message}",
                        file=sys.stderr,
                    )

        rc = self._install_package(git_url)
        if rc is None:
            return 1

        if rc != 0:
            print(f"\nError: Failed to install plugin '{name}'", file=sys.stderr)
            if is_private:
                source = plugin_info.get("source", "")
                if "git+ssh://" in source:
                    print(
                        "  Hint: ensure your SSH key is added — see docs/AUTHENTICATION.md",
                        file=sys.stderr,
                    )
                elif "git+https://" in source:
                    print(
                        "  Hint: run `gh auth login` to configure git credentials — see docs/AUTHENTICATION.md",
                        file=sys.stderr,
                    )
            return rc

        print(f"\n✓ Plugin '{name}' installed successfully")
        print(f"\nUsage: forge {plugin_info['package']} --help")

        if system_dep_failures:
            print(
                f"\nWarning: '{name}' installed but these system deps need manual setup:"
            )
            for r in system_dep_failures:
                print(f"  {r.spec.binary} ({r.spec.manager}): {r.spec.package}")
                if r.error_message:
                    for line in r.error_message.splitlines():
                        print(f"    {line}")
            print(
                "\nThe plugin is installed but may not function until the above are resolved."
            )
            if strict:
                print(
                    "\nError: system dependency installation failed (--strict mode)",
                    file=sys.stderr,
                )
                return 1

        return 0

    def _introspect_and_cache(self, name: str, binary_path: Path) -> dict | None:
        """Run ``--forge-introspect`` on a binary, cache the result, and return it.

        Returns the introspection dict on success, or None on any failure.
        """
        try:
            proc = subprocess.run(
                [str(binary_path), "--forge-introspect"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            print(
                f"Error: '{binary_path.name} --forge-introspect' timed out",
                file=sys.stderr,
            )
            return None
        except FileNotFoundError:
            print(
                f"Error: Binary not found at {binary_path}. Is {binary_path.parent} in PATH?",
                file=sys.stderr,
            )
            return None

        if proc.returncode != 0:
            print(
                f"Warning: '{binary_path.name} --forge-introspect' exited {proc.returncode}. "
                "Plugin may not work correctly.",
                file=sys.stderr,
            )
            return None

        try:
            introspect_data = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            print(
                f"Error: '{binary_path.name} --forge-introspect' returned invalid JSON: {e}",
                file=sys.stderr,
            )
            return None

        cache_path = Path.home() / ".config" / "forge" / "binary-plugins.json"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
        except Exception:
            cache = {}
        cache[name] = {
            "binary_path": str(binary_path),
            "introspect_data": introspect_data,
        }
        cache_path.write_text(json.dumps(cache, indent=2))
        return introspect_data

    def _install_binary_plugin(self, name: str, plugin_info: dict[str, Any]) -> int:
        """Install a binary-protocol plugin: download binary, introspect, cache."""
        binary_source = plugin_info.get("binary_source", {})
        if not binary_source:
            print(
                f"Error: Binary plugin '{name}' has no 'binary_source' config",
                file=sys.stderr,
            )
            return 1

        binary = binary_source.get("binary", name)
        install_dir = binary_source.get("install_dir", "~/.local/bin")
        binary_path = Path(install_dir).expanduser() / binary

        spec = SystemDepSpec(
            manager=binary_source.get("manager", "github_release"),
            package=f"{binary_source.get('repo', '')}@{binary_source.get('tag', '')}",
            binary=binary,
            repo=binary_source.get("repo"),
            tag=binary_source.get("tag"),
            asset=binary_source.get("asset"),
            install_dir=install_dir,
        )

        print(f"Installing binary plugin '{name}'...")
        result = install_system_deps([spec])[0]

        if result.already_installed:
            print(f"  {binary}: already installed, skipping download")
        elif result.success:
            print(f"  {binary}: installed to {binary_path.parent}")
        else:
            print(
                f"  Error: Failed to install {binary}: {result.error_message}",
                file=sys.stderr,
            )
            return 1

        if self._introspect_and_cache(name, binary_path) is None:
            return 1

        print(f"\n✓ Binary plugin '{name}' installed successfully")
        print(f"\nUsage: forge {name} --help")
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

        plugin_type = plugin_info.get("plugin_type", "native")

        if plugin_type == "binary":
            # Remove and reinstall binary plugin
            self._remove_binary_plugin(name, plugin_info)
            return self._install_binary_plugin(name, plugin_info)

        package_name = plugin_info["package"]
        print(f"Removing current version of '{name}'...")
        rc = self._uninstall_package(package_name)
        if rc is None:
            return 1

        return self.install(name, ref, strict=strict)

    def update_all(self, strict: bool = False) -> int:
        """Update all installed external plugins.

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
            print()

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

        plugin_type = plugin_info.get("plugin_type", "native")

        if plugin_type == "binary":
            return self._remove_binary_plugin(name, plugin_info)

        package_name = plugin_info["package"]
        print(f"Removing plugin '{name}'...")

        rc = self._uninstall_package(package_name)
        if rc is None:
            return 1

        if rc != 0:
            print(f"\nError: Failed to remove plugin '{name}'", file=sys.stderr)
            return rc

        print(f"\n✓ Plugin '{name}' removed successfully")

        specs = parse_system_deps(plugin_info)
        if specs:
            binaries = ", ".join(s.binary for s in specs)
            print(
                f"\nNote: System dependencies were not removed (they may be shared): {binaries}"
            )
            print("Remove them manually if no longer needed.")

        return 0

    def _remove_binary_plugin(self, name: str, plugin_info: dict[str, Any]) -> int:
        """Remove a binary-protocol plugin."""
        binary_source = plugin_info.get("binary_source", {})
        binary = binary_source.get("binary", name)
        install_dir = binary_source.get("install_dir", "~/.local/bin")
        binary_path = Path(install_dir).expanduser() / binary

        print(f"Removing binary plugin '{name}'...")

        if binary_path.exists():
            binary_path.unlink()
            print(f"  Removed {binary_path}")
        else:
            print(f"  Warning: Binary not found at {binary_path}", file=sys.stderr)

        cache_path = Path.home() / ".config" / "forge" / "binary-plugins.json"
        if cache_path.exists():
            try:
                cache = json.loads(cache_path.read_text())
                cache.pop(name, None)
                cache_path.write_text(json.dumps(cache, indent=2))
            except Exception:
                pass

        print(f"\n✓ Binary plugin '{name}' removed")
        return 0


def is_plugin_installed(info: dict[str, Any]) -> bool:
    """Return True if the plugin's package is currently installed in this environment."""
    plugin_type = info.get("plugin_type", "native")
    if plugin_type == "binary":
        cache_path = Path.home() / ".config" / "forge" / "binary-plugins.json"
        if not cache_path.exists():
            return False
        try:
            cache = json.loads(cache_path.read_text())
            binary = info.get("binary_source", {}).get("binary", "")
            return any(
                v.get("binary_path", "").endswith(binary) for v in cache.values()
            )
        except Exception:
            return False
    package = info.get("package", "")
    if not package:
        return False
    try:
        importlib.metadata.version(package)
        return True
    except importlib.metadata.PackageNotFoundError:
        return False


def format_plugin_list(
    plugins: dict[str, dict[str, Any]], verbose: bool = False
) -> str:
    """Format plugin list for display."""
    if not plugins:
        return "No external plugins available in registry"

    lines = ["Available external plugins (✓ = installed):\n"]

    for name in sorted(plugins):
        info = plugins[name]
        desc = info.get("description", "No description")
        plugin_type = info.get("plugin_type", "unknown")
        is_private = info.get("private", False)
        installed = is_plugin_installed(info)

        install_marker = "✓" if installed else " "
        privacy_marker = " [PRIVATE]" if is_private else ""
        type_marker = f" [{plugin_type}]"

        lines.append(
            f"  {install_marker} {name:<20} {desc}{type_marker}{privacy_marker}"
        )

        if verbose:
            if plugin_type == "binary":
                bs = info.get("binary_source", {})
                lines.append(f"    Binary:  {bs.get('binary', name)}")
                lines.append(f"    Repo:    {bs.get('repo', '')}")
                lines.append(f"    Tag:     {bs.get('tag', '')}")
            else:
                lines.append(f"    Package: {info.get('package', '')}")
                lines.append(f"    Source:  {info.get('source', '')}")
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
