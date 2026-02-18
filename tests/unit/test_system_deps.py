"""Tests for forge_cli.system_deps."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from forge_cli.system_deps import (
    SystemDepResult,
    SystemDepSpec,
    install_system_deps,
    parse_system_deps,
)


# ---------------------------------------------------------------------------
# parse_system_deps
# ---------------------------------------------------------------------------


def test_parse_empty_list():
    assert parse_system_deps({}) == []
    assert parse_system_deps({"system_deps": []}) == []


def test_parse_valid():
    info = {
        "system_deps": [
            {"manager": "go", "package": "github.com/org/tool@v1.0.0", "binary": "tool"},
            {"manager": "npm", "package": "@org/ts-tool@2.0.0", "binary": "ts-tool"},
        ]
    }
    specs = parse_system_deps(info)
    assert len(specs) == 2
    assert specs[0] == SystemDepSpec(manager="go", package="github.com/org/tool@v1.0.0", binary="tool")
    assert specs[1] == SystemDepSpec(manager="npm", package="@org/ts-tool@2.0.0", binary="ts-tool")


def test_parse_unknown_manager_skipped(capsys):
    info = {
        "system_deps": [
            {"manager": "cargo", "package": "my-crate", "binary": "my-crate"},
        ]
    }
    specs = parse_system_deps(info)
    assert specs == []
    captured = capsys.readouterr()
    assert "unknown manager 'cargo'" in captured.err


def test_parse_malformed_entry_skipped(capsys):
    info = {
        "system_deps": [
            {"manager": "go"},  # missing package and binary
        ]
    }
    specs = parse_system_deps(info)
    assert specs == []
    captured = capsys.readouterr()
    assert "malformed" in captured.err.lower()


# ---------------------------------------------------------------------------
# install_system_deps — skip when binary present
# ---------------------------------------------------------------------------


def test_install_skips_when_binary_present():
    spec = SystemDepSpec(manager="go", package="github.com/org/tool@v1.0.0", binary="tool")
    with patch("forge_cli.system_deps.shutil.which", return_value="/usr/local/bin/tool"):
        with patch("forge_cli.system_deps.subprocess.run") as mock_run:
            results = install_system_deps([spec])

    assert len(results) == 1
    assert results[0].already_installed is True
    assert results[0].success is True
    mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# _install_go
# ---------------------------------------------------------------------------


def test_go_install_success():
    spec = SystemDepSpec(manager="go", package="github.com/org/tool@v1.0.0", binary="tool")

    def fake_which(name):
        return None if name == "tool" else "/usr/local/go/bin/go"

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stderr = ""

    with patch("forge_cli.system_deps.shutil.which", side_effect=fake_which):
        with patch("forge_cli.system_deps.subprocess.run", return_value=mock_result) as mock_run:
            results = install_system_deps([spec])

    assert results[0].success is True
    assert results[0].already_installed is False
    mock_run.assert_called_once_with(
        ["go", "install", "github.com/org/tool@v1.0.0"],
        capture_output=True,
        text=True,
    )


def test_go_runtime_not_found():
    spec = SystemDepSpec(manager="go", package="github.com/org/tool@v1.0.0", binary="tool")

    with patch("forge_cli.system_deps.shutil.which", return_value=None):
        with patch("forge_cli.system_deps.subprocess.run") as mock_run:
            results = install_system_deps([spec])

    assert results[0].success is False
    assert "https://go.dev/dl/" in results[0].error_message
    mock_run.assert_not_called()


def test_go_subprocess_failure():
    spec = SystemDepSpec(manager="go", package="github.com/org/tool@v1.0.0", binary="tool")

    def fake_which(name):
        return None if name == "tool" else "/usr/local/go/bin/go"

    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "build failed: module not found"

    with patch("forge_cli.system_deps.shutil.which", side_effect=fake_which):
        with patch("forge_cli.system_deps.subprocess.run", return_value=mock_result):
            results = install_system_deps([spec])

    assert results[0].success is False
    assert "build failed: module not found" in results[0].error_message


# ---------------------------------------------------------------------------
# _install_npm
# ---------------------------------------------------------------------------


def test_npm_install_success():
    spec = SystemDepSpec(manager="npm", package="@org/ts-tool@2.0.0", binary="ts-tool")

    def fake_which(name):
        return None if name == "ts-tool" else "/usr/local/bin/npm"

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stderr = ""

    with patch("forge_cli.system_deps.shutil.which", side_effect=fake_which):
        with patch("forge_cli.system_deps.subprocess.run", return_value=mock_result) as mock_run:
            results = install_system_deps([spec])

    assert results[0].success is True
    mock_run.assert_called_once_with(
        ["npm", "install", "-g", "@org/ts-tool@2.0.0"],
        capture_output=True,
        text=True,
    )


def test_npm_runtime_not_found():
    spec = SystemDepSpec(manager="npm", package="@org/ts-tool@2.0.0", binary="ts-tool")

    with patch("forge_cli.system_deps.shutil.which", return_value=None):
        with patch("forge_cli.system_deps.subprocess.run") as mock_run:
            results = install_system_deps([spec])

    assert results[0].success is False
    assert "https://nodejs.org/" in results[0].error_message
    mock_run.assert_not_called()
