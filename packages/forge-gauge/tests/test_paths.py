"""
Tests for centralized path resolution (utils/paths.py).

Verifies that config and style paths resolve correctly in both
git-clone and wheel-installed modes.
"""

from pathlib import Path
from unittest.mock import patch

from forge_gauge.utils.paths import (
    GAUGE_HOME,
    _get_repo_root,
    _is_repo_install,
    get_config_path,
    get_styles_path,
)


class TestNonFrozenPaths:
    """Tests for path resolution in git-clone mode."""

    def test_get_repo_root_points_to_repo(self):
        """Repo root should contain pyproject.toml and src/."""
        root = _get_repo_root()
        assert (root / "pyproject.toml").exists()
        assert (root / "src").is_dir()

    def test_is_repo_install_true_in_git_clone(self):
        """_is_repo_install() should return True when pyproject.toml exists."""
        assert _is_repo_install() is True

    def test_get_config_path_resolves_to_repo_config(self):
        """Config paths should point to repo_root/config/ in git-clone mode."""
        path = get_config_path("image_mappings.yaml")
        assert path == _get_repo_root() / "config" / "image_mappings.yaml"
        assert path.exists()

    def test_get_styles_path_resolves_to_outputs(self):
        """Styles path should point to src/outputs/styles.css."""
        path = get_styles_path()
        assert path.name == "styles.css"
        assert path.exists()

    def test_config_path_returns_absolute(self):
        """Config paths should always be absolute."""
        path = get_config_path("some_file.yaml")
        assert path.is_absolute()


class TestWheelInstallPaths:
    """Tests for path resolution in wheel-installed mode."""

    def test_config_path_falls_back_to_gauge_home(self, tmp_path):
        """When pyproject.toml doesn't exist, config should fall back to ~/.gauge/config/."""
        fake_home = tmp_path / ".gauge"
        with patch("forge_gauge.utils.paths._is_repo_install", return_value=False), \
             patch("forge_gauge.utils.paths.GAUGE_HOME", fake_home):
            path = get_config_path("image_mappings.yaml")
            assert path == fake_home / "config" / "image_mappings.yaml"
            # Directory should be created
            assert (fake_home / "config").is_dir()
