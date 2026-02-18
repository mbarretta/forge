"""Tests for forge_cli.plugin_manager integration with system_deps."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from unittest.mock import MagicMock, patch

import pytest
import yaml

from forge_cli.plugin_manager import PluginManager, format_plugin_list
from forge_cli.system_deps import SystemDepResult, SystemDepSpec


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry(extra_plugins: dict | None = None) -> dict:
    """Return a registry dict with an optional go-tool plugin."""
    plugins = {
        "plain-plugin": {
            "package": "forge-plain",
            "source": "git+https://example.com/plain.git",
            "ref": "v1.0.0",
            "description": "No system deps",
            "plugin_type": "native",
            "tags": ["test"],
            "private": False,
        }
    }
    if extra_plugins:
        plugins.update(extra_plugins)
    return {"external_plugins": plugins}


def _plugin_with_system_deps() -> dict:
    return {
        "go-tool": {
            "package": "forge-go-tool",
            "source": "git+https://example.com/go-tool.git",
            "ref": "v1.0.0",
            "description": "Wraps a Go binary",
            "plugin_type": "wrapper",
            "tags": ["security"],
            "private": False,
            "system_deps": [
                {"manager": "go", "package": "github.com/org/go-tool@v1.2.3", "binary": "go-tool"}
            ],
        }
    }


def _make_manager(tmp_path: Path, registry_data: dict) -> PluginManager:
    registry_file = tmp_path / "plugins-registry.yaml"
    registry_file.write_text(yaml.dump(registry_data))
    return PluginManager(registry_path=registry_file)


# ---------------------------------------------------------------------------
# install() — system_deps integration
# ---------------------------------------------------------------------------


def test_install_calls_system_deps_for_plugin_with_system_deps(tmp_path):
    manager = _make_manager(tmp_path, _make_registry(_plugin_with_system_deps()))

    success_result = SystemDepResult(
        spec=SystemDepSpec(manager="go", package="github.com/org/go-tool@v1.2.3", binary="go-tool"),
        already_installed=False,
        success=True,
        error_message=None,
    )

    with patch.object(manager, "_run_uv", return_value=0):
        with patch("forge_cli.plugin_manager.install_system_deps", return_value=[success_result]) as mock_install:
            with patch("forge_cli.plugin_manager.parse_system_deps", wraps=lambda info: [success_result.spec]) as mock_parse:
                rc = manager.install("go-tool")

    assert rc == 0
    mock_install.assert_called_once()


def test_install_skips_system_deps_for_plugin_without_system_deps(tmp_path):
    manager = _make_manager(tmp_path, _make_registry())

    with patch.object(manager, "_run_uv", return_value=0):
        with patch("forge_cli.plugin_manager.install_system_deps") as mock_install:
            rc = manager.install("plain-plugin")

    assert rc == 0
    mock_install.assert_not_called()


def test_install_warns_and_returns_0_on_system_dep_failure(tmp_path, capsys):
    manager = _make_manager(tmp_path, _make_registry(_plugin_with_system_deps()))

    spec = SystemDepSpec(manager="go", package="github.com/org/go-tool@v1.2.3", binary="go-tool")
    failure_result = SystemDepResult(
        spec=spec,
        already_installed=False,
        success=False,
        error_message="Go runtime not found. Install Go from https://go.dev/dl/",
    )

    with patch.object(manager, "_run_uv", return_value=0):
        with patch("forge_cli.plugin_manager.install_system_deps", return_value=[failure_result]):
            with patch("forge_cli.plugin_manager.parse_system_deps", return_value=[spec]):
                rc = manager.install("go-tool")

    assert rc == 0
    captured = capsys.readouterr()
    assert "system deps need manual setup" in captured.out
    assert "may not function" in captured.out


def test_install_returns_nonzero_on_uv_failure(tmp_path):
    manager = _make_manager(tmp_path, _make_registry(_plugin_with_system_deps()))

    spec = SystemDepSpec(manager="go", package="github.com/org/go-tool@v1.2.3", binary="go-tool")
    success_result = SystemDepResult(
        spec=spec,
        already_installed=False,
        success=True,
        error_message=None,
    )

    with patch.object(manager, "_run_uv", return_value=1):
        with patch("forge_cli.plugin_manager.install_system_deps", return_value=[success_result]):
            with patch("forge_cli.plugin_manager.parse_system_deps", return_value=[spec]):
                rc = manager.install("go-tool")

    assert rc == 1


# ---------------------------------------------------------------------------
# remove() — system_deps note
# ---------------------------------------------------------------------------


def test_remove_prints_note_for_plugin_with_system_deps(tmp_path, capsys):
    manager = _make_manager(tmp_path, _make_registry(_plugin_with_system_deps()))

    with patch.object(manager, "_run_uv", return_value=0):
        rc = manager.remove("go-tool")

    assert rc == 0
    captured = capsys.readouterr()
    assert "System dependencies were not removed" in captured.out
    assert "go-tool" in captured.out


def test_remove_no_note_for_plugin_without_system_deps(tmp_path, capsys):
    manager = _make_manager(tmp_path, _make_registry())

    with patch.object(manager, "_run_uv", return_value=0):
        rc = manager.remove("plain-plugin")

    assert rc == 0
    captured = capsys.readouterr()
    assert "System dependencies" not in captured.out


# ---------------------------------------------------------------------------
# format_plugin_list() — verbose system_deps display
# ---------------------------------------------------------------------------


def test_verbose_list_shows_system_deps():
    plugins = {
        "go-tool": {
            "package": "forge-go-tool",
            "source": "git+https://example.com/go-tool.git",
            "ref": "v1.0.0",
            "description": "A Go tool wrapper",
            "plugin_type": "wrapper",
            "tags": ["security"],
            "private": False,
            "system_deps": [
                {"manager": "go", "package": "github.com/org/go-tool@v1.2.3", "binary": "go-tool"}
            ],
        }
    }
    output = format_plugin_list(plugins, verbose=True)
    assert "System deps:" in output
    assert "go-tool" in output
    assert "(go)" in output
    assert "github.com/org/go-tool@v1.2.3" in output


def test_verbose_list_no_system_deps_section_when_absent():
    plugins = {
        "plain-plugin": {
            "package": "forge-plain",
            "source": "git+https://example.com/plain.git",
            "ref": "v1.0.0",
            "description": "No system deps",
            "plugin_type": "native",
            "tags": [],
            "private": False,
        }
    }
    output = format_plugin_list(plugins, verbose=True)
    assert "System deps:" not in output
