"""Install non-Python system dependencies declared in the plugin registry."""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class SystemDepSpec:
    """A single non-Python binary dependency for a plugin."""

    manager: str  # "go" | "npm"
    package: str  # verbatim install argument
    binary: str   # checked via shutil.which


@dataclass(frozen=True)
class SystemDepResult:
    """Outcome of installing (or skipping) a single system dependency."""

    spec: SystemDepSpec
    already_installed: bool
    success: bool
    error_message: str | None


def parse_system_deps(plugin_info: dict[str, Any]) -> list[SystemDepSpec]:
    """Parse system_deps entries from a plugin registry record.

    Unknown or malformed entries are skipped with a warning to stderr.
    """
    raw = plugin_info.get("system_deps", [])
    if not raw:
        return []

    specs: list[SystemDepSpec] = []
    for entry in raw:
        manager = entry.get("manager")
        package = entry.get("package")
        binary = entry.get("binary")

        if not manager or not package or not binary:
            print(
                f"Warning: Skipping malformed system_deps entry (missing manager/package/binary): {entry}",
                file=sys.stderr,
            )
            continue

        if manager not in INSTALLERS:
            print(
                f"Warning: Skipping system_deps entry with unknown manager '{manager}' "
                f"(supported: {', '.join(sorted(INSTALLERS))})",
                file=sys.stderr,
            )
            continue

        specs.append(SystemDepSpec(manager=manager, package=package, binary=binary))

    return specs


def install_system_deps(specs: list[SystemDepSpec]) -> list[SystemDepResult]:
    """Install a list of system dependencies, skipping ones already present."""
    results: list[SystemDepResult] = []
    for spec in specs:
        if shutil.which(spec.binary):
            results.append(
                SystemDepResult(
                    spec=spec,
                    already_installed=True,
                    success=True,
                    error_message=None,
                )
            )
        else:
            results.append(INSTALLERS[spec.manager](spec))
    return results


def _install_go(spec: SystemDepSpec) -> SystemDepResult:
    """Install a Go binary via ``go install``."""
    if not shutil.which("go"):
        return SystemDepResult(
            spec=spec,
            already_installed=False,
            success=False,
            error_message=(
                f"Go runtime not found. Install Go from https://go.dev/dl/ "
                f"then re-run: go install {spec.package}"
            ),
        )

    result = subprocess.run(
        ["go", "install", spec.package],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return SystemDepResult(
            spec=spec,
            already_installed=False,
            success=True,
            error_message=None,
        )
    return SystemDepResult(
        spec=spec,
        already_installed=False,
        success=False,
        error_message=result.stderr.strip() or f"go install exited with code {result.returncode}",
    )


def _install_npm(spec: SystemDepSpec) -> SystemDepResult:
    """Install a Node.js package globally via ``npm install -g``."""
    if not shutil.which("npm"):
        return SystemDepResult(
            spec=spec,
            already_installed=False,
            success=False,
            error_message=(
                f"npm not found. Install Node.js from https://nodejs.org/ "
                f"then re-run: npm install -g {spec.package}"
            ),
        )

    result = subprocess.run(
        ["npm", "install", "-g", spec.package],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return SystemDepResult(
            spec=spec,
            already_installed=False,
            success=True,
            error_message=None,
        )
    return SystemDepResult(
        spec=spec,
        already_installed=False,
        success=False,
        error_message=result.stderr.strip() or f"npm install exited with code {result.returncode}",
    )


INSTALLERS: dict[str, Callable[[SystemDepSpec], SystemDepResult]] = {
    "go": _install_go,
    "npm": _install_npm,
}
