"""Tests for ProvenancePlugin subprocess delegation."""

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from forge_core.plugin import ResultStatus

from forge_provenance.plugin import REQUIRED_TOOLS, ProvenancePlugin


class TestRequiredTools:
    def test_verify_provenance_in_required_tools(self) -> None:
        assert "verify-provenance" in REQUIRED_TOOLS

    def test_chainctl_in_required_tools(self) -> None:
        assert "chainctl" in REQUIRED_TOOLS


class TestGetParams:
    def test_customer_org_is_required(self) -> None:
        plugin = ProvenancePlugin()
        params = plugin.get_params()
        customer_org = next(p for p in params if p.name == "customer-org")
        assert customer_org.required is True

    def test_full_is_bool(self) -> None:
        plugin = ProvenancePlugin()
        params = plugin.get_params()
        full = next(p for p in params if p.name == "full")
        assert full.type == "bool"

    def test_verify_signatures_is_bool(self) -> None:
        plugin = ProvenancePlugin()
        params = plugin.get_params()
        vs = next(p for p in params if p.name == "verify-signatures")
        assert vs.type == "bool"

    def test_limit_default_is_zero(self) -> None:
        plugin = ProvenancePlugin()
        params = plugin.get_params()
        limit = next(p for p in params if p.name == "limit")
        assert limit.default == 0


class TestRun:
    def test_constructs_basic_cli_args(self) -> None:
        plugin = ProvenancePlugin()
        ctx = MagicMock()

        with patch("forge_provenance.plugin.assert_dependencies"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stderr="")
            plugin.run({"customer_org": "my-org", "limit": 0}, ctx)

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "verify-provenance"
        assert "--customer-org" in cmd
        assert "my-org" in cmd

    def test_full_flag_appended_when_true(self) -> None:
        plugin = ProvenancePlugin()
        ctx = MagicMock()

        with patch("forge_provenance.plugin.assert_dependencies"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stderr="")
            plugin.run({"customer_org": "my-org", "full": True, "limit": 0}, ctx)

        cmd = mock_run.call_args[0][0]
        assert "--full" in cmd

    def test_full_flag_omitted_when_false(self) -> None:
        plugin = ProvenancePlugin()
        ctx = MagicMock()

        with patch("forge_provenance.plugin.assert_dependencies"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stderr="")
            plugin.run({"customer_org": "my-org", "full": False, "limit": 0}, ctx)

        cmd = mock_run.call_args[0][0]
        assert "--full" not in cmd

    def test_verify_signatures_flag(self) -> None:
        plugin = ProvenancePlugin()
        ctx = MagicMock()

        with patch("forge_provenance.plugin.assert_dependencies"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stderr="")
            plugin.run(
                {"customer_org": "my-org", "verify_signatures": True, "limit": 0}, ctx
            )

        cmd = mock_run.call_args[0][0]
        assert "--verify-signatures" in cmd

    def test_limit_flag_added_when_nonzero(self) -> None:
        plugin = ProvenancePlugin()
        ctx = MagicMock()

        with patch("forge_provenance.plugin.assert_dependencies"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stderr="")
            plugin.run({"customer_org": "my-org", "limit": 5}, ctx)

        cmd = mock_run.call_args[0][0]
        assert "--limit" in cmd
        assert "5" in cmd

    def test_limit_flag_omitted_when_zero(self) -> None:
        plugin = ProvenancePlugin()
        ctx = MagicMock()

        with patch("forge_provenance.plugin.assert_dependencies"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stderr="")
            plugin.run({"customer_org": "my-org", "limit": 0}, ctx)

        cmd = mock_run.call_args[0][0]
        assert "--limit" not in cmd

    def test_success_returns_success_status(self) -> None:
        plugin = ProvenancePlugin()
        ctx = MagicMock()

        with patch("forge_provenance.plugin.assert_dependencies"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stderr="")
            result = plugin.run({"customer_org": "my-org", "limit": 0}, ctx)

        assert result.status == ResultStatus.SUCCESS

    def test_nonzero_exit_returns_failure(self) -> None:
        plugin = ProvenancePlugin()
        ctx = MagicMock()

        with patch("forge_provenance.plugin.assert_dependencies"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1, stderr="auth error")
            result = plugin.run({"customer_org": "my-org", "limit": 0}, ctx)

        assert result.status == ResultStatus.FAILURE

    def test_csv_artifact_collected(self, tmp_path: Path) -> None:
        plugin = ProvenancePlugin()
        ctx = MagicMock()
        csv_file = Path("my-org.csv")

        try:
            csv_file.write_text("image,status\ntest,VERIFIED\n")
            with patch("forge_provenance.plugin.assert_dependencies"), \
                 patch("subprocess.run") as mock_run:
                mock_run.return_value = Mock(returncode=0, stderr="")
                result = plugin.run({"customer_org": "my-org", "limit": 0}, ctx)

            assert "report" in result.artifacts
        finally:
            if csv_file.exists():
                csv_file.unlink()

    def test_no_artifact_when_csv_missing(self) -> None:
        plugin = ProvenancePlugin()
        ctx = MagicMock()

        # Ensure the CSV doesn't exist
        csv_file = Path("nonexistent-org.csv")
        if csv_file.exists():
            csv_file.unlink()

        with patch("forge_provenance.plugin.assert_dependencies"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stderr="")
            result = plugin.run({"customer_org": "nonexistent-org", "limit": 0}, ctx)

        assert result.status == ResultStatus.SUCCESS
        assert "report" not in result.artifacts
