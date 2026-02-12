"""
Tests for update command routing.

Verifies that execute_update routes to git-clone or wheel update logic
depending on install mode.
"""

import argparse
import os
from unittest.mock import patch, MagicMock

from forge_gauge.plugins.gauge_core.update_command import (
    execute_update,
    _is_uv_tool_install,
    _find_wheel_asset,
    _download_wheel,
    _install_wheel,
    _fetch_latest_release_info,
)


class TestUpdateRouting:
    """Tests that execute_update routes correctly."""

    def _make_args(self, **kwargs):
        defaults = {"dry_run": False, "force": False, "main": False, "verbose": False}
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    @patch("plugins.gauge_core.update_command._update_git_clone", return_value=0)
    @patch("plugins.gauge_core.update_command._get_current_version", return_value="2.0.0")
    @patch("plugins.gauge_core.update_command._is_repo_install", return_value=True)
    def test_routes_to_git_clone_for_repo_install(self, mock_repo, mock_ver, mock_git):
        result = execute_update(self._make_args())
        mock_git.assert_called_once()
        assert result == 0

    @patch("plugins.gauge_core.update_command._update_wheel", return_value=0)
    @patch("plugins.gauge_core.update_command._get_current_version", return_value="2.0.0")
    @patch("plugins.gauge_core.update_command._is_repo_install", return_value=False)
    def test_routes_to_wheel_for_non_repo_install(self, mock_repo, mock_ver, mock_wheel):
        result = execute_update(self._make_args())
        mock_wheel.assert_called_once()
        assert result == 0


class TestIsUvToolInstall:
    """Tests for _is_uv_tool_install() detection."""

    def test_detects_uv_tool_prefix(self):
        with patch("plugins.gauge_core.update_command.sys") as mock_sys:
            mock_sys.prefix = "/home/user/.local/share/uv/tools/gauge"
            assert _is_uv_tool_install() is True

    def test_rejects_regular_venv(self):
        with patch("plugins.gauge_core.update_command.sys") as mock_sys:
            mock_sys.prefix = "/home/user/project/.venv"
            assert _is_uv_tool_install() is False


class TestFindWheelAsset:
    """Tests for _find_wheel_asset()."""

    def test_finds_wheel_in_assets(self):
        release = {
            "assets": [
                {"name": "gauge-2.1.1-py3-none-any.whl", "browser_download_url": "https://example.com/gauge-2.1.1-py3-none-any.whl"},
                {"name": "install.sh", "browser_download_url": "https://example.com/install.sh"},
            ]
        }
        success, url, name = _find_wheel_asset(release)
        assert success is True
        assert name == "gauge-2.1.1-py3-none-any.whl"
        assert "example.com" in url

    def test_returns_false_when_no_wheel(self):
        release = {
            "assets": [
                {"name": "install.sh", "browser_download_url": "https://example.com/install.sh"},
            ]
        }
        success, url, name = _find_wheel_asset(release)
        assert success is False

    def test_handles_empty_assets(self):
        success, url, name = _find_wheel_asset({"assets": []})
        assert success is False

    def test_handles_missing_assets_key(self):
        success, url, name = _find_wheel_asset({})
        assert success is False


class TestDownloadWheel:
    """Tests for _download_wheel()."""

    @patch("plugins.gauge_core.update_command.urllib.request.urlopen")
    @patch("plugins.gauge_core.update_command.github_api_headers", return_value={"Accept": "application/octet-stream"})
    def test_downloads_to_dest_dir(self, mock_headers, mock_urlopen, tmp_path):
        mock_response = MagicMock()
        mock_response.read.return_value = b"fake wheel content"
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        success, path = _download_wheel("https://example.com/gauge-2.0.0-py3-none-any.whl", str(tmp_path))
        assert success is True
        assert path.endswith("gauge-2.0.0-py3-none-any.whl")
        assert os.path.isfile(path)
        with open(path, "rb") as f:
            assert f.read() == b"fake wheel content"

    @patch("plugins.gauge_core.update_command.urllib.request.urlopen", side_effect=OSError("connection failed"))
    @patch("plugins.gauge_core.update_command.github_api_headers", return_value={})
    def test_returns_false_on_network_error(self, mock_headers, mock_urlopen, tmp_path):
        success, error = _download_wheel("https://example.com/gauge.whl", str(tmp_path))
        assert success is False
        assert "connection failed" in error


