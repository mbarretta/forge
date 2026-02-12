"""
Tests for automatic image matching functionality.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from forge_gauge.utils.image_matcher import ImageMatcher, MatchResult, DirectMatchStrategy, NameVariationStrategy


class TestImageMatcher:
    """Test image matching with 4-tier strategy."""

    @pytest.fixture
    def mock_dfc_yaml(self):
        """Mock DFC mappings YAML content."""
        return """
images:
  alpine: chainguard-base:latest
  golang*: go
  nginx: nginx-fips:latest
  python*: python
  postgres*: postgres
"""

    @pytest.fixture
    def mock_manual_mappings(self):
        """Mock manual mappings YAML content."""
        return """
"redis:7.0": "cgr.dev/chainguard/redis:latest"
"memcached:latest": "cgr.dev/chainguard/memcached:latest"
"""

    @pytest.fixture
    def image_matcher(self, tmp_path, mock_dfc_yaml):
        """Create ImageMatcher with mocked DFC mappings."""
        # Create DFC mappings file
        dfc_file = tmp_path / "dfc-mappings.yaml"
        dfc_file.write_text(mock_dfc_yaml)

        # Create ImageMatcher without manual mappings for now
        matcher = ImageMatcher(
            cache_dir=tmp_path,
            dfc_mappings_file=dfc_file,
            manual_mappings_file=tmp_path / "nonexistent.yaml",
            github_token=None
        )
        return matcher

    def test_tier1_dfc_exact_match(self, image_matcher):
        """Test Tier 1: DFC exact match returns 95% confidence."""
        result = image_matcher.match("alpine:latest")

        # DFC matches are normalized to private registry
        assert result.chainguard_image == "cgr.dev/chainguard-private/chainguard-base:latest"
        assert result.confidence == 0.95
        assert result.method == "dfc"

    def test_tier1_dfc_wildcard_match(self, image_matcher):
        """Test Tier 1: DFC wildcard match returns 95% confidence."""
        result = image_matcher.match("golang:1.21")

        # DFC matches are normalized to private registry
        assert result.chainguard_image == "cgr.dev/chainguard-private/go:latest"
        assert result.confidence == 0.95
        assert result.method == "dfc"

    def test_tier2_manual_override(self, tmp_path, mock_dfc_yaml, mock_manual_mappings):
        """Test Tier 2: Manual override returns 100% confidence."""
        # Create both DFC and manual mappings
        dfc_file = tmp_path / "dfc-mappings.yaml"
        dfc_file.write_text(mock_dfc_yaml)

        manual_file = tmp_path / "manual-mappings.yaml"
        manual_file.write_text(mock_manual_mappings)

        matcher = ImageMatcher(
            cache_dir=tmp_path,
            dfc_mappings_file=dfc_file,
            manual_mappings_file=manual_file,
            github_token=None
        )

        result = matcher.match("redis:7.0")

        # Manual mappings are normalized to private registry
        assert result.chainguard_image == "cgr.dev/chainguard-private/redis:latest"
        assert result.confidence == 1.0
        assert result.method == "manual"

    @patch('utils.image_matcher.Tier3HeuristicMatcher._verify_image_exists')
    def test_tier3_heuristic_fips_match(self, mock_verify, image_matcher):
        """Test Tier 3: Heuristic matches FIPS image to FIPS Chainguard private image."""
        # Mock verification to return True for the first candidate
        # Use a FIPS image NOT in DFC mappings to test heuristics
        mock_verify.return_value = True

        result = image_matcher.match("docker.io/library/redis-fips:7.0")

        # No version_matcher means :latest is appended by default
        assert result.chainguard_image == "cgr.dev/chainguard-private/redis-fips:latest"
        assert result.confidence == 0.85
        assert result.method == "heuristic"

    @patch('utils.image_matcher.Tier3HeuristicMatcher._verify_image_exists')
    def test_tier3_heuristic_non_fips_skips_fips_images(self, mock_verify, image_matcher):
        """Test Tier 3: Non-FIPS image should not match to FIPS Chainguard private image."""
        # Mock verification to return True for non-FIPS variant only
        def verify_side_effect(image):
            # Non-FIPS redis exists, FIPS variant should not be tried for non-FIPS input
            return "-fips" not in image

        mock_verify.side_effect = verify_side_effect

        result = image_matcher.match("docker.io/library/redis:7.0")

        # Should match non-FIPS variant, not FIPS (private registry)
        # No version_matcher means :latest is appended by default
        assert result.chainguard_image == "cgr.dev/chainguard-private/redis:latest"
        assert result.confidence == 0.85
        assert result.method == "heuristic"

        # Verify FIPS variant was never checked for non-FIPS input
        fips_calls = [call for call in mock_verify.call_args_list
                      if '-fips' in str(call)]
        assert len(fips_calls) == 0, "FIPS variant should not be checked for non-FIPS image"

    @patch('utils.image_matcher.Tier3HeuristicMatcher._verify_image_exists')
    def test_tier3_heuristic_no_fips_match(self, mock_verify, image_matcher):
        """Test Tier 3: Heuristic match without -fips suffix (private registry)."""
        # Mock verification to return True
        mock_verify.return_value = True

        result = image_matcher.match("docker.io/library/node:20")

        # No version_matcher means :latest is appended by default
        assert result.chainguard_image == "cgr.dev/chainguard-private/node:latest"
        assert result.confidence == 0.85
        assert result.method == "heuristic"

    @patch('utils.image_matcher.Tier3HeuristicMatcher._verify_image_exists')
    def test_tier4_no_match(self, mock_verify, image_matcher):
        """Test Tier 4: No match found returns 0 confidence."""
        # Mock verification to always return False
        mock_verify.return_value = False

        result = image_matcher.match("custom-internal-app:v1.0")

        assert result.chainguard_image is None
        assert result.confidence == 0.0
        assert result.method == "none"

    def test_extract_base_name(self, image_matcher):
        """Test base name extraction from various image references."""
        assert image_matcher.tier3._extract_base_name("docker.io/library/python:3.12") == "python"
        assert image_matcher.tier3._extract_base_name("gcr.io/kaniko-project/executor:latest") == "executor"
        assert image_matcher.tier3._extract_base_name("nginx:1.25") == "nginx"
        assert image_matcher.tier3._extract_base_name("bitnami/postgresql") == "postgresql"
        assert image_matcher.tier3._extract_base_name("python") == "python"
        # FIPS suffixes should be stripped to avoid double-suffixing
        assert image_matcher.tier3._extract_base_name("redis-fips:7.0") == "redis"
        assert image_matcher.tier3._extract_base_name("nginx_fips:latest") == "nginx"
        assert image_matcher.tier3._extract_base_name("docker.io/library/postgres-fips:16") == "postgres"

    def test_generate_candidates_simple(self, image_matcher):
        """Test candidate generation for simple image names."""
        candidates = image_matcher.tier3._generate_candidates("nginx", "nginx:latest")

        # Non-FIPS input should only include non-FIPS variants (private registry only)
        # Candidates no longer include :latest (version matcher resolves tag)
        assert "cgr.dev/chainguard-private/nginx" in candidates
        assert "cgr.dev/chainguard-private/nginx-fips" not in candidates

    def test_generate_candidates_simple_fips(self, image_matcher):
        """Test candidate generation for simple FIPS image names."""
        candidates = image_matcher.tier3._generate_candidates("nginx", "nginx-fips:latest")

        # FIPS input should include both FIPS and non-FIPS variants (private registry only)
        # Candidates no longer include :latest (version matcher resolves tag)
        assert "cgr.dev/chainguard-private/nginx-fips" in candidates
        assert "cgr.dev/chainguard-private/nginx" in candidates

    def test_generate_candidates_bitnami(self, image_matcher):
        """Test candidate generation for bitnami images."""
        candidates = image_matcher.tier3._generate_candidates("postgresql", "bitnami/postgresql:16")

        # Non-FIPS bitnami should only include non-FIPS variants (private registry only)
        # Candidates no longer include :latest (version matcher resolves tag)
        assert "cgr.dev/chainguard-private/postgresql" in candidates
        assert "cgr.dev/chainguard-private/postgresql-iamguarded" in candidates
        assert "cgr.dev/chainguard-private/postgresql-iamguarded-fips" not in candidates

        # IMPORTANT: -iamguarded should come BEFORE direct match for Bitnami images
        iamguarded_idx = candidates.index("cgr.dev/chainguard-private/postgresql-iamguarded")
        direct_idx = candidates.index("cgr.dev/chainguard-private/postgresql")
        assert iamguarded_idx < direct_idx, "Bitnami images should prioritize -iamguarded variant"

    def test_generate_candidates_bitnami_fips(self, image_matcher):
        """Test candidate generation for bitnami FIPS images."""
        candidates = image_matcher.tier3._generate_candidates("postgresql", "bitnami/postgresql-fips:16")

        # FIPS bitnami should include both FIPS and non-FIPS variants (private registry only)
        # Candidates no longer include :latest (version matcher resolves tag)
        assert "cgr.dev/chainguard-private/postgresql-fips" in candidates
        assert "cgr.dev/chainguard-private/postgresql" in candidates
        assert "cgr.dev/chainguard-private/postgresql-iamguarded-fips" in candidates
        assert "cgr.dev/chainguard-private/postgresql-iamguarded" in candidates

        # IMPORTANT: -iamguarded-fips should come BEFORE -fips for Bitnami FIPS images
        iamguarded_fips_idx = candidates.index("cgr.dev/chainguard-private/postgresql-iamguarded-fips")
        direct_fips_idx = candidates.index("cgr.dev/chainguard-private/postgresql-fips")
        assert iamguarded_fips_idx < direct_fips_idx, "Bitnami FIPS images should prioritize -iamguarded-fips variant"

    def test_generate_candidates_bitnami_kubectl(self, image_matcher):
        """Test candidate generation for bitnami/kubectl → kubectl-iamguarded."""
        candidates = image_matcher.tier3._generate_candidates("kubectl", "bitnami/kubectl:1.28")

        # Verify kubectl-iamguarded is included
        # Candidates no longer include :latest (version matcher resolves tag)
        assert "cgr.dev/chainguard-private/kubectl-iamguarded" in candidates
        assert "cgr.dev/chainguard-private/kubectl" in candidates

        # IMPORTANT: -iamguarded should come BEFORE direct match
        iamguarded_idx = candidates.index("cgr.dev/chainguard-private/kubectl-iamguarded")
        direct_idx = candidates.index("cgr.dev/chainguard-private/kubectl")
        assert iamguarded_idx < direct_idx, "bitnami/kubectl should prioritize kubectl-iamguarded"

    def test_generate_candidates_complex_path(self, image_matcher):
        """Test candidate generation for complex image paths."""
        candidates = image_matcher.tier3._generate_candidates(
            "executor",
            "gcr.io/kaniko-project/executor:latest"
        )

        # Non-FIPS input should only include non-FIPS variants (private registry only)
        # Candidates no longer include :latest (version matcher resolves tag)
        assert "cgr.dev/chainguard-private/executor" in candidates
        assert "cgr.dev/chainguard-private/kaniko-project-executor" in candidates
        assert "cgr.dev/chainguard-private/executor-fips" not in candidates

    def test_generate_candidates_complex_path_fips(self, image_matcher):
        """Test candidate generation for complex FIPS image paths."""
        candidates = image_matcher.tier3._generate_candidates(
            "executor",
            "gcr.io/kaniko-project/executor-fips:latest"
        )

        # FIPS input should include both FIPS and non-FIPS variants (private registry only)
        # Candidates no longer include :latest (version matcher resolves tag)
        assert "cgr.dev/chainguard-private/executor-fips" in candidates
        assert "cgr.dev/chainguard-private/executor" in candidates
        assert "cgr.dev/chainguard-private/kaniko-project-executor-fips" in candidates
        assert "cgr.dev/chainguard-private/kaniko-project-executor" in candidates

    def test_generate_candidates_kyverno_example(self, image_matcher):
        """Test candidate generation for kyverno/background-controller pattern."""
        candidates = image_matcher.tier3._generate_candidates(
            "background-controller",
            "ghcr.io/kyverno/background-controller:v1.10.3"
        )

        # Should generate kyverno-background-controller pattern for private registry only
        # Candidates no longer include :latest (version matcher resolves tag)
        assert "cgr.dev/chainguard-private/kyverno-background-controller" in candidates

    def test_name_variations(self, image_matcher):
        """Test common name variations via NameVariationStrategy."""
        from forge_gauge.utils.image_matcher import NameVariationStrategy
        strategy = NameVariationStrategy()

        # Test mongo → mongodb
        # Candidates no longer include :latest (version matcher resolves tag)
        candidates = strategy.generate("mongo", "mongo:latest", False)
        assert "cgr.dev/chainguard-private/mongodb" in candidates

        # Test postgresql → postgres
        candidates = strategy.generate("postgresql", "postgresql:15", False)
        assert "cgr.dev/chainguard-private/postgres" in candidates

    def test_variant_suffix_stripping(self):
        """Test that build variant suffixes like -native are stripped."""
        strategy = DirectMatchStrategy()

        # Test kafka-native → kafka
        candidates = strategy.generate("kafka-native", "kafka-native:4.1.1", False)
        assert "cgr.dev/chainguard-private/kafka-native" in candidates
        assert "cgr.dev/chainguard-private/kafka" in candidates

        # Test nginx-slim → nginx
        candidates = strategy.generate("nginx-slim", "nginx-slim:latest", False)
        assert "cgr.dev/chainguard-private/nginx-slim" in candidates
        assert "cgr.dev/chainguard-private/nginx" in candidates

        # Test with FIPS
        candidates = strategy.generate("kafka-native", "kafka-native-fips:4.1.1", True)
        assert "cgr.dev/chainguard-private/kafka-native-fips" in candidates
        assert "cgr.dev/chainguard-private/kafka-native" in candidates
        assert "cgr.dev/chainguard-private/kafka-fips" in candidates
        assert "cgr.dev/chainguard-private/kafka" in candidates

    @patch('integrations.github_metadata.GitHubMetadataClient.get_image_tier')
    def test_verify_image_exists_success(self, mock_get_tier, image_matcher):
        """Test image verification when image exists."""
        mock_get_tier.return_value = "free"

        result = image_matcher.tier3._verify_image_exists("cgr.dev/chainguard/python:latest")

        assert result is True
        mock_get_tier.assert_called_once_with("python")

    @patch('integrations.github_metadata.GitHubMetadataClient.get_image_tier')
    def test_verify_image_exists_not_found(self, mock_get_tier, image_matcher):
        """Test image verification when image doesn't exist."""
        mock_get_tier.return_value = None

        result = image_matcher.tier3._verify_image_exists("cgr.dev/chainguard/nonexistent:latest")

        assert result is False

    @patch('utils.docker_utils.image_exists_in_registry')
    @patch('integrations.github_metadata.GitHubMetadataClient.get_image_tier')
    def test_verify_image_exists_error(self, mock_get_tier, mock_docker_verify, image_matcher):
        """Test image verification when both API and docker verification fail."""
        mock_get_tier.side_effect = Exception("API error")
        mock_docker_verify.side_effect = Exception("Docker error")

        result = image_matcher.tier3._verify_image_exists("cgr.dev/chainguard/python:latest")

        assert result is False

    def test_manual_mappings_loading_missing_file(self, tmp_path, mock_dfc_yaml):
        """Test manual mappings loading when file doesn't exist."""
        dfc_file = tmp_path / "dfc-mappings.yaml"
        dfc_file.write_text(mock_dfc_yaml)

        matcher = ImageMatcher(
            cache_dir=tmp_path,
            dfc_mappings_file=dfc_file,
            manual_mappings_file=tmp_path / "nonexistent.yaml",
            github_token=None
        )

        assert len(matcher.tier2.manual_mappings) == 0

    def test_manual_mappings_loading_empty_file(self, tmp_path, mock_dfc_yaml):
        """Test manual mappings loading when file is empty."""
        dfc_file = tmp_path / "dfc-mappings.yaml"
        dfc_file.write_text(mock_dfc_yaml)

        manual_file = tmp_path / "manual-mappings.yaml"
        manual_file.write_text("")

        matcher = ImageMatcher(
            cache_dir=tmp_path,
            dfc_mappings_file=dfc_file,
            manual_mappings_file=manual_file,
            github_token=None
        )

        assert len(matcher.tier2.manual_mappings) == 0

    def test_manual_mappings_for_non_dfc_images(self, tmp_path):
        """Test that manual mappings work for images not in DFC."""
        # Create DFC mappings without redis
        dfc_yaml = """
images:
  nginx: nginx:latest
"""
        dfc_file = tmp_path / "dfc-mappings.yaml"
        dfc_file.write_text(dfc_yaml)

        # Create manual mappings with redis (not in DFC)
        manual_yaml = """
"redis:7.0": "cgr.dev/chainguard/redis-fips:latest"
"""
        manual_file = tmp_path / "manual-mappings.yaml"
        manual_file.write_text(manual_yaml)

        matcher = ImageMatcher(
            cache_dir=tmp_path,
            dfc_mappings_file=dfc_file,
            manual_mappings_file=manual_file,
            github_token=None
        )

        result = matcher.match("redis:7.0")

        # Manual mapping should match with 100% confidence (normalized to private registry)
        assert result.method == "manual"
        assert result.confidence == 1.0
        assert result.chainguard_image == "cgr.dev/chainguard-private/redis-fips:latest"

    @patch('utils.image_matcher.Tier4LLMMatcher._verify_image_exists')
    @patch('utils.image_matcher.Tier3HeuristicMatcher._verify_image_exists')
    def test_tier4_llm_hallucination_rejected(self, mock_tier3_verify, mock_tier4_verify, tmp_path, mock_dfc_yaml):
        """Test that LLM hallucinations are rejected when image doesn't exist."""
        # Create DFC mappings
        dfc_file = tmp_path / "dfc-mappings.yaml"
        dfc_file.write_text(mock_dfc_yaml)

        # Mock LLM matcher that suggests a non-existent image
        mock_llm_matcher = Mock()
        mock_llm_result = Mock()
        mock_llm_result.chainguard_image = "cgr.dev/chainguard-private/jmeter:latest"
        mock_llm_result.confidence = 0.85
        mock_llm_result.reasoning = "JMeter is a testing tool"
        mock_llm_matcher.match.return_value = mock_llm_result
        mock_llm_matcher.confidence_threshold = 0.7

        # Mock verification to return False (image doesn't exist)
        # This will be called by both Tier 3 heuristics and Tier 4 LLM
        mock_tier3_verify.return_value = False
        mock_tier4_verify.return_value = False

        matcher = ImageMatcher(
            cache_dir=tmp_path,
            dfc_mappings_file=dfc_file,
            github_token=None,
            llm_matcher=mock_llm_matcher,
        )

        result = matcher.match("custom-obscure-image:1.0")

        # Should NOT return the hallucinated image
        assert result.chainguard_image is None
        assert result.confidence == 0.0
        assert result.method == "none"

        # Verify that LLM verification was called
        assert mock_tier4_verify.called
        verify_calls = [call[0][0] for call in mock_tier4_verify.call_args_list]
        assert "cgr.dev/chainguard-private/jmeter:latest" in verify_calls

    @patch('utils.image_matcher.Tier4LLMMatcher._verify_image_exists')
    @patch('utils.image_matcher.Tier3HeuristicMatcher._verify_image_exists')
    def test_tier4_llm_verified_match(self, mock_tier3_verify, mock_tier4_verify, tmp_path, mock_dfc_yaml):
        """Test that verified LLM matches are accepted."""
        # Create DFC mappings
        dfc_file = tmp_path / "dfc-mappings.yaml"
        dfc_file.write_text(mock_dfc_yaml)

        # Mock LLM matcher that suggests an existing image
        mock_llm_matcher = Mock()
        mock_llm_result = Mock()
        mock_llm_result.chainguard_image = "cgr.dev/chainguard-private/kyverno-background-controller:latest"
        mock_llm_result.confidence = 0.85
        mock_llm_result.reasoning = "Kyverno background controller with hyphenated naming"
        mock_llm_matcher.match.return_value = mock_llm_result
        mock_llm_matcher.confidence_threshold = 0.7

        # Mock verification to return False for Tier 3 heuristics, but True for the LLM suggestion
        # This simulates Tier 3 failing but Tier 4 succeeding
        mock_tier3_verify.return_value = False
        mock_tier4_verify.return_value = True

        matcher = ImageMatcher(
            cache_dir=tmp_path,
            dfc_mappings_file=dfc_file,
            github_token=None,
            llm_matcher=mock_llm_matcher,
        )

        # Use a complex image that won't match via simple heuristics
        result = matcher.match("internal.registry.io/kyverno-ctrl:v1.0")

        # Should return the verified LLM match
        assert result.chainguard_image == "cgr.dev/chainguard-private/kyverno-background-controller:latest"
        assert result.confidence == 0.85
        assert result.method == "llm"
        assert result.reasoning == "Kyverno background controller with hyphenated naming"

        # Verify that the LLM-suggested image was checked by Tier 4
        assert mock_tier4_verify.called
        verify_calls = [call[0][0] for call in mock_tier4_verify.call_args_list]
        assert "cgr.dev/chainguard-private/kyverno-background-controller:latest" in verify_calls

    def test_dfc_match_redis_sentinel_normalized(self, tmp_path):
        """Test that redis → redis-sentinel DFC match is normalized to private registry."""
        # Create DFC mappings with redis → redis-sentinel (as in real DFC)
        dfc_yaml = """
images:
  redis: redis-sentinel
"""
        dfc_file = tmp_path / "dfc-mappings.yaml"
        dfc_file.write_text(dfc_yaml)

        matcher = ImageMatcher(
            cache_dir=tmp_path,
            dfc_mappings_file=dfc_file,
            github_token=None
        )

        result = matcher.match("redis:7")

        # Should match via DFC and be normalized to private registry
        assert result.chainguard_image == "cgr.dev/chainguard-private/redis-sentinel:latest"
        assert result.method == "dfc"
        assert result.confidence == 0.95
