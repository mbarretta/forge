"""
Tests for the coverage plugin wrapper.

Tests plugin loading, parameter validation, and args conversion.
"""

from pathlib import Path

from forge_core.plugin import ResultStatus, ToolParam

from forge_coverage.plugin import CoveragePlugin


class TestPluginBasics:
    """Test basic plugin functionality."""

    def test_create_plugin(self, plugin):
        """Test that create_plugin returns a CoveragePlugin instance."""
        assert isinstance(plugin, CoveragePlugin)

    def test_plugin_metadata(self, plugin):
        """Test plugin metadata is correct."""
        assert plugin.name == "coverage"
        assert plugin.version == "1.0.0"
        assert "Python" in plugin.description
        assert "JavaScript" in plugin.description

    def test_get_params_returns_list(self, plugin):
        """Test that get_params returns a list of ToolParam."""
        params = plugin.get_params()
        assert isinstance(params, list)
        assert len(params) > 0
        assert all(isinstance(p, ToolParam) for p in params)

    def test_required_parameters_present(self, plugin):
        """Test that key parameters are declared."""
        params = plugin.get_params()
        param_names = [p.name for p in params]

        # Check for essential parameters
        assert "requirements-file" in param_names
        assert "mode" in param_names
        assert "arch" in param_names
        assert "python-version" in param_names
        assert "issue" in param_names  # API mode
        assert "verbose" in param_names

    def test_mode_parameter_choices(self, plugin):
        """Test that mode parameter has correct choices."""
        params = plugin.get_params()
        mode_param = next(p for p in params if p.name == "mode")

        assert mode_param.choices is not None
        assert "index" in mode_param.choices
        assert "js" in mode_param.choices
        assert "api" in mode_param.choices
        assert mode_param.default == "index"


class TestParameterValidation:
    """Test parameter validation logic."""

    def test_csv_mode_requires_csv_arg(self, plugin, ctx):
        """Test that csv mode requires --csv argument."""
        result = plugin.run({"mode": "csv"}, ctx)

        assert result.status == ResultStatus.FAILURE
        assert "csv" in result.summary.lower()

    def test_api_mode_requires_issue(self, plugin, ctx):
        """Test that api mode requires --issue argument."""
        result = plugin.run({"mode": "api"}, ctx)

        assert result.status == ResultStatus.FAILURE
        assert "issue" in result.summary.lower()

    def test_api_mode_force_requires_refresh(self, plugin, ctx):
        """Test that --force requires --refresh in api mode."""
        result = plugin.run({
            "mode": "api",
            "issue": "12345",
            "force": True,
            "refresh": False,
        }, ctx)

        assert result.status == ResultStatus.FAILURE
        assert "force" in result.summary.lower()
        assert "refresh" in result.summary.lower()

    def test_non_api_mode_requires_requirements_file(self, plugin, ctx):
        """Test that non-api modes require requirements-file."""
        # Test index mode without requirements-file
        result = plugin.run({"mode": "index"}, ctx)

        assert result.status == ResultStatus.FAILURE
        assert "requirements" in result.summary.lower()


class TestArgsConversion:
    """Test conversion of args dict to argparse.Namespace."""

    def test_args_to_namespace_basic(self, plugin):
        """Test basic args conversion."""
        args = {
            "requirements-file": "/tmp/test.txt",
            "mode": "index",
            "verbose": True,
        }

        ns = plugin._args_to_namespace(args)

        assert ns.mode == "index"
        assert ns.verbose is True
        assert len(ns.requirements_file) == 1
        assert ns.requirements_file[0] == Path("/tmp/test.txt")

    def test_args_to_namespace_filters(self, plugin):
        """Test filter argument conversion."""
        args = {
            "requirements-file": "/tmp/test.txt",
            "arch": "amd64",
            "python-version": "3.11",
            "manylinux-variant": "2_28",
            "workers": 20,
        }

        ns = plugin._args_to_namespace(args)

        assert ns.arch == "amd64"
        assert ns.python_version == "3.11"
        assert ns.manylinux_variant == "2_28"
        assert ns.workers == 20

    def test_args_to_namespace_api_mode(self, plugin):
        """Test API mode argument conversion."""
        args = {
            "mode": "api",
            "issue": "12345",
            "token": "test-token",
            "api-url": "https://test.api",
            "organization-id": "org-123",
            "environment": "staging",
            "refresh": True,
            "force": False,
        }

        ns = plugin._args_to_namespace(args)

        assert ns.mode == "api"
        assert ns.issue == "12345"
        assert ns.token == "test-token"
        assert ns.api_url == "https://test.api"
        assert ns.organization_id == "org-123"
        assert ns.environment == "staging"
        assert ns.refresh is True
        assert ns.force is False

    def test_args_to_namespace_defaults(self, plugin):
        """Test that defaults are applied correctly."""
        args = {"requirements-file": "/tmp/test.txt"}

        ns = plugin._args_to_namespace(args)

        assert ns.mode == "index"
        assert ns.index_url == "https://libraries.cgr.dev/python/simple"
        assert ns.verbose is False
        assert ns.workers == 10
        assert ns.environment == "prod"
        assert ns.refresh is False
        assert ns.force is False

    def test_args_to_namespace_csv_path(self, plugin):
        """Test CSV path conversion."""
        args = {
            "requirements-file": "/tmp/test.txt",
            "mode": "csv",
            "csv": "/tmp/results.csv",
        }

        ns = plugin._args_to_namespace(args)

        assert ns.csv == Path("/tmp/results.csv")

    def test_args_to_namespace_none_csv(self, plugin):
        """Test that None csv is handled correctly."""
        args = {"requirements-file": "/tmp/test.txt"}

        ns = plugin._args_to_namespace(args)

        assert ns.csv is None


class TestPluginIntegration:
    """Test plugin integration with FORGE core."""

    def test_plugin_conforms_to_protocol(self, plugin):
        """Test that plugin conforms to ToolPlugin protocol."""
        # Check required attributes
        assert hasattr(plugin, "name")
        assert hasattr(plugin, "description")
        assert hasattr(plugin, "version")

        # Check required methods
        assert hasattr(plugin, "get_params")
        assert callable(plugin.get_params)
        assert hasattr(plugin, "run")
        assert callable(plugin.run)

    def test_run_returns_tool_result(self, plugin, ctx):
        """Test that run method returns a ToolResult."""
        # Call with invalid args to get quick failure
        result = plugin.run({"mode": "csv"}, ctx)

        # Should return ToolResult even on failure
        assert hasattr(result, "status")
        assert hasattr(result, "summary")
        assert isinstance(result.status, ResultStatus)
        assert isinstance(result.summary, str)
