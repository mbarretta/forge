"""Tests for plugin registry and command plugin infrastructure."""

import argparse
import pytest
from typing import Optional

from forge_gauge.core.command_plugin import CommandDefinition, GaugePlugin
from forge_gauge.core.plugin_registry import PluginRegistry


class MockPlugin(GaugePlugin):
    """A mock plugin for testing."""

    def __init__(
        self,
        name: str = "mock-plugin",
        version: str = "1.0.0",
        description: str = "Mock plugin for testing",
        commands: Optional[list[CommandDefinition]] = None,
        available: bool = True,
    ):
        self._name = name
        self._version = version
        self._description = description
        self._commands = commands or []
        self._available = available

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return self._version

    @property
    def description(self) -> str:
        return self._description

    def get_commands(self) -> list[CommandDefinition]:
        return self._commands

    def is_available(self) -> bool:
        return self._available


def make_command(name: str, description: str = "Test command") -> CommandDefinition:
    """Helper to create a command definition for testing."""
    return CommandDefinition(
        name=name,
        description=description,
        configure_parser=lambda p: None,
        execute=lambda a: 0,
    )


class TestCommandDefinition:
    """Tests for CommandDefinition dataclass."""

    def test_create_command_definition(self):
        """Test creating a CommandDefinition."""
        def configure(parser: argparse.ArgumentParser) -> None:
            parser.add_argument("--test", help="Test arg")

        def execute(args: argparse.Namespace) -> int:
            return 0

        cmd = CommandDefinition(
            name="test-cmd",
            description="A test command",
            configure_parser=configure,
            execute=execute,
        )

        assert cmd.name == "test-cmd"
        assert cmd.description == "A test command"
        assert cmd.configure_parser is configure
        assert cmd.execute is execute

    def test_command_definition_is_frozen(self):
        """Test that CommandDefinition is immutable (frozen dataclass)."""
        cmd = make_command("test")

        with pytest.raises(AttributeError):
            cmd.name = "new-name"


class TestGaugePlugin:
    """Tests for GaugePlugin abstract base class."""

    def test_mock_plugin_properties(self):
        """Test that mock plugin implements required properties."""
        plugin = MockPlugin(
            name="test-plugin",
            version="2.0.0",
            description="Test description",
        )

        assert plugin.name == "test-plugin"
        assert plugin.version == "2.0.0"
        assert plugin.description == "Test description"

    def test_plugin_default_is_available(self):
        """Test that plugins are available by default."""
        plugin = MockPlugin()
        assert plugin.is_available() is True

    def test_plugin_unavailable(self):
        """Test plugin availability check."""
        plugin = MockPlugin(available=False)
        assert plugin.is_available() is False

    def test_plugin_with_commands(self):
        """Test plugin with commands."""
        commands = [
            make_command("cmd1", "First command"),
            make_command("cmd2", "Second command"),
        ]
        plugin = MockPlugin(commands=commands)

        assert len(plugin.get_commands()) == 2
        assert plugin.get_commands()[0].name == "cmd1"
        assert plugin.get_commands()[1].name == "cmd2"


