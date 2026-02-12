"""
External plugin management utilities for Gauge.

Handles installation, updates, and management of 3rd party plugins
from GitHub repositories with isolated virtualenv support.
"""

import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

# Default paths
GAUGE_HOME = Path.home() / ".gauge"
PLUGINS_DIR = GAUGE_HOME / "plugins"
REGISTRY_FILE = GAUGE_HOME / "plugin-registry.yaml"


@dataclass
class PluginSource:
    """Source information for an installed plugin."""

    type: str  # "github"
    repo: str  # e.g., "chainguard-dev/my-plugin"
    branch: str
    commit: str


@dataclass
class InstalledPlugin:
    """Metadata for an installed external plugin."""

    name: str
    version: str
    source: PluginSource
    installed_at: datetime
    updated_at: datetime
    path: Path

    def to_dict(self) -> dict:
        """Convert to dictionary for YAML serialization."""
        return {
            "name": self.name,
            "version": self.version,
            "source": {
                "type": self.source.type,
                "repo": self.source.repo,
                "branch": self.source.branch,
                "commit": self.source.commit,
            },
            "installed_at": self.installed_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "path": str(self.path),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "InstalledPlugin":
        """Create from dictionary (YAML deserialization)."""
        source = PluginSource(
            type=data["source"]["type"],
            repo=data["source"]["repo"],
            branch=data["source"]["branch"],
            commit=data["source"]["commit"],
        )
        return cls(
            name=data["name"],
            version=data["version"],
            source=source,
            installed_at=datetime.fromisoformat(data["installed_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            path=Path(data["path"]),
        )


@dataclass
class PluginManifest:
    """Plugin manifest from plugin.yaml."""

    name: str
    version: str = "0.0.0"
    description: str = ""
    author: str = ""
    commands: list[dict] = field(default_factory=list)
    python_dependencies: list[str] = field(default_factory=list)
    setup_commands: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)

    @classmethod
    def from_file(cls, path: Path) -> Optional["PluginManifest"]:
        """Load manifest from plugin.yaml file."""
        if not path.exists():
            return None

        try:
            with open(path) as f:
                data = yaml.safe_load(f) or {}

            build = data.get("build", {})

            return cls(
                name=data.get("name", ""),
                version=data.get("version", "0.0.0"),
                description=data.get("description", ""),
                author=data.get("author", ""),
                commands=data.get("commands", []),
                python_dependencies=build.get("python_dependencies", []),
                setup_commands=build.get("setup_commands", []),
                requires=build.get("requires", []),
            )
        except Exception as e:
            logger.warning(f"Failed to parse plugin.yaml: {e}")
            return None

    @classmethod
    def from_requirements_txt(cls, path: Path, name: str) -> Optional["PluginManifest"]:
        """Create manifest from requirements.txt file."""
        if not path.exists():
            return None

        try:
            with open(path) as f:
                deps = [
                    line.strip()
                    for line in f
                    if line.strip() and not line.startswith("#")
                ]

            return cls(
                name=name,
                python_dependencies=deps,
            )
        except Exception as e:
            logger.warning(f"Failed to parse requirements.txt: {e}")
            return None


class PluginRegistryFile:
    """Manages the plugin registry file (~/.gauge/plugin-registry.yaml)."""

    def __init__(self, path: Path = REGISTRY_FILE):
        self.path = path

    def load(self) -> dict[str, InstalledPlugin]:
        """Load installed plugins from registry file."""
        if not self.path.exists():
            return {}

        try:
            with open(self.path) as f:
                data = yaml.safe_load(f) or {}

            plugins = {}
            for name, plugin_data in data.get("plugins", {}).items():
                try:
                    plugins[name] = InstalledPlugin.from_dict(plugin_data)
                except Exception as e:
                    logger.warning(f"Failed to load plugin '{name}' from registry: {e}")

            return plugins
        except Exception as e:
            logger.warning(f"Failed to load plugin registry: {e}")
            return {}

    def save(self, plugins: dict[str, InstalledPlugin]) -> None:
        """Save plugins to registry file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)

        data = {"plugins": {name: p.to_dict() for name, p in plugins.items()}}

        with open(self.path, "w") as f:
            yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)

    def add(self, plugin: InstalledPlugin) -> None:
        """Add or update a plugin in the registry."""
        plugins = self.load()
        plugins[plugin.name] = plugin
        self.save(plugins)

    def remove(self, name: str) -> bool:
        """Remove a plugin from the registry."""
        plugins = self.load()
        if name in plugins:
            del plugins[name]
            self.save(plugins)
            return True
        return False

    def get(self, name: str) -> Optional[InstalledPlugin]:
        """Get a plugin by name."""
        plugins = self.load()
        return plugins.get(name)


def check_tool_available(tool: str) -> bool:
    """Check if a command-line tool is available."""
    return shutil.which(tool) is not None


def check_required_tools(requires: list[str]) -> list[str]:
    """Check which required tools are missing."""
    missing = []
    for tool in requires:
        if not check_tool_available(tool):
            missing.append(tool)
    return missing


def run_command(
    cmd: list[str],
    cwd: Optional[Path] = None,
    env: Optional[dict] = None,
    capture_output: bool = True,
) -> subprocess.CompletedProcess:
    """Run a shell command with error handling."""
    full_env = os.environ.copy()
    if env:
        full_env.update(env)

    return subprocess.run(
        cmd,
        cwd=cwd,
        env=full_env,
        capture_output=capture_output,
        text=True,
    )


def clone_repository(
    repo: str,
    dest: Path,
    branch: Optional[str] = None,
) -> tuple[bool, str]:
    """Clone a GitHub repository.

    Args:
        repo: Repository in format "owner/repo"
        dest: Destination directory
        branch: Optional branch/tag to checkout

    Returns:
        Tuple of (success, message or error)
    """
    url = f"https://github.com/{repo}.git"

    cmd = ["git", "clone", "--depth", "1"]
    if branch:
        cmd.extend(["--branch", branch])
    cmd.extend([url, str(dest)])

    result = run_command(cmd)

    if result.returncode != 0:
        return False, result.stderr or "Git clone failed"

    return True, "Repository cloned successfully"


def get_git_commit(repo_path: Path) -> Optional[str]:
    """Get the current commit hash of a git repository."""
    result = run_command(["git", "rev-parse", "HEAD"], cwd=repo_path)
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def get_git_branch(repo_path: Path) -> Optional[str]:
    """Get the current branch name of a git repository."""
    result = run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path)
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def pull_repository(repo_path: Path) -> tuple[bool, str]:
    """Pull latest changes from remote.

    Returns:
        Tuple of (success, message or error)
    """
    result = run_command(["git", "pull"], cwd=repo_path)
    if result.returncode != 0:
        return False, result.stderr or "Git pull failed"
    return True, result.stdout or "Already up to date"


def create_venv(venv_path: Path) -> tuple[bool, str]:
    """Create a virtual environment using uv.

    Returns:
        Tuple of (success, message or error)
    """
    if not check_tool_available("uv"):
        return False, "uv is required for plugin installation. Install with: pip install uv"

    result = run_command(["uv", "venv", str(venv_path)])
    if result.returncode != 0:
        return False, result.stderr or "Failed to create virtualenv"
    return True, "Virtualenv created"


def install_dependencies(
    venv_path: Path,
    dependencies: list[str],
    requirements_file: Optional[Path] = None,
) -> tuple[bool, str]:
    """Install Python dependencies into a virtualenv using uv.

    Args:
        venv_path: Path to the virtualenv
        dependencies: List of package specifiers
        requirements_file: Optional path to requirements.txt

    Returns:
        Tuple of (success, message or error)
    """
    if not check_tool_available("uv"):
        return False, "uv is required for dependency installation"

    # Determine pip path
    if sys.platform == "win32":
        pip_path = venv_path / "Scripts" / "pip"
    else:
        pip_path = venv_path / "bin" / "pip"

    # Install from requirements file if provided
    if requirements_file and requirements_file.exists():
        result = run_command(
            ["uv", "pip", "install", "-r", str(requirements_file), "--python", str(venv_path / "bin" / "python")],
        )
        if result.returncode != 0:
            return False, f"Failed to install from requirements.txt: {result.stderr}"

    # Install individual dependencies
    if dependencies:
        result = run_command(
            ["uv", "pip", "install", *dependencies, "--python", str(venv_path / "bin" / "python")],
        )
        if result.returncode != 0:
            return False, f"Failed to install dependencies: {result.stderr}"

    return True, "Dependencies installed"


def run_setup_commands(
    plugin_dir: Path,
    commands: list[str],
) -> tuple[bool, str]:
    """Run setup commands in the plugin directory.

    Args:
        plugin_dir: Plugin directory (working directory for commands)
        commands: List of shell commands to run

    Returns:
        Tuple of (success, message or error)
    """
    for cmd in commands:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=plugin_dir,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return False, f"Setup command failed: {cmd}\n{result.stderr}"

    return True, "Setup commands completed"


def get_plugin_venv_site_packages(plugin_dir: Path) -> Optional[Path]:
    """Get the site-packages path for a plugin's virtualenv."""
    venv_path = plugin_dir / ".venv"
    if not venv_path.exists():
        return None

    # Find site-packages (handles different Python versions)
    if sys.platform == "win32":
        site_packages = venv_path / "Lib" / "site-packages"
    else:
        # Look for python directory
        lib_path = venv_path / "lib"
        if lib_path.exists():
            for py_dir in lib_path.iterdir():
                if py_dir.name.startswith("python"):
                    site_packages = py_dir / "site-packages"
                    if site_packages.exists():
                        return site_packages

    return None


def validate_plugin_structure(plugin_dir: Path) -> tuple[bool, str]:
    """Validate that a directory contains a valid gauge plugin.

    Checks for:
    - __init__.py exists
    - Either get_plugin() function or Plugin class exported

    Returns:
        Tuple of (valid, message)
    """
    init_file = plugin_dir / "__init__.py"
    plugin_file = plugin_dir / "plugin.py"

    if not init_file.exists() and not plugin_file.exists():
        return False, "Plugin must have __init__.py or plugin.py"

    # Try to check if plugin exports required symbols
    # We'll do a simple text check to avoid import side effects
    content = ""
    if init_file.exists():
        content = init_file.read_text()
    elif plugin_file.exists():
        content = plugin_file.read_text()

    has_get_plugin = "get_plugin" in content or "def get_plugin" in content
    has_plugin_class = "Plugin" in content or "class " in content and "GaugePlugin" in content

    if not has_get_plugin and not has_plugin_class:
        return False, "Plugin must export get_plugin() function or Plugin class"

    return True, "Plugin structure is valid"


def derive_plugin_name(repo: str, manifest: Optional[PluginManifest]) -> str:
    """Derive the plugin name from manifest or repository name.

    Args:
        repo: Repository in format "owner/repo"
        manifest: Optional plugin manifest

    Returns:
        Plugin name (directory name)
    """
    if manifest and manifest.name:
        return manifest.name

    # Use repository name
    repo_name = repo.split("/")[-1]

    # Remove common prefixes/suffixes
    for prefix in ["gauge-", "gauge_"]:
        if repo_name.startswith(prefix):
            repo_name = repo_name[len(prefix) :]

    for suffix in ["-plugin", "_plugin", "-gauge", "_gauge"]:
        if repo_name.endswith(suffix):
            repo_name = repo_name[: -len(suffix)]

    return repo_name
