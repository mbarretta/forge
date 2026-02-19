"""Tests for --retry-failures validation in GaugePlugin._run_scan()."""

from pathlib import Path
from unittest.mock import MagicMock

from forge_core.plugin import ResultStatus

from forge_gauge.plugin import GaugePlugin


class TestCLIValidation:
    """Test argument validation for --retry-failures in GaugePlugin._run_scan()."""

    def test_retry_and_resume_mutually_exclusive(self, tmp_path: Path) -> None:
        """--retry-failures and --resume are mutually exclusive."""
        checkpoint = tmp_path / "checkpoint.json"
        checkpoint.write_text('{"version": "2.0", "results": []}')

        plugin = GaugePlugin()
        ctx = MagicMock()
        result = plugin._run_scan(
            {
                "retry_failures": True,
                "resume": True,
                "checkpoint_file": str(checkpoint),
            },
            ctx,
        )
        assert result.status == ResultStatus.FAILURE

    def test_skip_permanent_requires_retry_failures(self) -> None:
        """--skip-permanent-failures requires --retry-failures."""
        plugin = GaugePlugin()
        ctx = MagicMock()
        result = plugin._run_scan(
            {"retry_failures": False, "skip_permanent_failures": True},
            ctx,
        )
        assert result.status == ResultStatus.FAILURE

    def test_retry_failures_requires_checkpoint(self, tmp_path: Path) -> None:
        """--retry-failures requires checkpoint file to exist."""
        plugin = GaugePlugin()
        ctx = MagicMock()
        result = plugin._run_scan(
            {
                "retry_failures": True,
                "resume": False,
                "checkpoint_file": str(tmp_path / "nonexistent.json"),
            },
            ctx,
        )
        assert result.status == ResultStatus.FAILURE