class TestPluginRegistry:
    """Tests for PluginRegistry."""

    def test_empty_registry(self):
        """Test empty registry state."""
        registry = PluginRegistry()

        assert registry.list_plugins() == []
        assert registry.list_commands() == []

    def test_register_plugin(self):
        """Test registering a plugin."""
        registry = PluginRegistry()
        plugin = MockPlugin(name="test-plugin")

        registry.register(plugin)

        assert "test-plugin" in registry.list_plugins()

    def test_register_plugin_with_commands(self):
        """Test registering a plugin with commands."""
        registry = PluginRegistry()
        commands = [make_command("test-cmd")]
        plugin = MockPlugin(name="test-plugin", commands=commands)

        registry.register(plugin)

        assert "test-cmd" in registry.list_commands()

    def test_get_command(self):
        """Test getting a command by name."""
        registry = PluginRegistry()
        cmd = make_command("my-cmd", "My command description")
        plugin = MockPlugin(commands=[cmd])

        registry.register(plugin)
        result = registry.get_command("my-cmd")

        assert result is not None
        assert result.name == "my-cmd"
        assert result.description == "My command description"

    def test_get_command_not_found(self):
        """Test getting a non-existent command."""
        registry = PluginRegistry()

        result = registry.get_command("non-existent")

        assert result is None

    def test_get_plugin(self):
        """Test getting a plugin by name."""
        registry = PluginRegistry()
        plugin = MockPlugin(name="test-plugin")

        registry.register(plugin)
        result = registry.get_plugin("test-plugin")

        assert result is plugin

    def test_get_plugin_not_found(self):
        """Test getting a non-existent plugin."""
        registry = PluginRegistry()

        result = registry.get_plugin("non-existent")

        assert result is None

    def test_get_plugin_for_command(self):
        """Test getting the plugin that provides a command."""
        registry = PluginRegistry()
        cmd = make_command("my-cmd")
        plugin = MockPlugin(name="provider-plugin", commands=[cmd])

        registry.register(plugin)
        result = registry.get_plugin_for_command("my-cmd")

        assert result is plugin

    def test_duplicate_plugin_raises_error(self):
        """Test that registering a plugin with duplicate name raises error."""
        registry = PluginRegistry()
        plugin1 = MockPlugin(name="dupe")
        plugin2 = MockPlugin(name="dupe")

        registry.register(plugin1)

        with pytest.raises(ValueError) as exc_info:
            registry.register(plugin2)

        assert "already registered" in str(exc_info.value)

    def test_duplicate_command_raises_error(self):
        """Test that registering plugins with duplicate command names raises error."""
        registry = PluginRegistry()
        cmd = make_command("shared-cmd")
        plugin1 = MockPlugin(name="plugin1", commands=[cmd])
        plugin2 = MockPlugin(name="plugin2", commands=[cmd])

        registry.register(plugin1)

        with pytest.raises(ValueError) as exc_info:
            registry.register(plugin2)

        assert "conflicts with existing command" in str(exc_info.value)

    def test_unavailable_plugin_not_registered(self):
        """Test that unavailable plugins are skipped during registration."""
        registry = PluginRegistry()
        plugin = MockPlugin(name="unavailable", available=False)

        registry.register(plugin)

        assert "unavailable" not in registry.list_plugins()

    def test_get_all_commands(self):
        """Test getting all commands with their plugins."""
        registry = PluginRegistry()
        cmd1 = make_command("cmd-a", "Command A")
        cmd2 = make_command("cmd-b", "Command B")
        plugin1 = MockPlugin(name="plugin1", commands=[cmd1])
        plugin2 = MockPlugin(name="plugin2", commands=[cmd2])

        registry.register(plugin1)
        registry.register(plugin2)

        all_cmds = registry.get_all_commands()

        assert len(all_cmds) == 2
        # Results should be sorted by command name
        assert all_cmds[0][0] == "cmd-a"
        assert all_cmds[1][0] == "cmd-b"

    def test_list_commands_sorted(self):
        """Test that list_commands returns sorted command names."""
        registry = PluginRegistry()
        commands = [
            make_command("zebra"),
            make_command("alpha"),
            make_command("beta"),
        ]
        plugin = MockPlugin(commands=commands)

        registry.register(plugin)
        result = registry.list_commands()

        assert result == ["alpha", "beta", "zebra"]

    def test_list_plugins_sorted(self):
        """Test that list_plugins returns sorted plugin names."""
        registry = PluginRegistry()
        registry.register(MockPlugin(name="zebra-plugin"))
        registry.register(MockPlugin(name="alpha-plugin"))
        registry.register(MockPlugin(name="beta-plugin"))

        result = registry.list_plugins()

        assert result == ["alpha-plugin", "beta-plugin", "zebra-plugin"]


class TestGaugeCorePlugin:
    """Tests for the gauge-core plugin."""

    def test_gauge_core_plugin_loads(self):
        """Test that gauge-core plugin can be loaded."""
        from forge_gauge.constants import __version__
        from forge_gauge.plugins.gauge_core import get_plugin

        plugin = get_plugin()

        assert plugin.name == "gauge-core"
        assert plugin.version == __version__

    def test_gauge_core_provides_scan_command(self):
        """Test that gauge-core provides the scan command."""
        from forge_gauge.plugins.gauge_core import get_plugin

        plugin = get_plugin()
        commands = plugin.get_commands()
        command_names = [cmd.name for cmd in commands]

        assert "scan" in command_names

    def test_gauge_core_provides_match_command(self):
        """Test that gauge-core provides the match command."""
        from forge_gauge.plugins.gauge_core import get_plugin

        plugin = get_plugin()
        commands = plugin.get_commands()
        command_names = [cmd.name for cmd in commands]

        assert "match" in command_names

    def test_scan_command_configures_parser(self):
        """Test that scan command properly configures its parser."""
        from forge_gauge.plugins.gauge_core import get_plugin

        plugin = get_plugin()
        scan_cmd = next(cmd for cmd in plugin.get_commands() if cmd.name == "scan")

        parser = argparse.ArgumentParser()
        scan_cmd.configure_parser(parser)

        # Parse with minimal args
        args = parser.parse_args(["-i", "test.csv"])

        # input is now a string to support both file paths and image references
        assert args.input == "test.csv"

    def test_match_command_configures_parser(self):
        """Test that match command properly configures its parser."""
        from forge_gauge.plugins.gauge_core import get_plugin

        plugin = get_plugin()
        match_cmd = next(cmd for cmd in plugin.get_commands() if cmd.name == "match")

        parser = argparse.ArgumentParser()
        match_cmd.configure_parser(parser)

        # Parse with minimal args
        args = parser.parse_args(["-i", "test.txt"])

        assert args.input.name == "test.txt"


class TestPluginDiscovery:
    """Tests for plugin auto-discovery."""

    def test_discover_plugins_finds_gauge_core(self):
        """Test that discover_plugins finds the gauge-core plugin."""
        registry = PluginRegistry()

        registry.discover_plugins()

        assert "gauge-core" in registry.list_plugins()
        assert "scan" in registry.list_commands()
        assert "match" in registry.list_commands()

    def test_discover_plugins_finds_plugin_manager(self):
        """Test that discover_plugins finds the plugin-manager plugin."""
        registry = PluginRegistry()

        registry.discover_plugins()

        assert "plugin-manager" in registry.list_plugins()
        assert "plugin" in registry.list_commands()

    def test_discover_external_plugins_empty_directory(self):
        """Test that discover_external_plugins handles missing directory."""
        registry = PluginRegistry()

        # Should not raise even if ~/.gauge/plugins doesn't exist
        registry.discover_external_plugins()

        # Should still work (may have external plugins if installed)
        assert isinstance(registry.list_plugins(), list)
