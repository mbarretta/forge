"""Tests for external plugin management utilities."""

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from forge_gauge.core.external_plugins import (
    InstalledPlugin,
    PluginManifest,
    PluginRegistryFile,
    PluginSource,
    check_tool_available,
    derive_plugin_name,
    validate_plugin_structure,
)


class TestPluginSource:
    """Tests for PluginSource dataclass."""

    def test_create_plugin_source(self):
        """Test creating a PluginSource."""
        source = PluginSource(
            type="github",
            repo="owner/repo",
            branch="main",
            commit="abc123",
        )

        assert source.type == "github"
        assert source.repo == "owner/repo"
        assert source.branch == "main"
        assert source.commit == "abc123"


class TestInstalledPlugin:
    """Tests for InstalledPlugin dataclass."""

    def test_create_installed_plugin(self):
        """Test creating an InstalledPlugin."""
        now = datetime.now(timezone.utc)
        source = PluginSource(
            type="github",
            repo="owner/repo",
            branch="main",
            commit="abc123",
        )
        plugin = InstalledPlugin(
            name="my-plugin",
            version="1.0.0",
            source=source,
            installed_at=now,
            updated_at=now,
            path=Path("/tmp/my-plugin"),
        )

        assert plugin.name == "my-plugin"
        assert plugin.version == "1.0.0"
        assert plugin.source == source

    def test_to_dict(self):
        """Test converting InstalledPlugin to dictionary."""
        now = datetime.now(timezone.utc)
        source = PluginSource(
            type="github",
            repo="owner/repo",
            branch="main",
            commit="abc123",
        )
        plugin = InstalledPlugin(
            name="my-plugin",
            version="1.0.0",
            source=source,
            installed_at=now,
            updated_at=now,
            path=Path("/tmp/my-plugin"),
        )

        data = plugin.to_dict()

        assert data["name"] == "my-plugin"
        assert data["version"] == "1.0.0"
        assert data["source"]["type"] == "github"
        assert data["source"]["repo"] == "owner/repo"
        assert data["path"] == "/tmp/my-plugin"

    def test_from_dict(self):
        """Test creating InstalledPlugin from dictionary."""
        now = datetime.now(timezone.utc)
        data = {
            "name": "my-plugin",
            "version": "1.0.0",
            "source": {
                "type": "github",
                "repo": "owner/repo",
                "branch": "main",
                "commit": "abc123",
            },
            "installed_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "path": "/tmp/my-plugin",
        }

        plugin = InstalledPlugin.from_dict(data)

        assert plugin.name == "my-plugin"
        assert plugin.version == "1.0.0"
        assert plugin.source.repo == "owner/repo"
        assert plugin.path == Path("/tmp/my-plugin")

    def test_round_trip(self):
        """Test that to_dict and from_dict are inverses."""
        now = datetime.now(timezone.utc)
        source = PluginSource(
            type="github",
            repo="owner/repo",
            branch="main",
            commit="abc123",
        )
        original = InstalledPlugin(
            name="my-plugin",
            version="1.0.0",
            source=source,
            installed_at=now,
            updated_at=now,
            path=Path("/tmp/my-plugin"),
        )

        data = original.to_dict()
        restored = InstalledPlugin.from_dict(data)

        assert restored.name == original.name
        assert restored.version == original.version
        assert restored.source.repo == original.source.repo


class TestPluginManifest:
    """Tests for PluginManifest."""

    def test_create_manifest(self):
        """Test creating a PluginManifest."""
        manifest = PluginManifest(
            name="my-plugin",
            version="1.0.0",
            description="Test plugin",
            python_dependencies=["requests>=2.28.0"],
        )

        assert manifest.name == "my-plugin"
        assert manifest.version == "1.0.0"
        assert "requests>=2.28.0" in manifest.python_dependencies

    def test_from_file_not_exists(self):
        """Test loading manifest from non-existent file."""
        result = PluginManifest.from_file(Path("/nonexistent/plugin.yaml"))
        assert result is None

    def test_from_file_valid(self):
        """Test loading manifest from valid file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("""
name: test-plugin
version: 2.0.0
description: A test plugin
author: test@example.com

