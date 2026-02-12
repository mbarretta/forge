"""Tests for the DHI-Compete plugin definition and CLI."""

import argparse
import pytest
from unittest.mock import patch, MagicMock

from forge_gauge.plugins.dhi_compete import get_plugin, DHICompetePlugin
from forge_gauge.plugins.dhi_compete.plugin import configure_dhi_compete_parser, execute_dhi_compete


class TestDHICompetePlugin:
    """Tests for DHICompetePlugin class."""

    def test_plugin_properties(self):
        """Test plugin has correct properties."""
        plugin = get_plugin()

        assert plugin.name == "dhi-compete"
        assert plugin.version == "1.0.0"
        assert "Docker Hub" in plugin.description or "Chainguard" in plugin.description

    def test_plugin_provides_dhi_compete_command(self):
        """Test plugin provides the dhi-compete command."""
        plugin = get_plugin()
        commands = plugin.get_commands()

        assert len(commands) == 1
        assert commands[0].name == "dhi-compete"

    def test_plugin_is_available(self):
        """Test plugin availability check."""
        plugin = get_plugin()

        # Plugin should always be available (runs with reduced functionality)
        assert plugin.is_available() is True

    def test_plugin_discovery(self):
        """Test that plugin is discovered by registry."""
        from forge_gauge.core.plugin_registry import PluginRegistry

        registry = PluginRegistry()
        registry.discover_plugins()

        assert "dhi-compete" in registry.list_plugins()
        assert "dhi-compete" in registry.list_commands()


class TestDHICompeteParser:
    """Tests for dhi-compete command argument parsing."""

    def test_parser_alternative_and_chainguard(self):
        """Test parsing --alternative and --chainguard arguments."""
        parser = argparse.ArgumentParser()
        configure_dhi_compete_parser(parser)

        args = parser.parse_args([
            "--alternative", "nginx:latest",
            "--chainguard", "cgr.dev/chainguard/nginx:latest",
        ])

        assert args.alternative == "nginx:latest"
        assert args.chainguard == "cgr.dev/chainguard/nginx:latest"

    def test_parser_input_file(self):
        """Test parsing --input argument."""
        parser = argparse.ArgumentParser()
        configure_dhi_compete_parser(parser)

        args = parser.parse_args(["-i", "images.csv"])

        assert args.input.name == "images.csv"

    def test_parser_output_options(self):
        """Test parsing output options."""
        parser = argparse.ArgumentParser()
        configure_dhi_compete_parser(parser)

        args = parser.parse_args([
            "--alternative", "nginx:latest",
            "--chainguard", "cgr.dev/chainguard/nginx:latest",
            "-o", "reports",
            "-f", "html",
            "-c", "Acme Corp",
        ])

        assert args.output_dir.name == "reports"
        assert args.format == "html"
        assert args.customer_name == "Acme Corp"

    def test_parser_skip_options(self):
        """Test parsing skip analysis options."""
        parser = argparse.ArgumentParser()
        configure_dhi_compete_parser(parser)

        args = parser.parse_args([
            "--alternative", "nginx:latest",
            "--chainguard", "cgr.dev/chainguard/nginx:latest",
            "--skip-sbom",
            "--skip-vex",
            "--skip-attack-surface",
        ])

        assert args.skip_sbom is True
        assert args.skip_vex is True
        assert args.skip_attack_surface is True

    def test_parser_defaults(self):
        """Test parser default values."""
        parser = argparse.ArgumentParser()
        configure_dhi_compete_parser(parser)

        args = parser.parse_args([
            "--alternative", "nginx:latest",
            "--chainguard", "cgr.dev/chainguard/nginx:latest",
        ])

        assert args.output_dir.name == "output"
        assert args.format == "markdown"
        assert args.customer_name == "Customer"
        assert args.skip_sbom is False
        assert args.skip_vex is False
        assert args.skip_attack_surface is False
        assert args.verbose is False


class TestDHICompeteExecute:
    """Tests for dhi-compete command execution."""

    def test_execute_requires_input(self):
        """Test that execute fails without input."""
        parser = argparse.ArgumentParser()
        configure_dhi_compete_parser(parser)
        args = parser.parse_args([])

        result = execute_dhi_compete(args)

        assert result == 1  # Failure

    def test_execute_requires_both_images(self):
        """Test that execute fails with only one image."""
        parser = argparse.ArgumentParser()
        configure_dhi_compete_parser(parser)

        # Only alternative
        args = parser.parse_args(["--alternative", "nginx:latest"])
        result = execute_dhi_compete(args)
        assert result == 1

        # Only chainguard
        args = parser.parse_args(["--chainguard", "cgr.dev/chainguard/nginx:latest"])
        result = execute_dhi_compete(args)
        assert result == 1

    @patch("plugins.dhi_compete.analyzer.DHICompeteAnalyzer")
    def test_execute_calls_analyzer(self, mock_analyzer_class):
        """Test that execute creates and runs analyzer."""
        mock_analyzer = MagicMock()
        mock_analyzer.run.return_value = 0
        mock_analyzer_class.return_value = mock_analyzer

        parser = argparse.ArgumentParser()
        configure_dhi_compete_parser(parser)
        args = parser.parse_args([
            "--alternative", "nginx:latest",
            "--chainguard", "cgr.dev/chainguard/nginx:latest",
        ])

        result = execute_dhi_compete(args)

        mock_analyzer_class.assert_called_once_with(args)
        mock_analyzer.run.assert_called_once()
        assert result == 0
