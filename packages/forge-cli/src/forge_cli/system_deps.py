"""Install non-Python system dependencies declared in the plugin registry."""

from __future__ import annotations

import os
import platform
import shutil
import stat
import subprocess
import urllib.error
import urllib.request
import json as _json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class SystemDepSpec:
    """A single non-Python binary dependency for a plugin."""

    manager: str  # "go" | "npm" | "github_release"
    package: (
        str  # for go/npm: verbatim install argument; for github_release: "repo@tag"
    )
    binary: str  # binary name checked via shutil.which
    # github_release-specific (optional for go/npm)
    repo: str | None = None
    tag: str | None = None
    asset: str | None = None
    install_dir: str = "~/.local/bin"


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
    import sys

    raw = plugin_info.get("system_deps", [])
    if not raw:
        return []

    specs: list[SystemDepSpec] = []
    for entry in raw:
        manager = entry.get("manager")
        binary = entry.get("binary")

        if not manager or not binary:
            print(
                f"Warning: Skipping malformed system_deps entry (missing manager/binary): {entry}",
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

        if manager == "github_release":
            repo = entry.get("repo")
            tag = entry.get("tag")
            asset = entry.get("asset")
            if not repo or not tag or not asset:
                print(
                    f"Warning: Skipping github_release entry missing repo/tag/asset: {entry}",
                    file=sys.stderr,
                )
                continue
            specs.append(
                SystemDepSpec(
                    manager=manager,
                    package=f"{repo}@{tag}",
                    binary=binary,
                    repo=repo,
                    tag=tag,
                    asset=asset,
                    install_dir=entry.get("install_dir", "~/.local/bin"),
                )
            )
        else:
            package = entry.get("package")
            if not package:
                print(
                    f"Warning: Skipping system_deps entry missing package: {entry}",
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


def _install_via_cli(
    spec: SystemDepSpec,
    cli_tool: str,
    install_cmd: list[str],
    not_found_msg: str,
) -> SystemDepResult:
    """Run a CLI install command and return a SystemDepResult."""
    if not shutil.which(cli_tool):
        return SystemDepResult(
            spec=spec,
            already_installed=False,
            success=False,
            error_message=not_found_msg,
        )
    result = subprocess.run(install_cmd, capture_output=True, text=True)
    if result.returncode == 0:
        return SystemDepResult(
            spec=spec, already_installed=False, success=True, error_message=None
        )
    return SystemDepResult(
        spec=spec,
        already_installed=False,
        success=False,
        error_message=result.stderr.strip()
        or f"{cli_tool} exited with code {result.returncode}",
    )


def _install_go(spec: SystemDepSpec) -> SystemDepResult:
    """Install a Go binary via ``go install``."""
    return _install_via_cli(
        spec,
        cli_tool="go",
        install_cmd=["go", "install", spec.package],
        not_found_msg=(
            f"Go runtime not found. Install Go from https://go.dev/dl/ "
            f"then re-run: go install {spec.package}"
        ),
    )


def _install_npm(spec: SystemDepSpec) -> SystemDepResult:
    """Install a Node.js package globally via ``npm install -g``."""
    return _install_via_cli(
        spec,
        cli_tool="npm",
        install_cmd=["npm", "install", "-g", spec.package],
        not_found_msg=(
            f"npm not found. Install Node.js from https://nodejs.org/ "
            f"then re-run: npm install -g {spec.package}"
        ),
    )


def _resolve_asset_name(template: str) -> str:
    """Expand {os} and {arch} placeholders in a GitHub release asset name template."""
    os_name = {
        "Darwin": "darwin",
        "Linux": "linux",
        "Windows": "windows",
    }.get(platform.system(), platform.system().lower())
    arch = {
        "x86_64": "amd64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }.get(platform.machine(), platform.machine())
    return template.format(os=os_name, arch=arch)


def _chmod_x(path: Path) -> None:
    """Make a file executable."""
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _try_gh_download(
    spec: SystemDepSpec,
    asset_name: str,
    install_dir: Path,
    binary_path: Path,
) -> SystemDepResult | None:
    """Attempt download via gh CLI. Returns None if gh is unavailable or the download fails."""
    if not shutil.which("gh"):
        return None
    if not spec.tag or not spec.repo:
        return None
    result = subprocess.run(
        [
            "gh",
            "release",
            "download",
            spec.tag,
            "--repo",
            spec.repo,
            "--pattern",
            asset_name,
            "--dir",
            str(install_dir),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    downloaded = install_dir / asset_name
    if downloaded.exists() and downloaded != binary_path:
        downloaded.rename(binary_path)
    if binary_path.exists():
        _chmod_x(binary_path)
        return SystemDepResult(
            spec=spec, already_installed=False, success=True, error_message=None
        )
    return None


def _try_api_download(
    spec: SystemDepSpec,
    asset_name: str,
    binary_path: Path,
) -> SystemDepResult:
    """Download via GitHub REST API, using GITHUB_TOKEN if set."""
    token = os.environ.get("GITHUB_TOKEN", "")
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    api_url = f"https://api.github.com/repos/{spec.repo}/releases/tags/{spec.tag}"
    try:
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req) as resp:
            release = _json.loads(resp.read())
    except urllib.error.HTTPError as e:
        msg = f"GitHub API error {e.code} for {spec.repo}@{spec.tag}"
        if e.code in (401, 403):
            msg += " — set GITHUB_TOKEN or run `gh auth login`"
        elif e.code == 404:
            msg += " — release not found (check repo/tag and access)"
        return SystemDepResult(
            spec=spec, already_installed=False, success=False, error_message=msg
        )
    except Exception as e:
        return SystemDepResult(
            spec=spec, already_installed=False, success=False, error_message=str(e)
        )

    for asset in release.get("assets", []):
        if asset["name"] == asset_name:
            try:
                dl_req = urllib.request.Request(
                    asset["browser_download_url"], headers=headers
                )
                with urllib.request.urlopen(dl_req) as resp:
                    binary_path.write_bytes(resp.read())
                _chmod_x(binary_path)
                return SystemDepResult(
                    spec=spec, already_installed=False, success=True, error_message=None
                )
            except Exception as e:
                return SystemDepResult(
                    spec=spec,
                    already_installed=False,
                    success=False,
                    error_message=str(e),
                )

    return SystemDepResult(
        spec=spec,
        already_installed=False,
        success=False,
        error_message=(
            f"No asset matching '{asset_name}' found in {spec.repo}@{spec.tag}. "
            f"Available: {', '.join(a['name'] for a in release.get('assets', []))}"
        ),
    )


def _install_github_release(spec: SystemDepSpec) -> SystemDepResult:
    """Download a pre-built binary from GitHub Releases.

    Tries ``gh release download`` first (handles auth automatically),
    then falls back to the GitHub REST API with GITHUB_TOKEN.
    """
    if not spec.repo or not spec.tag or not spec.asset:
        return SystemDepResult(
            spec=spec,
            already_installed=False,
            success=False,
            error_message="github_release spec is missing repo, tag, or asset",
        )

    install_dir = Path(spec.install_dir).expanduser()
    install_dir.mkdir(parents=True, exist_ok=True)
    asset_name = _resolve_asset_name(spec.asset)
    binary_path = install_dir / spec.binary

    return _try_gh_download(
        spec, asset_name, install_dir, binary_path
    ) or _try_api_download(spec, asset_name, binary_path)


INSTALLERS: dict[str, Callable[[SystemDepSpec], SystemDepResult]] = {
    "go": _install_go,
    "npm": _install_npm,
    "github_release": _install_github_release,
}