build:
  python_dependencies:
    - requests>=2.28.0
    - pyyaml
  setup_commands:
    - echo "hello"
  requires:
    - git
""")
            f.flush()
            path = Path(f.name)

        try:
            manifest = PluginManifest.from_file(path)

            assert manifest is not None
            assert manifest.name == "test-plugin"
            assert manifest.version == "2.0.0"
            assert manifest.description == "A test plugin"
            assert manifest.author == "test@example.com"
            assert "requests>=2.28.0" in manifest.python_dependencies
            assert "pyyaml" in manifest.python_dependencies
            assert 'echo "hello"' in manifest.setup_commands
            assert "git" in manifest.requires
        finally:
            path.unlink()

    def test_from_requirements_txt_not_exists(self):
        """Test loading from non-existent requirements.txt."""
        result = PluginManifest.from_requirements_txt(
            Path("/nonexistent/requirements.txt"),
            "test-plugin",
        )
        assert result is None

    def test_from_requirements_txt_valid(self):
        """Test loading from valid requirements.txt."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("""
requests>=2.28.0
# This is a comment
pyyaml~=6.0

click
""")
            f.flush()
            path = Path(f.name)

        try:
            manifest = PluginManifest.from_requirements_txt(path, "test-plugin")

            assert manifest is not None
            assert manifest.name == "test-plugin"
            assert "requests>=2.28.0" in manifest.python_dependencies
            assert "pyyaml~=6.0" in manifest.python_dependencies
            assert "click" in manifest.python_dependencies
            # Comments should be excluded
            assert "# This is a comment" not in manifest.python_dependencies
        finally:
            path.unlink()


class TestPluginRegistryFile:
    """Tests for PluginRegistryFile."""

    def test_load_nonexistent(self):
        """Test loading from non-existent file returns empty dict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = PluginRegistryFile(Path(tmpdir) / "registry.yaml")
            result = registry.load()
            assert result == {}

    def test_save_and_load(self):
        """Test saving and loading plugins."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.yaml"
            registry = PluginRegistryFile(registry_path)

            now = datetime.now(timezone.utc)
            source = PluginSource(
                type="github",
                repo="owner/repo",
                branch="main",
                commit="abc123",
            )
            plugin = InstalledPlugin(
                name="my-plugin",
                version="1.0.0",
                source=source,
                installed_at=now,
                updated_at=now,
                path=Path("/tmp/my-plugin"),
            )

            registry.save({"my-plugin": plugin})

            loaded = registry.load()
            assert "my-plugin" in loaded
            assert loaded["my-plugin"].version == "1.0.0"

    def test_add_plugin(self):
        """Test adding a plugin to registry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.yaml"
            registry = PluginRegistryFile(registry_path)

            now = datetime.now(timezone.utc)
            source = PluginSource(
                type="github",
                repo="owner/repo",
                branch="main",
                commit="abc123",
            )
            plugin = InstalledPlugin(
                name="my-plugin",
                version="1.0.0",
                source=source,
                installed_at=now,
                updated_at=now,
                path=Path("/tmp/my-plugin"),
            )

            registry.add(plugin)

            loaded = registry.load()
            assert "my-plugin" in loaded

    def test_remove_plugin(self):
        """Test removing a plugin from registry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.yaml"
            registry = PluginRegistryFile(registry_path)

            now = datetime.now(timezone.utc)
            source = PluginSource(
                type="github",
                repo="owner/repo",
                branch="main",
                commit="abc123",
            )
            plugin = InstalledPlugin(
                name="my-plugin",
                version="1.0.0",
                source=source,
                installed_at=now,
                updated_at=now,
                path=Path("/tmp/my-plugin"),
            )

            registry.add(plugin)
            assert registry.remove("my-plugin") is True

            loaded = registry.load()
            assert "my-plugin" not in loaded

    def test_remove_nonexistent(self):
        """Test removing a non-existent plugin."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.yaml"
            registry = PluginRegistryFile(registry_path)

            result = registry.remove("nonexistent")
            assert result is False

    def test_get_plugin(self):
        """Test getting a specific plugin."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.yaml"
            registry = PluginRegistryFile(registry_path)

            now = datetime.now(timezone.utc)
            source = PluginSource(
                type="github",
                repo="owner/repo",
                branch="main",
                commit="abc123",
            )
            plugin = InstalledPlugin(
                name="my-plugin",
                version="1.0.0",
                source=source,
                installed_at=now,
                updated_at=now,
                path=Path("/tmp/my-plugin"),
            )

            registry.add(plugin)

            result = registry.get("my-plugin")
            assert result is not None
            assert result.name == "my-plugin"

    def test_get_nonexistent(self):
        """Test getting a non-existent plugin."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.yaml"
            registry = PluginRegistryFile(registry_path)

            result = registry.get("nonexistent")
            assert result is None


