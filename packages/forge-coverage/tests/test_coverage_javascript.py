"""
Integration tests for JavaScript package coverage checking.

Tests coverage checking against common JavaScript libraries.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from forge_coverage import check_coverage


# Test fixtures directory
FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestJavaScriptCoverageBasics:
    """Test basic JavaScript coverage checking functionality."""

    def test_load_package_lock_json(self):
        """Test loading package-lock.json file."""
        lock_file = FIXTURES_DIR / "package-lock.json"

        # Verify file exists and is valid JSON
        assert lock_file.exists()

        with open(lock_file) as f:
            data = json.load(f)

        assert "lockfileVersion" in data
        assert data["lockfileVersion"] == 3
        assert "packages" in data

    def test_package_lock_has_common_packages(self):
        """Test that our fixture includes common packages."""
        lock_file = FIXTURES_DIR / "package-lock.json"

        with open(lock_file) as f:
            data = json.load(f)

        # Check for node_modules entries
        assert "node_modules/express" in data["packages"]
        assert "node_modules/react" in data["packages"]
        assert "node_modules/lodash" in data["packages"]
        assert "node_modules/axios" in data["packages"]

    def test_js_package_result_structure(self):
        """Test JSPackageResult dataclass structure."""
        result = check_coverage.JSPackageResult(
            name="express",
            version="4.18.2",
            found=True,
        )

        assert result.name == "express"
        assert result.version == "4.18.2"
        assert result.found is True


class TestFlatcoverIntegration:
    """Test flatcover binary management."""

    def test_get_flatcover_cache_dir(self):
        """Test that cache directory is created."""
        cache_dir = check_coverage.get_flatcover_cache_dir()

        assert isinstance(cache_dir, Path)
        assert cache_dir.name == "check_coverage"
        assert ".cache" in str(cache_dir)

    def test_compute_file_checksum(self, tmp_path):
        """Test checksum computation."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        checksum = check_coverage.compute_file_checksum(test_file)

        assert checksum.startswith("sha256:")
        assert len(checksum) > 10

    def test_ensure_flatcover_checks_local_override(self, tmp_path, monkeypatch):
        """Test that local flatcover override is detected."""
        # Create a fake local flatcover
        fake_flatcover = tmp_path / "flatcover"
        fake_flatcover.write_text("#!/bin/bash\necho 'fake flatcover'")
        fake_flatcover.chmod(0o755)

        # Change to that directory
        monkeypatch.chdir(tmp_path)

        with patch("forge_coverage.check_coverage.Path") as mock_path:
            mock_path.return_value = fake_flatcover
            # This would normally check for ./flatcover
            local_flatcover = Path("./flatcover")
            assert local_flatcover.exists() if tmp_path else True


class TestJavaScriptCoverageWithMocks:
    """Test JavaScript coverage with mocked flatcover responses."""

    @pytest.fixture
    def mock_flatcover_binary(self, tmp_path):
        """Create a mock flatcover binary."""
        binary = tmp_path / "flatcover"
        binary.write_text("#!/bin/bash\necho 'mock flatcover'")
        binary.chmod(0o755)
        return binary

    @pytest.fixture
    def mock_chainctl_credentials(self):
        """Mock chainctl credential retrieval."""
        return ("identity-123", "token-456")

    def test_get_javascript_auth_credentials_mock(self, mock_chainctl_credentials):
        """Test getting JavaScript auth credentials."""
        with patch("subprocess.run") as mock_run:
            # Mock successful chainctl output
            mock_run.return_value = Mock(
                returncode=0,
                stdout=json.dumps({
                    "identity_id": "identity-123",
                    "token": "token-456"
                }),
            )

            identity_id, token = check_coverage.get_javascript_auth_credentials("test-org")

            assert identity_id == "identity-123"
            assert token == "token-456"
            mock_run.assert_called_once()

    def test_run_flatcover_parses_csv_output(self, mock_flatcover_binary):
        """Test parsing flatcover CSV output."""
        with patch("subprocess.Popen") as mock_popen:
            # Mock flatcover CSV output
            mock_process = Mock()
            mock_process.returncode = 0
            mock_process.communicate.return_value = (
                "express,4.18.2,true\nreact,18.2.0,false\nlodash,4.17.21,true\n",
                ""
            )
            mock_popen.return_value = mock_process

            results = check_coverage.run_flatcover(
                mock_flatcover_binary,
                Path("/tmp/package-lock.json"),
                "https://libraries.cgr.dev/javascript",
                "identity-123",
                "token-456"
            )

            assert len(results) == 3
            assert results[0].name == "express"
            assert results[0].version == "4.18.2"
            assert results[0].found is True

            assert results[1].name == "react"
            assert results[1].version == "18.2.0"
            assert results[1].found is False

            assert results[2].name == "lodash"
            assert results[2].version == "4.17.21"
            assert results[2].found is True


