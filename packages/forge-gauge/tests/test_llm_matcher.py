"""
Tests for LLM-powered image matching functionality.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from forge_gauge.utils.llm_matcher import LLMMatcher, LLMMatchResult


class TestLLMMatcher:
    """Test LLM-powered image matching."""

    @pytest.fixture
    def mock_anthropic_client(self):
        """Mock Anthropic API client."""
        mock_client = Mock()
        mock_message = Mock()
        mock_content = Mock()
        mock_content.text = json.dumps({
            "chainguard_image": "cgr.dev/chainguard-private/redis:latest",
            "confidence": 0.85,
            "reasoning": "Redis is a popular in-memory data store with a direct Chainguard equivalent"
        })
        mock_message.content = [mock_content]
        mock_client.messages.create.return_value = mock_message
        return mock_client

    @pytest.fixture
    def mock_catalog(self):
        """Mock Chainguard catalog for testing."""
        return [
            "redis", "nginx", "python", "node", "postgres", "mysql",
            "chainguard-base", "go", "java", "alpine-base", "wolfi-base",
            "prometheus-postgres-exporter", "kyverno-background-controller",
        ]

    @pytest.fixture
    def llm_matcher(self, tmp_path, mock_anthropic_client, mock_catalog):
        """Create LLMMatcher with mocked API client and catalog."""
        with patch('utils.llm_matcher.anthropic.Anthropic', return_value=mock_anthropic_client):
            with patch.object(LLMMatcher, '_load_full_catalog', return_value=mock_catalog):
                matcher = LLMMatcher(
                    api_key="test-key",
                    model="claude-sonnet-4-5",
                    cache_dir=tmp_path,
                    confidence_threshold=0.7,
                )
        return matcher

    def test_llm_match_success(self, llm_matcher, mock_anthropic_client):
        """Test successful LLM matching."""
        result = llm_matcher.match("docker.io/library/redis:7.0")

        assert result.chainguard_image == "cgr.dev/chainguard-private/redis:latest"
        assert result.confidence == 0.85
        assert "Redis" in result.reasoning
        assert result.cached is False
        assert result.latency_ms > 0

    def test_llm_match_caching(self, llm_matcher, mock_anthropic_client):
        """Test that LLM results are cached."""
        # First call - not cached
        result1 = llm_matcher.match("docker.io/library/redis:7.0")
        assert result1.cached is False
        assert mock_anthropic_client.messages.create.call_count == 1

        # Second call - should be cached
        result2 = llm_matcher.match("docker.io/library/redis:7.0")
        assert result2.cached is True
        assert result2.chainguard_image == result1.chainguard_image
        assert result2.confidence == result1.confidence
        # API should not be called again
        assert mock_anthropic_client.messages.create.call_count == 1

    def test_llm_match_no_match(self, tmp_path, mock_catalog):
        """Test LLM matching when no match is found."""
        mock_client = Mock()
        mock_message = Mock()
        mock_content = Mock()
        mock_content.text = json.dumps({
            "chainguard_image": None,
            "confidence": 0.0,
            "reasoning": "Could not find a suitable Chainguard equivalent for this custom internal image"
        })
        mock_message.content = [mock_content]
        mock_client.messages.create.return_value = mock_message

        with patch('utils.llm_matcher.anthropic.Anthropic', return_value=mock_client):
            with patch.object(LLMMatcher, '_load_full_catalog', return_value=mock_catalog):
                matcher = LLMMatcher(
                    api_key="test-key",
                    cache_dir=tmp_path,
                )

                result = matcher.match("internal.registry.com/custom-app:v1.0")

                assert result.chainguard_image is None
                assert result.confidence == 0.0
                assert "Could not find" in result.reasoning

    def test_llm_match_below_threshold(self, tmp_path, mock_catalog):
        """Test LLM matching when confidence is below threshold."""
        mock_client = Mock()
        mock_message = Mock()
        mock_content = Mock()
        mock_content.text = json.dumps({
            "chainguard_image": "cgr.dev/chainguard-private/nginx:latest",
            "confidence": 0.6,  # Below default threshold of 0.7
            "reasoning": "This might be nginx but not certain"
        })
        mock_message.content = [mock_content]
        mock_client.messages.create.return_value = mock_message

        with patch('utils.llm_matcher.anthropic.Anthropic', return_value=mock_client):
            with patch.object(LLMMatcher, '_load_full_catalog', return_value=mock_catalog):
                matcher = LLMMatcher(
                    api_key="test-key",
                    cache_dir=tmp_path,
                    confidence_threshold=0.7,
                )

                result = matcher.match("some-ambiguous-image:latest")

                # Result should be returned but with low confidence
                assert result.chainguard_image == "cgr.dev/chainguard-private/nginx:latest"
                assert result.confidence == 0.6

    def test_llm_match_api_error(self, tmp_path, mock_catalog):
        """Test LLM matching when API call fails."""
        mock_client = Mock()
        mock_client.messages.create.side_effect = Exception("API error")

        with patch('utils.llm_matcher.anthropic.Anthropic', return_value=mock_client):
            with patch.object(LLMMatcher, '_load_full_catalog', return_value=mock_catalog):
                matcher = LLMMatcher(
                    api_key="test-key",
                    cache_dir=tmp_path,
                )

                result = matcher.match("redis:latest")

                assert result.chainguard_image is None
                assert result.confidence == 0.0
                # With 3-tier matching, API errors in tier 1 cause fallback to tiers 2 & 3
                # Final result may have "Error" from API or "No match" from final tier
                assert "Error" in result.reasoning or "No match" in result.reasoning

    def test_llm_match_json_parse_error(self, tmp_path, mock_catalog):
        """Test LLM matching when response is not valid JSON."""
        mock_client = Mock()
        mock_message = Mock()
        mock_content = Mock()
        mock_content.text = "Not valid JSON"
        mock_message.content = [mock_content]
        mock_client.messages.create.return_value = mock_message

        with patch('utils.llm_matcher.anthropic.Anthropic', return_value=mock_client):
            with patch.object(LLMMatcher, '_load_full_catalog', return_value=mock_catalog):
                matcher = LLMMatcher(
                    api_key="test-key",
                    cache_dir=tmp_path,
                )

                result = matcher.match("redis:latest")

                assert result.chainguard_image is None
                assert result.confidence == 0.0
                assert "JSON" in result.reasoning or "parse" in result.reasoning

    def test_llm_match_no_api_key(self, tmp_path):
        """Test LLM matching when no API key is provided."""
        import os
        # Temporarily remove ANTHROPIC_API_KEY if it exists
        old_key = os.environ.pop('ANTHROPIC_API_KEY', None)
        try:
            matcher = LLMMatcher(
                api_key=None,
                cache_dir=tmp_path,
            )

            result = matcher.match("redis:latest")

            assert result.chainguard_image is None
            assert result.confidence == 0.0
            assert "disabled" in result.reasoning
        finally:
            # Restore the old key if it existed
            if old_key:
                os.environ['ANTHROPIC_API_KEY'] = old_key

    def test_llm_match_os_image_rule(self, llm_matcher):
        """Test that OS images are suggested to map to chainguard-base."""
        # The prompt should include the OS images → chainguard-base rule
        prompt = llm_matcher._build_catalog_prompt("ubuntu:22.04")

        assert "chainguard-base" in prompt.lower()
        assert "debian" in prompt.lower()
        assert "ubuntu" in prompt.lower()
        assert "rhel" in prompt.lower()

    def test_llm_match_prompt_building(self, llm_matcher):
        """Test prompt building includes all necessary guidelines."""
        prompt = llm_matcher._build_catalog_prompt("ghcr.io/kyverno/background-controller:v1.10.3")

        # Check for key prompt elements
        assert "kyverno/background-controller" in prompt
        assert "FIPS" in prompt
        assert "bitnami" in prompt.lower()
        assert "chainguard-private" in prompt
        assert "confidence" in prompt.lower()
        assert "JSON" in prompt

    def test_llm_match_strips_markdown_code_blocks(self, tmp_path, mock_catalog):
        """Test that markdown code blocks are stripped from responses."""
        mock_client = Mock()
        mock_message = Mock()
        mock_content = Mock()
        # Response with markdown code block
        mock_content.text = """```json
{
  "chainguard_image": "cgr.dev/chainguard-private/python:latest",
  "confidence": 0.9,
  "reasoning": "Direct Python match"
}
```"""
        mock_message.content = [mock_content]
        mock_client.messages.create.return_value = mock_message

        with patch('utils.llm_matcher.anthropic.Anthropic', return_value=mock_client):
            with patch.object(LLMMatcher, '_load_full_catalog', return_value=mock_catalog):
                matcher = LLMMatcher(
                    api_key="test-key",
                    cache_dir=tmp_path,
                )

                result = matcher.match("python:3.12")

                assert result.chainguard_image == "cgr.dev/chainguard-private/python:latest"
                assert result.confidence == 0.9

    def test_llm_match_telemetry_logging(self, llm_matcher, tmp_path):
        """Test that telemetry is logged correctly."""
        llm_matcher.match("redis:latest")

        # Check telemetry file was created
        telemetry_file = tmp_path / "llm_telemetry.jsonl"
        assert telemetry_file.exists()

        # Read and verify telemetry data
        with open(telemetry_file, 'r') as f:
            telemetry_line = f.readline().strip()

        telemetry = json.loads(telemetry_line)
        assert "timestamp" in telemetry
        assert telemetry["image_name"] == "redis:latest"
        assert telemetry["model"] == "claude-sonnet-4-5"
        assert "confidence" in telemetry
        assert "success" in telemetry
        assert "latency_ms" in telemetry

    def test_llm_match_cache_persistence(self, tmp_path, mock_anthropic_client, mock_catalog):
        """Test that cache persists across matcher instances."""
        # First matcher instance
        with patch('utils.llm_matcher.anthropic.Anthropic', return_value=mock_anthropic_client):
            with patch.object(LLMMatcher, '_load_full_catalog', return_value=mock_catalog):
                matcher1 = LLMMatcher(
                    api_key="test-key",
                    cache_dir=tmp_path,
                )
                result1 = matcher1.match("redis:latest")
                assert not result1.cached

        # Second matcher instance (new object, same cache dir)
        with patch('utils.llm_matcher.anthropic.Anthropic', return_value=mock_anthropic_client):
            with patch.object(LLMMatcher, '_load_full_catalog', return_value=mock_catalog):
                matcher2 = LLMMatcher(
                    api_key="test-key",
                    cache_dir=tmp_path,
                )
                result2 = matcher2.match("redis:latest")

                # Should be cached from previous matcher
                assert result2.cached
                assert result2.chainguard_image == result1.chainguard_image

    def test_llm_match_different_models_separate_cache(self, tmp_path, mock_anthropic_client, mock_catalog):
        """Test that different models have separate cache entries."""
        # First matcher with sonnet model
        with patch('utils.llm_matcher.anthropic.Anthropic', return_value=mock_anthropic_client):
            with patch.object(LLMMatcher, '_load_full_catalog', return_value=mock_catalog):
                matcher1 = LLMMatcher(
                    api_key="test-key",
                    model="claude-sonnet-4-5",
                    cache_dir=tmp_path,
                )
                result1 = matcher1.match("redis:latest")
                assert not result1.cached

        # Second matcher with haiku model
        with patch('utils.llm_matcher.anthropic.Anthropic', return_value=mock_anthropic_client):
            with patch.object(LLMMatcher, '_load_full_catalog', return_value=mock_catalog):
                matcher2 = LLMMatcher(
                    api_key="test-key",
                    model="claude-haiku-4-5",
                    cache_dir=tmp_path,
                )
                result2 = matcher2.match("redis:latest")

                # Should NOT be cached because model is different
                assert not result2.cached

    def test_transient_failure_not_cached(self, tmp_path, mock_anthropic_client):
        """Test that transient failures (catalog not available, API errors) are not cached."""
        # Matcher with empty catalog (simulates catalog unavailable)
        with patch('utils.llm_matcher.anthropic.Anthropic', return_value=mock_anthropic_client):
            with patch.object(LLMMatcher, '_load_full_catalog', return_value=[]):
                matcher = LLMMatcher(
                    api_key="test-key",
                    cache_dir=tmp_path,
                )

                # First call - should fail due to empty catalog
                result1 = matcher.match("azure-cloud-node-manager:latest")
                assert result1.chainguard_image is None
                assert "catalog" in result1.reasoning.lower()

        # Now create a matcher with a real catalog
        mock_catalog = ["cloud-provider-azure-node-manager", "redis", "nginx"]
        mock_message = Mock()
        mock_content = Mock()
        mock_content.text = json.dumps({
            "chainguard_image": "cgr.dev/chainguard-private/cloud-provider-azure-node-manager:latest",
            "confidence": 0.95,
            "reasoning": "Direct match for Azure cloud provider node manager"
        })
        mock_message.content = [mock_content]
        mock_anthropic_client.messages.create.return_value = mock_message

        with patch('utils.llm_matcher.anthropic.Anthropic', return_value=mock_anthropic_client):
            with patch.object(LLMMatcher, '_load_full_catalog', return_value=mock_catalog):
                matcher2 = LLMMatcher(
                    api_key="test-key",
                    cache_dir=tmp_path,
                )

                # Second call - should NOT be cached because first failure was transient
                result2 = matcher2.match("azure-cloud-node-manager:latest")
                assert result2.cached is False  # Should retry, not use stale cache
                assert result2.chainguard_image == "cgr.dev/chainguard-private/cloud-provider-azure-node-manager:latest"

    def test_is_transient_failure_detection(self, llm_matcher):
        """Test the transient failure detection logic."""
        # Should detect transient failures (case-insensitive)
        assert llm_matcher._is_transient_failure("Chainguard catalog not available")
        assert llm_matcher._is_transient_failure("LLM client not available")
        assert llm_matcher._is_transient_failure("API error: rate limit exceeded")
        assert llm_matcher._is_transient_failure("Request timed out")
        assert llm_matcher._is_transient_failure("Connection error to API")
        assert llm_matcher._is_transient_failure("Rate limit exceeded")

        # Should NOT detect these as transient (legitimate no-match results)
        assert not llm_matcher._is_transient_failure("No suitable Chainguard equivalent found")
        assert not llm_matcher._is_transient_failure("This is a custom internal image with no public equivalent")
        assert not llm_matcher._is_transient_failure("Image not in catalog")
