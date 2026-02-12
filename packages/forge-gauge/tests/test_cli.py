"""Tests for CLI argument parsing and output type handling."""

import argparse
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from forge_gauge.common import OUTPUT_CONFIGS
from forge_gauge.plugins.gauge_core.scan_command import configure_scan_parser
from forge_gauge.core.orchestrator import GaugeOrchestrator


def parse_args(args: list[str]) -> argparse.Namespace:
    """Helper function to parse scan command arguments for testing."""
    parser = argparse.ArgumentParser()
    configure_scan_parser(parser)
    return parser.parse_args(args)


class TestOutputTypeParsing:
    """Tests for parse_output_types method on GaugeOrchestrator."""

    def setup_method(self):
        """Set up a dummy orchestrator for testing."""
        # Create a mock args object
        class MockArgs:
            def __init__(self):
                pass
        self.args = MockArgs()
        self.orchestrator = GaugeOrchestrator(self.args)

    def test_default_none_returns_default_types(self):
        """Test that None (default) returns vuln_summary and cost_analysis."""
        result = self.orchestrator.parse_output_types(None)
        assert result == {'cost_analysis', 'vuln_summary'}

    def test_single_type(self):
        """Test parsing a single output type."""
        result = self.orchestrator.parse_output_types('pricing')
        assert result == {'pricing'}

    def test_comma_delimited_two_types(self):
        """Test parsing comma-delimited list of two types."""
        result = self.orchestrator.parse_output_types('cost_analysis,pricing')
        assert result == {'cost_analysis', 'pricing'}

    def test_comma_delimited_all_three(self):
        """Test parsing comma-delimited list of all three types."""
        result = self.orchestrator.parse_output_types('cost_analysis,vuln_summary,pricing')
        assert result == {'cost_analysis', 'vuln_summary', 'pricing'}

    def test_with_spaces_strips_whitespace(self):
        """Test that spaces around commas are handled correctly."""
        result = self.orchestrator.parse_output_types('cost_analysis, pricing')
        assert result == {'cost_analysis', 'pricing'}

    def test_invalid_type_raises_value_error(self):
        """Test that invalid output type raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            self.orchestrator.parse_output_types('invalid_type')
        assert 'Invalid output type(s): invalid_type' in str(exc_info.value)
        assert 'Valid types:' in str(exc_info.value)

    def test_mixed_valid_and_invalid_raises_value_error(self):
        """Test that mix of valid and invalid types raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            self.orchestrator.parse_output_types('pricing,invalid,cost_analysis')
        assert 'Invalid output type(s): invalid' in str(exc_info.value)

    def test_duplicate_types_deduped(self):
        """Test that duplicate types are deduplicated."""
        result = self.orchestrator.parse_output_types('pricing,pricing,cost_analysis')
        assert result == {'pricing', 'cost_analysis'}

    def test_both_alias_expands_to_vuln_summary_and_cost_analysis(self):
        """Test that 'both' is an alias for vuln_summary and cost_analysis."""
        result = self.orchestrator.parse_output_types('both')
        assert result == {'vuln_summary', 'cost_analysis'}

    def test_both_with_pricing_includes_all_three(self):
        """Test that 'both,pricing' includes all three output types."""
        result = self.orchestrator.parse_output_types('both,pricing')
        assert result == {'vuln_summary', 'cost_analysis', 'pricing'}


class TestCLIArguments:
    """Tests for parse_args function."""

    def test_output_default_is_none(self):
        """Test that --output defaults to None (all types)."""
        args = parse_args(['-i', 'test.csv'])
        assert args.output is None

    def test_output_single_type(self):
        """Test --output with single type."""
        args = parse_args(['-i', 'test.csv', '--output', 'pricing'])
        assert args.output == 'pricing'

    def test_output_comma_delimited(self):
        """Test --output with comma-delimited types."""
        args = parse_args(['-i', 'test.csv', '--output', 'cost_analysis,pricing'])
        assert args.output == 'cost_analysis,pricing'

    def test_pricing_policy_default(self):
        """Test that --pricing-policy has correct default."""
        args = parse_args(['-i', 'test.csv'])
        assert args.pricing_policy == Path('pricing-policy.yaml')

    def test_pricing_policy_custom(self):
        """Test --pricing-policy with custom path."""
        args = parse_args(['-i', 'test.csv', '--pricing-policy', 'custom-policy.yaml'])
        assert args.pricing_policy == Path('custom-policy.yaml')

    def test_short_option_o_works(self):
        """Test that -o short option works for --output."""
        args = parse_args(['-i', 'test.csv', '-o', 'pricing'])
        assert args.output == 'pricing'

    def test_output_both_alias(self):
        """Test --output with 'both' alias."""
        args = parse_args(['-i', 'test.csv', '--output', 'both'])
        assert args.output == 'both'

    def test_with_all_flag_sets_individual_flags(self):
        """Test that --with-all flag is parsed correctly."""
        args = parse_args(['-i', 'test.csv', '--with-all'])
        assert args.with_all is True

    def test_without_with_all_flag_defaults_false(self):
        """Test that --with-all defaults to False."""
        args = parse_args(['-i', 'test.csv'])
        assert args.with_all is False

    def test_individual_with_flags_default_false(self):
        """Test that individual --with-* flags default to False."""
        args = parse_args(['-i', 'test.csv'])
        assert args.with_chps is False
        assert args.with_fips is False
        assert args.with_kevs is False