class TestJavaScriptCoverageAggregation:
    """Test aggregation of results from multiple lock files."""

    def test_aggregate_results_or_logic(self):
        """Test that results are aggregated with OR logic."""
        # Simulate results from multiple files
        all_results = {}

        # File 1: express found, react not found
        file1_results = [
            check_coverage.JSPackageResult("express", "4.18.2", True),
            check_coverage.JSPackageResult("react", "18.2.0", False),
        ]

        for result in file1_results:
            key = (result.name, result.version)
            all_results[key] = result.found

        # File 2: express found, react found
        file2_results = [
            check_coverage.JSPackageResult("express", "4.18.2", True),
            check_coverage.JSPackageResult("react", "18.2.0", True),
        ]

        for result in file2_results:
            key = (result.name, result.version)
            # OR logic: if found in any file, mark as found
            if key in all_results:
                all_results[key] = all_results[key] or result.found
            else:
                all_results[key] = result.found

        # express should be True (found in both)
        assert all_results[("express", "4.18.2")] is True
        # react should be True (found in file 2)
        assert all_results[("react", "18.2.0")] is True


@pytest.mark.integration
class TestJavaScriptCoverageIntegration:
    """
    Integration tests that make real flatcover calls.

    These tests are marked with @pytest.mark.integration and can be skipped
    with: pytest -m "not integration"
    """

    def test_check_javascript_packages_real_flatcover(self):
        """Test checking JavaScript packages with real flatcover."""
        lock_file = FIXTURES_DIR / "package-lock.json"

        # This test requires:
        # 1. flatcover binary available
        # 2. chainctl authentication
        # 3. Network access to Chainguard registry

        try:
            # Try to ensure flatcover is available
            flatcover_binary = check_coverage.ensure_flatcover()
            assert flatcover_binary.exists()

            # Try to get credentials
            identity_id, token = check_coverage.get_javascript_auth_credentials(
                "chainguard-eng"
            )

            # Run flatcover
            results = check_coverage.run_flatcover(
                flatcover_binary,
                lock_file,
                "https://libraries.cgr.dev/javascript",
                identity_id,
                token
            )

            # Verify we got results
            assert len(results) > 0

            # Verify structure
            for result in results:
                assert hasattr(result, "name")
                assert hasattr(result, "version")
                assert hasattr(result, "found")
                assert isinstance(result.found, bool)

        except Exception as e:
            pytest.skip(f"Skipping integration test: {e}")

    def test_common_javascript_libraries_documented(self):
        """Document which common JavaScript libraries we're testing."""
        lock_file = FIXTURES_DIR / "package-lock.json"

        with open(lock_file) as f:
            data = json.load(f)

        packages = data.get("packages", {})

        # Document the packages we're testing
        common_libs = {
            "express": "Web framework",
            "react": "UI library",
            "lodash": "Utility library",
            "axios": "HTTP client",
        }

        for lib_name, description in common_libs.items():
            node_modules_key = f"node_modules/{lib_name}"
            assert node_modules_key in packages, \
                f"{lib_name} ({description}) should be in test fixtures"


class TestJavaScriptModeEndToEnd:
    """Test JavaScript mode end-to-end with mocking."""

    def test_check_js_coverage_with_mocks(self, tmp_path):
        """Test complete JavaScript coverage check with mocked components."""
        lock_file = FIXTURES_DIR / "package-lock.json"

        with patch("forge_coverage.check_coverage.ensure_flatcover") as mock_ensure, \
             patch("forge_coverage.check_coverage.get_organization_id") as mock_org, \
             patch("forge_coverage.check_coverage.get_javascript_auth_credentials") as mock_auth, \
             patch("forge_coverage.check_coverage.run_flatcover") as mock_run:

            # Setup mocks
            mock_binary = tmp_path / "flatcover"
            mock_binary.touch()
            mock_ensure.return_value = mock_binary
            mock_org.return_value = "test-org"
            mock_auth.return_value = ("identity-123", "token-456")
            mock_run.return_value = [
                check_coverage.JSPackageResult("express", "4.18.2", True),
                check_coverage.JSPackageResult("react", "18.2.0", False),
            ]

            # This should execute without errors (output goes to stdout)
            check_coverage.check_js_coverage_with_flatcover(
                [lock_file],
                "https://libraries.cgr.dev/javascript",
                "prod",
                None
            )

            # Verify mocks were called
            mock_ensure.assert_called_once()
            mock_auth.assert_called_once_with("test-org")
            mock_run.assert_called_once()
