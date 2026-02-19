"""Tests for GaugePlugin subprocess delegation."""

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from forge_core.plugin import ResultStatus

from forge_gauge.plugin import REQUIRED_TOOLS, GaugePlugin


class TestRequiredTools:
    def test_gauge_in_required_tools(self) -> None:
        assert "gauge" in REQUIRED_TOOLS


class TestBuildCmd:
    def test_scan_subcommand(self) -> None:
        plugin = GaugePlugin()
        cmd = plugin._build_cmd("scan", {"command": "scan", "input": "images.csv"})
        assert cmd[0] == "gauge"
        assert cmd[1] == "scan"

    def test_match_subcommand(self) -> None:
        plugin = GaugePlugin()
        cmd = plugin._build_cmd("match", {"command": "match", "input": "images.csv"})
        assert cmd[1] == "match"

    def test_command_key_excluded(self) -> None:
        plugin = GaugePlugin()
        cmd = plugin._build_cmd("scan", {"command": "scan"})
        assert "--command" not in cmd

    def test_string_arg_appended(self) -> None:
        plugin = GaugePlugin()
        cmd = plugin._build_cmd("scan", {"command": "scan", "input": "images.csv"})
        assert "--input" in cmd
        idx = cmd.index("--input")
        assert cmd[idx + 1] == "images.csv"

    def test_hyphenated_flag_from_underscored_key(self) -> None:
        plugin = GaugePlugin()
        cmd = plugin._build_cmd("scan", {"command": "scan", "output_dir": "results"})
        assert "--output-dir" in cmd

    def test_bool_true_flag_included(self) -> None:
        plugin = GaugePlugin()
        cmd = plugin._build_cmd("scan", {"command": "scan", "no_cache": True})
        assert "--no-cache" in cmd

    def test_bool_false_flag_omitted(self) -> None:
        plugin = GaugePlugin()
        cmd = plugin._build_cmd("scan", {"command": "scan", "no_cache": False})
        assert "--no-cache" not in cmd

    def test_none_value_omitted(self) -> None:
        plugin = GaugePlugin()
        cmd = plugin._build_cmd("scan", {"command": "scan", "organization": None})
        assert "--organization" not in cmd

    def test_int_value_converted_to_str(self) -> None:
        plugin = GaugePlugin()
        cmd = plugin._build_cmd("scan", {"command": "scan", "max_workers": 4})
        assert "--max-workers" in cmd
        idx = cmd.index("--max-workers")
        assert cmd[idx + 1] == "4"


class TestRunScan:
    def test_constructs_correct_gauge_cli_args(self, tmp_path: Path) -> None:
        plugin = GaugePlugin()
        ctx = MagicMock()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stderr="")
            plugin._run_scan(
                {"command": "scan", "input": "images.csv", "output_dir": str(tmp_path)},
                ctx,
            )

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "gauge"
        assert cmd[1] == "scan"
        assert "--input" in cmd
        assert "--output-dir" in cmd

    def test_success_returns_success_status(self, tmp_path: Path) -> None:
        plugin = GaugePlugin()
        ctx = MagicMock()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stderr="")
            result = plugin._run_scan(
                {"command": "scan", "input": "images.csv", "output_dir": str(tmp_path)},
                ctx,
            )

        assert result.status == ResultStatus.SUCCESS

    def test_nonzero_exit_returns_failure(self) -> None:
        plugin = GaugePlugin()
        ctx = MagicMock()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1, stderr="scan error")
            result = plugin._run_scan(
                {"command": "scan", "input": "images.csv", "output_dir": "output"},
                ctx,
            )

        assert result.status == ResultStatus.FAILURE

    def test_artifact_collection_from_output_dir(self, tmp_path: Path) -> None:
        plugin = GaugePlugin()
        ctx = MagicMock()
        (tmp_path / "report.html").write_text("<html>report</html>")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stderr="")
            result = plugin._run_scan(
                {"command": "scan", "input": "images.csv", "output_dir": str(tmp_path)},
                ctx,
            )

        assert "report" in result.artifacts

    def test_retry_and_resume_mutually_exclusive(self, tmp_path: Path) -> None:
        checkpoint = tmp_path / "checkpoint.json"
        checkpoint.write_text("{}")
        plugin = GaugePlugin()
        ctx = MagicMock()

        result = plugin._run_scan(
            {"retry_failures": True, "resume": True, "checkpoint_file": str(checkpoint)},
            ctx,
        )
        assert result.status == ResultStatus.FAILURE

    def test_skip_permanent_requires_retry_failures(self) -> None:
        plugin = GaugePlugin()
        ctx = MagicMock()

        result = plugin._run_scan(
            {"retry_failures": False, "skip_permanent_failures": True},
            ctx,
        )
        assert result.status == ResultStatus.FAILURE

    def test_retry_failures_requires_existing_checkpoint(self, tmp_path: Path) -> None:
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


class TestRunMatch:
    def test_constructs_correct_gauge_cli_args(self, tmp_path: Path) -> None:
        plugin = GaugePlugin()
        ctx = MagicMock()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stderr="")
            plugin._run_match(
                {"command": "match", "input": "images.csv", "output_dir": str(tmp_path)},
                ctx,
            )

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "gauge"
        assert cmd[1] == "match"

    def test_success_returns_success_status(self, tmp_path: Path) -> None:
        plugin = GaugePlugin()
        ctx = MagicMock()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stderr="")
            result = plugin._run_match(
                {"command": "match", "input": "images.csv", "output_dir": str(tmp_path)},
                ctx,
            )

        assert result.status == ResultStatus.SUCCESS

    def test_nonzero_exit_returns_failure(self) -> None:
        plugin = GaugePlugin()
        ctx = MagicMock()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1, stderr="match error")
            result = plugin._run_match(
                {"command": "match", "input": "images.csv", "output_dir": "output"},
                ctx,
            )

        assert result.status == ResultStatus.FAILURE

    def test_artifact_collected_when_match_log_present(self, tmp_path: Path) -> None:
        plugin = GaugePlugin()
        ctx = MagicMock()
        (tmp_path / "matched-log.yaml").write_text("matched: []\nunmatched: []")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stderr="")
            result = plugin._run_match(
                {"command": "match", "input": "images.csv", "output_dir": str(tmp_path)},
                ctx,
            )

        assert result.status == ResultStatus.SUCCESS
        assert "match_log" in result.artifacts

    def test_partial_status_when_unmatched_images(self, tmp_path: Path) -> None:
        plugin = GaugePlugin()
        ctx = MagicMock()
        (tmp_path / "matched-log.yaml").write_text(
            "matched:\n  - image: a\nunmatched:\n  - image: b\n"
        )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stderr="")
            result = plugin._run_match(
                {"command": "match", "input": "images.csv", "output_dir": str(tmp_path)},
                ctx,
            )

        assert result.status == ResultStatus.PARTIAL
        assert result.data["matched"] == 1
        assert result.data["unmatched"] == 1