class TestCLIIntegration:
    """Integration tests for CLI argument parsing with output type parsing."""

    def setup_method(self):
        """Set up a dummy orchestrator for testing."""
        # Create a mock args object
        class MockArgs:
            def __init__(self):
                pass
        self.args = MockArgs()
        self.orchestrator = GaugeOrchestrator(self.args)

    def test_default_workflow(self):
        """Test default workflow: no --output flag generates vuln_summary and cost_analysis."""
        args = parse_args(['-i', 'test.csv'])
        self.orchestrator.args = args
        output_types = self.orchestrator.parse_output_types(args.output)
        assert output_types == {'cost_analysis', 'vuln_summary'}

    def test_single_pricing_workflow(self):
        """Test workflow for generating only pricing quote."""
        args = parse_args(['-i', 'test.csv', '--output', 'pricing'])
        self.orchestrator.args = args
        output_types = self.orchestrator.parse_output_types(args.output)
        assert output_types == {'pricing'}

    def test_dual_output_workflow(self):
        """Test workflow for generating two output types."""
        args = parse_args(['-i', 'test.csv', '--output', 'cost_analysis,pricing'])
        self.orchestrator.args = args
        output_types = self.orchestrator.parse_output_types(args.output)
        assert output_types == {'cost_analysis', 'pricing'}

    def test_invalid_output_raises_on_parsing(self):
        """Test that invalid output type is caught during parsing phase."""
        args = parse_args(['-i', 'test.csv', '--output', 'invalid'])
        self.orchestrator.args = args
        with pytest.raises(ValueError) as exc_info:
            self.orchestrator.parse_output_types(args.output)
        assert 'Invalid output type(s): invalid' in str(exc_info.value)

    def test_both_alias_workflow(self):
        """Test workflow for generating both vuln_summary and cost_analysis using 'both' alias."""
        args = parse_args(['-i', 'test.csv', '--output', 'both'])
        self.orchestrator.args = args
        output_types = self.orchestrator.parse_output_types(args.output)
        assert output_types == {'vuln_summary', 'cost_analysis'}


class TestVersionFlag:
    """Tests for --version and -V flags."""

    def test_version_flag_short(self):
        """Test -V flag prints version and exits."""
        from cli import main_dispatch
        from forge_gauge.constants import __version__

        with patch.object(sys, 'argv', ['gauge', '-V']):
            captured_output = StringIO()
            with patch('sys.stdout', captured_output):
                main_dispatch()
            output = captured_output.getvalue()
            assert f"gauge {__version__}" in output

    def test_version_flag_long(self):
        """Test --version flag prints version and exits."""
        from cli import main_dispatch
        from forge_gauge.constants import __version__

        with patch.object(sys, 'argv', ['gauge', '--version']):
            captured_output = StringIO()
            with patch('sys.stdout', captured_output):
                main_dispatch()
            output = captured_output.getvalue()
            assert f"gauge {__version__}" in output


class TestOutputConfigsConsistency:
    """Tests to ensure OUTPUT_CONFIGS keys match what _generate_reports returns.

    This prevents regressions like pricing_text vs pricing_txt mismatches.
    """

    # Keys that _generate_reports can return (must stay in sync with orchestrator.py)
    KNOWN_OUTPUT_FILE_KEYS = {
        "vuln_summary",
        "cost_analysis",
        "pricing_html",
        "pricing_txt",
    }

    def _build_output_names(self) -> dict[str, str]:
        """Build output_names dict the same way the orchestrator does."""
        output_names = {}
        for output_type, config in OUTPUT_CONFIGS.items():
            output_names[output_type] = config["description"]
            if "formats" in config:
                for format_key, format_config in config["formats"].items():
                    output_names[f"{output_type}_{format_key}"] = format_config["description"]
        return output_names

    def test_all_output_file_keys_have_descriptions(self):
        """Verify all keys that _generate_reports returns have descriptions in OUTPUT_CONFIGS."""
        output_names = self._build_output_names()

        missing_keys = self.KNOWN_OUTPUT_FILE_KEYS - set(output_names.keys())
        assert not missing_keys, (
            f"OUTPUT_CONFIGS is missing descriptions for output file keys: {missing_keys}. "
            f"Either add these to OUTPUT_CONFIGS or fix _generate_reports to use correct keys."
        )

    def test_pricing_format_keys_are_correct(self):
        """Verify pricing format keys match expected values (prevents pricing_text vs pricing_txt bugs)."""
        assert "pricing" in OUTPUT_CONFIGS, "pricing output type missing from OUTPUT_CONFIGS"
        pricing_config = OUTPUT_CONFIGS["pricing"]
        assert "formats" in pricing_config, "pricing config missing 'formats' key"

        format_keys = set(pricing_config["formats"].keys())
        expected_format_keys = {"html", "txt"}
        assert format_keys == expected_format_keys, (
            f"Pricing format keys mismatch: got {format_keys}, expected {expected_format_keys}"
        )

    def test_output_names_has_required_structure(self):
        """Verify OUTPUT_CONFIGS produces all expected output_names keys."""
        output_names = self._build_output_names()

        # Base output types
        assert "vuln_summary" in output_names
        assert "cost_analysis" in output_names
        assert "pricing" in output_names

        # Multi-format output types should have format-specific keys
        assert "pricing_html" in output_names
        assert "pricing_txt" in output_names

    def test_no_text_vs_txt_confusion(self):
        """Explicitly test that we use 'txt' not 'text' for text format keys."""
        output_names = self._build_output_names()

        # These should NOT exist (common typo)
        assert "pricing_text" not in output_names, (
            "Found 'pricing_text' in output_names - should be 'pricing_txt'"
        )