class TestCheckToolAvailable:
    """Tests for check_tool_available function."""

    def test_git_available(self):
        """Test that git is available (should be on most systems)."""
        # This might fail on systems without git, but it's a reasonable assumption
        result = check_tool_available("git")
        # We just check it returns a boolean, not the value
        assert isinstance(result, bool)

    def test_nonexistent_tool(self):
        """Test that a non-existent tool is not available."""
        result = check_tool_available("nonexistent-tool-xyz-123")
        assert result is False


class TestDerivePluginName:
    """Tests for derive_plugin_name function."""

    def test_from_manifest(self):
        """Test deriving name from manifest."""
        manifest = PluginManifest(name="custom-name", version="1.0.0")
        result = derive_plugin_name("owner/repo", manifest)
        assert result == "custom-name"

    def test_from_repo_simple(self):
        """Test deriving name from simple repo name."""
        result = derive_plugin_name("owner/my-analyzer", None)
        assert result == "my-analyzer"

    def test_strips_gauge_prefix(self):
        """Test that gauge- prefix is stripped."""
        result = derive_plugin_name("owner/gauge-analytics", None)
        assert result == "analytics"

    def test_strips_gauge_underscore_prefix(self):
        """Test that gauge_ prefix is stripped."""
        result = derive_plugin_name("owner/gauge_analytics", None)
        assert result == "analytics"

    def test_strips_plugin_suffix(self):
        """Test that -plugin suffix is stripped."""
        result = derive_plugin_name("owner/analytics-plugin", None)
        assert result == "analytics"

    def test_strips_gauge_suffix(self):
        """Test that -gauge suffix is stripped."""
        result = derive_plugin_name("owner/analytics-gauge", None)
        assert result == "analytics"

    def test_strips_both_prefix_and_suffix(self):
        """Test stripping both prefix and suffix."""
        result = derive_plugin_name("owner/gauge-analytics-plugin", None)
        assert result == "analytics"


class TestValidatePluginStructure:
    """Tests for validate_plugin_structure function."""

    def test_valid_plugin_with_init(self):
        """Test validating a plugin with __init__.py."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir)
            init_file = plugin_dir / "__init__.py"
            init_file.write_text("""
from plugin import MyPlugin

def get_plugin():
    return MyPlugin()

Plugin = MyPlugin
""")

            valid, message = validate_plugin_structure(plugin_dir)
            assert valid is True

    def test_valid_plugin_with_plugin_py(self):
        """Test validating a plugin with plugin.py."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir)
            plugin_file = plugin_dir / "plugin.py"
            plugin_file.write_text("""
from forge_gauge.core.command_plugin import GaugePlugin

class MyPlugin(GaugePlugin):
    pass
""")

            valid, message = validate_plugin_structure(plugin_dir)
            assert valid is True

    def test_invalid_plugin_no_files(self):
        """Test validating a plugin with no required files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir)

            valid, message = validate_plugin_structure(plugin_dir)
            assert valid is False
            assert "__init__.py" in message or "plugin.py" in message

    def test_invalid_plugin_no_exports(self):
        """Test validating a plugin without required exports."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir)
            init_file = plugin_dir / "__init__.py"
            init_file.write_text("""
# Just a comment, no plugin exports
x = 1
""")

            valid, message = validate_plugin_structure(plugin_dir)
            assert valid is False
            assert "get_plugin" in message or "Plugin" in message