class TestInstallWheel:
    """Tests for _install_wheel()."""

    @patch("plugins.gauge_core.update_command.subprocess.run")
    @patch("plugins.gauge_core.update_command._is_uv_tool_install", return_value=True)
    def test_uses_uv_tool_for_uv_install(self, mock_uv, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="installed", stderr="")
        success, output = _install_wheel("/tmp/gauge.whl")
        assert success is True
        cmd = mock_run.call_args[0][0]
        assert cmd[:3] == ["uv", "tool", "install"]

    @patch("plugins.gauge_core.update_command.subprocess.run")
    @patch("plugins.gauge_core.update_command._is_uv_tool_install", return_value=False)
    @patch("plugins.gauge_core.update_command.sys")
    def test_uses_pip_in_virtualenv(self, mock_sys, mock_uv, mock_run):
        mock_sys.prefix = "/some/venv"
        mock_sys.base_prefix = "/usr"
        mock_sys.executable = "/some/venv/bin/python"
        mock_run.return_value = MagicMock(returncode=0, stdout="installed", stderr="")
        success, output = _install_wheel("/tmp/gauge.whl")
        assert success is True
        cmd = mock_run.call_args[0][0]
        assert "pip" in cmd

    @patch("plugins.gauge_core.update_command._is_uv_tool_install", return_value=False)
    @patch("plugins.gauge_core.update_command.sys")
    def test_rejects_global_install(self, mock_sys, mock_uv):
        mock_sys.prefix = "/usr"
        mock_sys.base_prefix = "/usr"
        success, output = _install_wheel("/tmp/gauge.whl")
        assert success is False
        assert "global" in output

    @patch("plugins.gauge_core.update_command.subprocess.run", side_effect=FileNotFoundError)
    @patch("plugins.gauge_core.update_command._is_uv_tool_install", return_value=True)
    def test_handles_missing_tool(self, mock_uv, mock_run):
        success, output = _install_wheel("/tmp/gauge.whl")
        assert success is False
        assert "not found" in output


class TestFetchLatestReleaseInfo:
    """Tests for _fetch_latest_release_info()."""

    @patch("plugins.gauge_core.update_command.urllib.request.urlopen")
    @patch("plugins.gauge_core.update_command.github_api_headers", return_value={})
    def test_returns_release_data(self, mock_headers, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"tag_name": "v2.1.1", "assets": []}'
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        success, data = _fetch_latest_release_info()
        assert success is True
        assert data["tag_name"] == "v2.1.1"

    @patch("plugins.gauge_core.update_command.urllib.request.urlopen", side_effect=OSError("timeout"))
    @patch("plugins.gauge_core.update_command.github_api_headers", return_value={})
    def test_returns_false_on_error(self, mock_headers, mock_urlopen):
        success, data = _fetch_latest_release_info()
        assert success is False
        assert "error" in data


class TestUpdateWheelDryRun:
    """Tests for wheel update dry-run mode."""

    def _make_args(self, **kwargs):
        defaults = {"dry_run": True, "force": False, "main": False, "verbose": False}
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    @patch("plugins.gauge_core.update_command._fetch_latest_release_info")
    def test_dry_run_shows_info(self, mock_fetch):
        from forge_gauge.plugins.gauge_core.update_command import _update_wheel
        mock_fetch.return_value = (True, {
            "tag_name": "v3.0.0",
            "assets": [
                {"name": "gauge-3.0.0-py3-none-any.whl", "browser_download_url": "https://example.com/gauge-3.0.0-py3-none-any.whl"},
            ],
        })
        result = _update_wheel(self._make_args(), "2.0.0")
        assert result == 0

    def test_main_flag_rejected(self):
        from forge_gauge.plugins.gauge_core.update_command import _update_wheel
        result = _update_wheel(self._make_args(main=True), "2.0.0")
        assert result == 1

    @patch("plugins.gauge_core.update_command._fetch_latest_release_info")
    def test_already_up_to_date(self, mock_fetch):
        from forge_gauge.plugins.gauge_core.update_command import _update_wheel
        mock_fetch.return_value = (True, {"tag_name": "v2.0.0", "assets": []})
        result = _update_wheel(self._make_args(dry_run=False), "2.0.0")
        assert result == 0
