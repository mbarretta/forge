"""Tests for Chainguard API client retry logic."""

import pytest
from unittest.mock import Mock, patch, MagicMock
import requests


class TestChainguardAPIRetry:
    """Tests for rate limiting retry logic in ChainguardAPI."""

    @pytest.fixture
    def mock_chainctl(self):
        """Mock chainctl auth token command."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="test-token\n", stderr="")
            yield mock_run

    @pytest.fixture
    def api_client(self, mock_chainctl):
        """Create a ChainguardAPI instance with mocked chainctl."""
        from forge_gauge.integrations.chainguard_api import ChainguardAPI
        return ChainguardAPI()

    def test_successful_request_no_retry(self, api_client):
        """Test that successful requests don't trigger retry logic."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"items": [{"vulnCounts": []}]}
        mock_response.raise_for_status = Mock()

        with patch.object(api_client._session, "get", return_value=mock_response) as mock_get:
            result = api_client.get_vulnerability_counts("python", "latest")

            assert result == {"items": [{"vulnCounts": []}]}
            assert mock_get.call_count == 1

    def test_rate_limit_429_triggers_retry(self, api_client):
        """Test that 429 errors trigger retry with exponential backoff."""
        # First call returns 429, second call succeeds
        error_response = Mock()
        error_response.status_code = 429
        error_response.headers = {}

        success_response = Mock()
        success_response.status_code = 200
        success_response.json.return_value = {"items": [{"vulnCounts": []}]}
        success_response.raise_for_status = Mock()

        http_error = requests.HTTPError(response=error_response)
        error_response.raise_for_status = Mock(side_effect=http_error)

        with patch.object(api_client._session, "get") as mock_get:
            mock_get.side_effect = [error_response, success_response]
            error_response.raise_for_status = Mock(side_effect=http_error)

            with patch("time.sleep") as mock_sleep:
                result = api_client.get_vulnerability_counts("python", "latest")

                assert result == {"items": [{"vulnCounts": []}]}
                assert mock_get.call_count == 2
                mock_sleep.assert_called_once()

    def test_rate_limit_uses_retry_after_header(self, api_client):
        """Test that Retry-After header is respected when present."""
        error_response = Mock()
        error_response.status_code = 429
        error_response.headers = {"Retry-After": "5"}

        success_response = Mock()
        success_response.status_code = 200
        success_response.json.return_value = {"items": []}
        success_response.raise_for_status = Mock()

        http_error = requests.HTTPError(response=error_response)
        error_response.raise_for_status = Mock(side_effect=http_error)

        with patch.object(api_client._session, "get") as mock_get:
            mock_get.side_effect = [error_response, success_response]

            with patch("time.sleep") as mock_sleep:
                result = api_client.get_vulnerability_counts("python", "latest")

                # Should use Retry-After value of 5 seconds
                mock_sleep.assert_called_once_with(5.0)

    def test_rate_limit_exponential_backoff(self, api_client):
        """Test exponential backoff when no Retry-After header."""
        error_response = Mock()
        error_response.status_code = 429
        error_response.headers = {}

        success_response = Mock()
        success_response.status_code = 200
        success_response.json.return_value = {"items": []}
        success_response.raise_for_status = Mock()

        http_error = requests.HTTPError(response=error_response)
        error_response.raise_for_status = Mock(side_effect=http_error)

        with patch.object(api_client._session, "get") as mock_get:
            # Two 429 errors, then success
            mock_get.side_effect = [error_response, error_response, success_response]

            with patch("time.sleep") as mock_sleep:
                result = api_client.get_vulnerability_counts("python", "latest")

                # Should have exponential backoff: 1.0, 2.0 (BASE_RETRY_DELAY * 2^attempt)
                assert mock_sleep.call_count == 2
                calls = [call[0][0] for call in mock_sleep.call_args_list]
                assert calls[0] == 1.0  # 1.0 * 2^0
                assert calls[1] == 2.0  # 1.0 * 2^1

    def test_rate_limit_max_retries_exceeded(self, api_client):
        """Test that max retries returns empty result."""
        error_response = Mock()
        error_response.status_code = 429
        error_response.headers = {}

        http_error = requests.HTTPError(response=error_response)
        error_response.raise_for_status = Mock(side_effect=http_error)

        with patch.object(api_client._session, "get", return_value=error_response):
            with patch("time.sleep"):
                result = api_client.get_vulnerability_counts("python", "latest")

                # Should return empty after MAX_RETRIES (3) + 1 attempts
                assert result == {"items": []}

    def test_403_error_no_retry(self, api_client):
        """Test that 403 errors don't trigger retry (no data available)."""
        error_response = Mock()
        error_response.status_code = 403

        http_error = requests.HTTPError(response=error_response)
        error_response.raise_for_status = Mock(side_effect=http_error)

        with patch.object(api_client._session, "get", return_value=error_response) as mock_get:
            result = api_client.get_vulnerability_counts("python", "latest")

            assert result == {"items": []}
            assert mock_get.call_count == 1  # No retry

    def test_timeout_no_retry(self, api_client):
        """Test that timeouts don't trigger retry."""
        with patch.object(api_client._session, "get") as mock_get:
            mock_get.side_effect = requests.Timeout()

            result = api_client.get_vulnerability_counts("python", "latest")

            assert result == {"items": []}
            assert mock_get.call_count == 1  # No retry

    def test_other_http_error_no_retry(self, api_client):
        """Test that non-429 HTTP errors don't trigger retry."""
        error_response = Mock()
        error_response.status_code = 500

        http_error = requests.HTTPError(response=error_response)
        error_response.raise_for_status = Mock(side_effect=http_error)

        with patch.object(api_client._session, "get", return_value=error_response) as mock_get:
            result = api_client.get_vulnerability_counts("python", "latest")

            assert result == {"items": []}
            assert mock_get.call_count == 1  # No retry


class TestCVERatiosPrefetch:
    """Tests for CVE ratios prefetch worker count."""

    def test_default_workers_is_two(self):
        """Test that default max_workers is 2 to avoid rate limiting."""
        import inspect
        from forge_gauge.utils.cve_ratios import prefetch_cve_ratios_batch

        sig = inspect.signature(prefetch_cve_ratios_batch)
        default_workers = sig.parameters["max_workers"].default
        assert default_workers == 2, "Default workers should be 2 to avoid rate limiting"
