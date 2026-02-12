"""
Centralized path resolution for Gauge.

Resolves file paths relative to the repository root for config files,
bundled resources, and external plugins.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# User-level gauge home directory
GAUGE_HOME = Path.home() / ".gauge"


def _get_repo_root() -> Path:
    """Get the repository root directory.

    Works by navigating up from this file's location:
    src/forge_gauge/utils/paths.py -> utils -> forge_gauge -> src -> repo_root
    """
    return Path(__file__).resolve().parent.parent.parent.parent


def _is_repo_install() -> bool:
    """Check if running from a git clone (vs pip-installed wheel)."""
    # Check for pyproject.toml (FORGE uses pyproject.toml instead of setup.py)
    return (_get_repo_root() / "pyproject.toml").is_file()


def get_config_path(relative_path: str) -> Path:
    """Resolve a mutable config file path (e.g., "image_mappings.yaml").

    In git-clone mode, config lives at repo_root/config/.
    In wheel-installed mode, config falls back to ~/.gauge/config/.

    Args:
        relative_path: Filename or path relative to config dir (e.g., "image_mappings.yaml")

    Returns:
        Absolute path to the config file
    """
    if _is_repo_install():
        return _get_repo_root() / "config" / relative_path
    config_dir = GAUGE_HOME / "config"
    if not config_dir.is_dir():
        config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / relative_path


def get_styles_path() -> Path:
    """Resolve the path to the CSS styles file used by HTML generators.

    Returns:
        Absolute path to src/outputs/styles.css
    """
    return Path(__file__).resolve().parent.parent / "outputs" / "styles.css"
