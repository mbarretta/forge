"""Tests for plugin-manager plugin."""

import argparse
import pytest

from forge_gauge.plugins.plugin_manager import get_plugin, Plugin
from forge_gauge.plugins.plugin_manager.plugin import PluginManagerPlugin


class TestPluginManagerPlugin:
    """Tests for PluginManagerPlugin class."""

    def test_get_plugin_returns_instance(self):
        """Test that get_plugin returns a PluginManagerPlugin instance."""
        plugin = get_plugin()
        assert isinstance(plugin, PluginManagerPlugin)

    def test_plugin_class_export(self):
        """Test that Plugin is exported correctly."""
        assert Plugin is PluginManagerPlugin

    def test_plugin_name(self):
        """Test plugin name property."""
        plugin = get_plugin()
        assert plugin.name == "plugin-manager"

    def test_plugin_version(self):
        """Test plugin version property."""
        plugin = get_plugin()
        assert plugin.version == "1.0.0"

    def test_plugin_description(self):
        """Test plugin description property."""
        plugin = get_plugin()
        assert "plugin" in plugin.description.lower()

    def test_plugin_is_available(self):
        """Test plugin is available by default."""
        plugin = get_plugin()
        assert plugin.is_available() is True

    def test_plugin_provides_plugin_command(self):
        """Test that plugin provides the plugin command."""
        plugin = get_plugin()
        commands = plugin.get_commands()
        command_names = [cmd.name for cmd in commands]

        assert "plugin" in command_names

    def test_plugin_command_configures_parser(self):
        """Test that plugin command configures its parser with subcommands."""
        plugin = get_plugin()
        plugin_cmd = next(cmd for cmd in plugin.get_commands() if cmd.name == "plugin")

        parser = argparse.ArgumentParser()
        plugin_cmd.configure_parser(parser)

        # Parse with install subcommand
        args = parser.parse_args(["install", "owner/repo"])
        assert args.plugin_command == "install"
        assert args.repository == "owner/repo"

    def test_plugin_command_list_subcommand(self):
        """Test list subcommand parsing."""
        plugin = get_plugin()
        plugin_cmd = next(cmd for cmd in plugin.get_commands() if cmd.name == "plugin")

        parser = argparse.ArgumentParser()
        plugin_cmd.configure_parser(parser)

        args = parser.parse_args(["list"])
        assert args.plugin_command == "list"

    def test_plugin_command_list_json_flag(self):
        """Test list --json flag parsing."""
        plugin = get_plugin()
        plugin_cmd = next(cmd for cmd in plugin.get_commands() if cmd.name == "plugin")

        parser = argparse.ArgumentParser()
        plugin_cmd.configure_parser(parser)

        args = parser.parse_args(["list", "--json"])
        assert args.plugin_command == "list"
        assert args.json is True

    def test_plugin_command_update_subcommand(self):
        """Test update subcommand parsing."""
        plugin = get_plugin()
        plugin_cmd = next(cmd for cmd in plugin.get_commands() if cmd.name == "plugin")

        parser = argparse.ArgumentParser()
        plugin_cmd.configure_parser(parser)

        args = parser.parse_args(["update", "my-plugin"])
        assert args.plugin_command == "update"
        assert args.name == "my-plugin"

    def test_plugin_command_update_all_flag(self):
        """Test update --all flag parsing."""
        plugin = get_plugin()
        plugin_cmd = next(cmd for cmd in plugin.get_commands() if cmd.name == "plugin")

        parser = argparse.ArgumentParser()
        plugin_cmd.configure_parser(parser)

        args = parser.parse_args(["update", "--all"])
        assert args.plugin_command == "update"
        assert args.update_all is True

    def test_plugin_command_remove_subcommand(self):
        """Test remove subcommand parsing."""
        plugin = get_plugin()
        plugin_cmd = next(cmd for cmd in plugin.get_commands() if cmd.name == "plugin")

        parser = argparse.ArgumentParser()
        plugin_cmd.configure_parser(parser)

        args = parser.parse_args(["remove", "my-plugin"])
        assert args.plugin_command == "remove"
        assert args.name == "my-plugin"

    def test_plugin_command_install_branch_option(self):
        """Test install --branch option parsing."""
        plugin = get_plugin()
        plugin_cmd = next(cmd for cmd in plugin.get_commands() if cmd.name == "plugin")

        parser = argparse.ArgumentParser()
        plugin_cmd.configure_parser(parser)

        args = parser.parse_args(["install", "owner/repo", "--branch", "v1.0.0"])
        assert args.plugin_command == "install"
        assert args.repository == "owner/repo"
        assert args.branch == "v1.0.0"

    def test_plugin_command_install_force_option(self):
        """Test install --force option parsing."""
        plugin = get_plugin()
        plugin_cmd = next(cmd for cmd in plugin.get_commands() if cmd.name == "plugin")

        parser = argparse.ArgumentParser()
        plugin_cmd.configure_parser(parser)

        args = parser.parse_args(["install", "owner/repo", "--force"])
        assert args.plugin_command == "install"
        assert args.force is True
