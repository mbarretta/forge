"""
Automatic image matching for Chainguard equivalents.

Implements a 4-tier matching strategy to automatically find Chainguard images
corresponding to alternative/customer images.
"""

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from forge_gauge.constants import (
    CHAINGUARD_PRIVATE_REGISTRY,
    CHAINGUARD_PUBLIC_REGISTRY,
    MATCH_CONFIDENCE_DFC,
    MATCH_CONFIDENCE_HEURISTIC,
    MATCH_CONFIDENCE_MANUAL,
)
from forge_gauge.utils.paths import get_config_path
from forge_gauge.integrations.dfc_mappings import DFCMappings
from forge_gauge.utils.image_utils import ImageReference, convert_to_private_registry, extract_base_name
from forge_gauge.utils.image_verification import ImageVerificationService
from forge_gauge.utils.llm_utils import load_yaml_mappings
from forge_gauge.utils.registry_access import RegistryAccessChecker
from forge_gauge.utils.upstream_finder import UpstreamImageFinder
from forge_gauge.utils.version_matcher import VersionMatcher

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    """Result of an image matching attempt."""

    chainguard_image: Optional[str]
    """Matched Chainguard image reference"""

    confidence: float
    """Confidence score (0.0 - 1.0)"""

    method: str
    """Matching method used (dfc, manual, heuristic, llm, none)"""

    alternatives: Optional[list[str]] = None
    """Alternative matches (for fuzzy results)"""

    upstream_image: Optional[str] = None
    """Discovered upstream image (if upstream finding was enabled)"""

    upstream_confidence: Optional[float] = None
    """Upstream discovery confidence score"""

    upstream_method: Optional[str] = None
    """Upstream discovery method used"""

    reasoning: Optional[str] = None
    """LLM reasoning (if method is llm)"""


def strip_version_suffix(name: str) -> str:
    """
    Strip version suffixes and numbers from image names.

    Handles patterns like:
    - mongodb_8.x → mongodb
    - solr-9 → solr
    - redis7 → redis
    - ruby33 → ruby
    - airflowv3 → airflow

    Args:
        name: Image name to strip version from

    Returns:
        Name with version suffix removed
    """
    # Strip version patterns with "v" prefix first (e.g., "airflowv3" → "airflow")
    name = re.sub(r'v\d+(?:\.\w+)?$', '', name)

    # Strip trailing version patterns like "-9", "_8.x", "7", "33"
    # Pattern: optional separator (-, _, or nothing) + version number + optional .x suffix
    name = re.sub(r'[-_]?\d+(?:\.\w+)?$', '', name)

    return name


class CandidateStrategy(ABC):
    """
    Base strategy for generating candidate Chainguard image names.

    Each strategy implements a specific heuristic for transforming
    alternative image names into potential Chainguard equivalents.
    """

    @abstractmethod
    def generate(self, base_name: str, full_image: str, has_fips: bool) -> list[str]:
        """
        Generate candidate Chainguard images.

        Args:
            base_name: Extracted base image name (e.g., 'nginx', 'python')
            full_image: Full alternative image reference
            has_fips: Whether the image has FIPS indicators

        Returns:
            List of candidate Chainguard image references
        """


class BitnamiStrategy(CandidateStrategy):
    """Strategy for Bitnami images → -iamguarded variants."""

    def generate(self, base_name: str, full_image: str, has_fips: bool) -> list[str]:
        """Generate candidates for Bitnami images."""
        if "bitnami" not in full_image.lower():
            return []

        candidates = []

        if has_fips:
            # Rule 1: Bitnami FIPS → -iamguarded-fips (priority)
            candidates.append(f"{CHAINGUARD_PRIVATE_REGISTRY}/{base_name}-iamguarded-fips")
            # Rule 2: Fallback to -fips
            candidates.append(f"{CHAINGUARD_PRIVATE_REGISTRY}/{base_name}-fips")
            candidates.append(f"{CHAINGUARD_PRIVATE_REGISTRY}/{base_name}-bitnami-fips")
            # Rule 3: Fallback to non-FIPS -iamguarded
            candidates.append(f"{CHAINGUARD_PRIVATE_REGISTRY}/{base_name}-iamguarded")
        else:
            # Rule 4: Bitnami → -iamguarded (priority)
            candidates.append(f"{CHAINGUARD_PRIVATE_REGISTRY}/{base_name}-iamguarded")

        # Rule 5: Direct match as fallback for Bitnami
        candidates.append(f"{CHAINGUARD_PRIVATE_REGISTRY}/{base_name}")

        return candidates


class DirectMatchStrategy(CandidateStrategy):
    """Strategy for direct base name matching (non-Bitnami)."""

    # Build variant suffixes that indicate the same base image with a different build
    # e.g., kafka-native is Kafka with GraalVM native compilation
    VARIANT_SUFFIXES = ["-native", "-slim", "-alpine"]

    def generate(self, base_name: str, full_image: str, has_fips: bool) -> list[str]:
        """Generate direct match candidates."""
        # Only apply to non-Bitnami images
        if "bitnami" in full_image.lower():
            return []

        candidates = []

        if has_fips:
            # Rule 6: Non-Bitnami FIPS → direct -fips
            candidates.append(f"{CHAINGUARD_PRIVATE_REGISTRY}/{base_name}-fips")

        # Rule 7: Direct match without -fips
        candidates.append(f"{CHAINGUARD_PRIVATE_REGISTRY}/{base_name}")

        # Rule 7b: Try stripping build variant suffixes
        # e.g., kafka-native → kafka (GraalVM native builds)
        for suffix in self.VARIANT_SUFFIXES:
            if base_name.endswith(suffix):
                stripped = base_name[:-len(suffix)]
                if has_fips:
                    candidates.append(f"{CHAINGUARD_PRIVATE_REGISTRY}/{stripped}-fips")
                candidates.append(f"{CHAINGUARD_PRIVATE_REGISTRY}/{stripped}")
                break  # Only strip one suffix

        return candidates


class PathFlatteningStrategy(CandidateStrategy):
    """Strategy for flattening complex image paths."""

    # Organizational namespaces that should be skipped when building hyphenated names
    # These are registry-specific prefixes, not meaningful project names
    SKIP_PREFIXES = {
        "library",      # Docker Hub official images
        "opensource",   # Iron Bank organizational prefix
        "ironbank",     # Iron Bank namespace
        "_",            # Docker Hub internal
    }

    def generate(self, base_name: str, full_image: str, has_fips: bool) -> list[str]:
        """Generate candidates from complex paths."""
        # Rule 8: Flatten complex paths (e.g., calico/node → calico-node)
        if "/" not in full_image:
            return []

        candidates = []
        parts = full_image.split("/")

        # Try last component
        last_component = parts[-1].split(":")[0].split("@")[0].lower()
        # Strip FIPS suffix to avoid double-suffixing
        last_component = re.sub(r"[-_]fips$", "", last_component)

        if last_component != base_name:
            if has_fips:
                candidates.append(f"{CHAINGUARD_PRIVATE_REGISTRY}/{last_component}-fips")
            candidates.append(f"{CHAINGUARD_PRIVATE_REGISTRY}/{last_component}")

        # Try last two components joined with hyphen
        # (e.g., ghcr.io/kyverno/background-controller → kyverno-background-controller)
        # Skip organizational prefixes that don't add meaningful context
        if len(parts) >= 2:
            second_last = parts[-2].lower()

            # Skip organizational namespaces - they don't represent project names
            if second_last not in self.SKIP_PREFIXES:
                hyphenated = f"{second_last}-{last_component}"
                if has_fips:
                    candidates.append(f"{CHAINGUARD_PRIVATE_REGISTRY}/{hyphenated}-fips")
                candidates.append(f"{CHAINGUARD_PRIVATE_REGISTRY}/{hyphenated}")

        return candidates


class NameVariationStrategy(CandidateStrategy):
    """Strategy for common name variations (mongo → mongodb, etc.)."""

    # Common variations mapping
    NAME_MAP = {
        "mongo": "mongodb",
        "postgresql": "postgres",
        "node-chrome": "node-chromium",
        # Add more as discovered
    }

    def generate(self, base_name: str, full_image: str, has_fips: bool) -> list[str]:
        """Generate candidates from name variations."""
        # Rule 9: Common name variations
        if base_name not in self.NAME_MAP:
            return []

        candidates = []
        variation = self.NAME_MAP[base_name]

        if has_fips:
            candidates.append(f"{CHAINGUARD_PRIVATE_REGISTRY}/{variation}-fips")
        candidates.append(f"{CHAINGUARD_PRIVATE_REGISTRY}/{variation}")

        return candidates


class BaseOSStrategy(CandidateStrategy):
    """
    Strategy for mapping base OS images to chainguard-base.

    Handles comprehensive list of minimal OS base images from various vendors.
    Applies version stripping and modifier removal (base, minimal, fips, etc.).
    """

    # Exhaustive list of base OS image patterns
    BASE_OS_PATTERNS = {
        # Red Hat Universal Base Images (UBI)
        "ubi",
        "ubi-minimal",
        "ubi-micro",
        "ubi-init",

        # Alpine Linux
        "alpine",

        # Debian
        "debian",
        "debian-slim",

        # Ubuntu
        "ubuntu",
        "ubuntu-minimal",

        # CentOS/Rocky/Alma
        "centos",
        "rockylinux",
        "almalinux",

        # Amazon Linux
        "amazonlinux",
        "al2023",

        # Google Distroless
        "distroless",
        "distroless-base",
        "static-debian",
        "base-debian",

        # Scratch (empty base)
        "scratch",

        # BusyBox
        "busybox",

        # Fedora
        "fedora",
        "fedora-minimal",

        # OpenSUSE
        "opensuse",
        "leap",
        "tumbleweed",

        # Other minimal bases
        "wolfi",
        "wolfi-base",
        "chainguard-base",  # Normalize to itself
        "base",  # Generic "base" images
    }

    def generate(self, base_name: str, full_image: str, has_fips: bool) -> list[str]:
        """Generate candidates for base OS images."""
        # Normalize the image name
        normalized = self._normalize_os_name(base_name, full_image)

        if not normalized:
            return []

        # Check if normalized name matches any base OS pattern
        if normalized not in self.BASE_OS_PATTERNS:
            return []

        # Map to chainguard-base
        candidates = []

        if has_fips:
            # Try FIPS variant first
            candidates.append(f"{CHAINGUARD_PRIVATE_REGISTRY}/chainguard-base-fips")

        # Standard chainguard-base
        candidates.append(f"{CHAINGUARD_PRIVATE_REGISTRY}/chainguard-base")

        return candidates

    # OS normalization configuration
    _VERSION_STRIP_PATTERNS = [
        # Pattern: (regex_pattern, replacement) - applied in order
        (r"^(ubi|alpine|centos|rockylinux|almalinux)\d+", r"\1"),  # Strip trailing digits
        (r"^(debian|ubuntu)[-_]\d+(?:\.\d+)?", r"\1"),              # Strip version with separator
        (r"^fedora[-_]?\d+", "fedora"),                              # Fedora versions
    ]

    _OS_ALIASES = {
        # Exact name mappings
        "al": "amazonlinux",      # After version stripping: al2023, al2 → al
        "al2": "amazonlinux",     # Before version stripping
        "al2023": "amazonlinux",  # Before version stripping
        "al2022": "amazonlinux",  # Before version stripping
    }

    _SUBSTRING_NORMALIZATIONS = [
        # If name contains substring, normalize to target
        ("distroless", "distroless"),
        ("leap", "leap"),
        ("tumbleweed", "tumbleweed"),
    ]

    def _normalize_os_name(self, base_name: str, full_image: str) -> Optional[str]:
        """
        Normalize OS image name by stripping versions, modifiers, and special characters.

        Handles patterns like:
        - ubi8, ubi9, ubi10 → ubi
        - alpine3 → alpine
        - debian-12-slim → debian-slim
        - al2023 → amazonlinux

        Args:
            base_name: Base image name extracted from full reference
            full_image: Full image reference for context

        Returns:
            Normalized OS name or None if not a base OS image
        """
        name = base_name.lower()

        # Strip version suffixes first
        name = strip_version_suffix(name)

        # Strip common modifiers (preserve meaningful variants like -micro, -minimal, -slim)
        if name.endswith("-base") and name != "base":
            name = name.replace("-base", "")
        name = re.sub(r"[-_]fips$", "", name)

        # Apply version-stripping patterns
        for pattern, replacement in self._VERSION_STRIP_PATTERNS:
            name = re.sub(pattern, replacement, name)

        # Apply exact aliases
        name = self._OS_ALIASES.get(name, name)

        # Apply substring-based normalizations (check prefix to avoid false positives)
        for substring, target in self._SUBSTRING_NORMALIZATIONS:
            if name.startswith(substring):
                name = target
                break

        return name if name else None


class TierMatcher(ABC):
    """
    Base class for tier-based image matchers.

    Each tier implements a specific matching strategy with associated confidence level.
    """

    @abstractmethod
    def match(self, image: str) -> Optional[MatchResult]:
        """
        Attempt to match image using this tier's strategy.

        Args:
            image: Image reference to match

        Returns:
            MatchResult if match found, None otherwise
        """


class Tier1DFCMatcher(TierMatcher):
    """Tier 1: DFC (Directory-for-Chainguard) Mappings - 95% confidence."""

    def __init__(self, cache_dir: Optional[Path] = None, dfc_mappings_file: Optional[Path] = None):
        """
        Initialize DFC matcher.

        Args:
            cache_dir: Cache directory for DFC mappings
            dfc_mappings_file: Optional local DFC mappings file
        """
        self.dfc = DFCMappings(cache_dir=cache_dir, local_file=dfc_mappings_file)
        self.dfc.load_mappings()

    def match(self, image: str) -> Optional[MatchResult]:
        """Match using DFC mappings."""
        dfc_match = self.dfc.match_image(image)
        if dfc_match:
            dfc_match = convert_to_private_registry(dfc_match)

            logger.debug(f"DFC match found for {image}: {dfc_match}")
            return MatchResult(
                chainguard_image=dfc_match,
                confidence=MATCH_CONFIDENCE_DFC,
                method="dfc",
            )
        return None


class Tier2ManualMatcher(TierMatcher):
    """Tier 2: Local Manual Overrides - 100% confidence."""

    def __init__(self, manual_mappings_file: Optional[Path] = None):
        """
        Initialize manual matcher.

        Args:
            manual_mappings_file: Optional local manual overrides file
        """
        self.manual_mappings_file = manual_mappings_file or get_config_path("image_mappings.yaml")
        self.manual_mappings: dict[str, str] = {}
        self._load_manual_mappings()

    def match(self, image: str) -> Optional[MatchResult]:
        """Match using manual mappings."""
        if image in self.manual_mappings:
            manual_match = convert_to_private_registry(self.manual_mappings[image])

            logger.debug(f"Manual mapping found for {image}: {manual_match}")
            return MatchResult(
                chainguard_image=manual_match,
                confidence=MATCH_CONFIDENCE_MANUAL,
                method="manual",
            )
        return None

    def _load_manual_mappings(self) -> None:
        """Load manual override mappings from YAML file."""
        data = load_yaml_mappings(self.manual_mappings_file, "manual image mappings")
        if data:
            self.manual_mappings = data


class Tier3HeuristicMatcher(TierMatcher):
    """Tier 3: Heuristic Rules - 85% confidence."""

    def __init__(self, github_token: Optional[str] = None):
        """
        Initialize heuristic matcher.

        Args:
            github_token: GitHub token for metadata API access (for image verification)
        """
        self.image_verifier = ImageVerificationService(github_token=github_token)
        # Initialize candidate generation strategies
        # Order matters: more specific strategies should come first
        self.strategies = [
            BaseOSStrategy(),  # Check for base OS images first
            BitnamiStrategy(),
            PathFlatteningStrategy(),  # Try path-based matches before direct (e.g., calico/node → calico-node)
            DirectMatchStrategy(),
            NameVariationStrategy(),
        ]

    def match(self, image: str) -> Optional[MatchResult]:
        """Match using heuristic rules."""
        base_name = self._extract_base_name(image)
        candidates = self._generate_candidates(base_name, image)

        # Try each candidate and verify existence
        for candidate in candidates:
            if self._verify_image_exists(candidate):
                logger.debug(f"Heuristic match found for {image}: {candidate}")
                return MatchResult(
                    chainguard_image=candidate,
                    confidence=MATCH_CONFIDENCE_HEURISTIC,
                    method="heuristic",
                )

        return None

    def _has_fips_indicator(self, image: str) -> bool:
        """Check if image name/tag has FIPS indicators."""
        image_lower = image.lower()
        fips_patterns = [
            "-fips",
            "_fips",
            ":fips",
            "fips-",
            "fips_",
            "/fips",
        ]
        return any(pattern in image_lower for pattern in fips_patterns)

    def _generate_candidates(self, base_name: str, full_image: str) -> list[str]:
        """Generate candidate Chainguard image names using strategy pattern."""
        has_fips = self._has_fips_indicator(full_image)

        # Apply all strategies and collect candidates
        candidates = []
        for strategy in self.strategies:
            strategy_candidates = strategy.generate(base_name, full_image, has_fips)
            candidates.extend(strategy_candidates)

        return candidates

    def _extract_base_name(self, image: str) -> str:
        """Extract base image name from full reference."""
        ref = ImageReference.parse(image)
        name = ref.base_name(strip_fips=True, strip_version=True)
        return name

    def _verify_image_exists(self, image: str) -> bool:
        """Verify if Chainguard image exists."""
        return self.image_verifier.verify_image_exists(image)


class Tier4LLMMatcher(TierMatcher):
    """Tier 4: LLM-Powered Fuzzy Matching with full catalog.

    The LLM matcher now handles:
    1. Matching against full Chainguard catalog (no hallucination)
    2. Web search for understanding source images
    3. Iterative refinement for hard cases
    """

    def __init__(self, llm_matcher, github_token: Optional[str] = None):
        """
        Initialize LLM matcher.

        Args:
            llm_matcher: Configured LLMMatcher instance
            github_token: GitHub token for image verification (kept for compatibility)
        """
        self.llm_matcher = llm_matcher
        self.image_verifier = ImageVerificationService(github_token=github_token)

    def match(self, image: str) -> Optional[MatchResult]:
        """Match using LLM with full catalog matching.

        The LLM matcher validates against the catalog internally,
        but we also verify as a defense-in-depth measure.
        """
        if not self.llm_matcher:
            return None

        llm_result = self.llm_matcher.match(image)

        # Check if we got a valid match
        if not llm_result.chainguard_image:
            return None

        if llm_result.confidence < self.llm_matcher.confidence_threshold:
            logger.debug(
                f"LLM match for {image} below threshold: {llm_result.confidence:.0%}"
            )
            return None

        # Convert public registry to private if needed
        chainguard_image = convert_to_private_registry(llm_result.chainguard_image)

        # Defense-in-depth: verify the image exists even though LLM should
        # have validated against the catalog
        if not self._verify_image_exists(chainguard_image):
            logger.warning(
                f"LLM suggested non-existent image for {image}: {chainguard_image}"
            )
            return None

        logger.debug(
            f"LLM match for {image}: {chainguard_image} "
            f"(confidence: {llm_result.confidence:.0%})"
        )

        return MatchResult(
            chainguard_image=chainguard_image,
            confidence=llm_result.confidence,
            method="llm",
            reasoning=llm_result.reasoning,
        )

    def _verify_image_exists(self, image: str) -> bool:
        """Verify if Chainguard image exists."""
        return self.image_verifier.verify_image_exists(image)


class ImageMatcher:
    """
    Orchestrates 4-tier image matching strategy.

    Coordinates tier-based matchers to find Chainguard equivalents
    for alternative container images.

    Tier 1: DFC Mappings (95% confidence)
    Tier 2: Local Manual Overrides (100% confidence)
    Tier 3: Heuristic Rules (85% confidence)
    Tier 4: LLM-Powered Fuzzy Matching (70%+ confidence)
    """

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        dfc_mappings_file: Optional[Path] = None,
        manual_mappings_file: Optional[Path] = None,
        github_token: Optional[str] = None,
        upstream_finder: Optional[UpstreamImageFinder] = None,
        llm_matcher=None,
        registry_checker: Optional[RegistryAccessChecker] = None,
        prefer_fips: bool = False,
        version_matcher: Optional[VersionMatcher] = None,
    ):
        """
        Initialize image matcher coordinator.

        Args:
            cache_dir: Cache directory for DFC mappings
            dfc_mappings_file: Optional local DFC mappings file
            manual_mappings_file: Optional local manual overrides file
            github_token: GitHub token for metadata API access
            upstream_finder: Optional upstream image finder for discovering public equivalents
            llm_matcher: Optional LLM matcher for Tier 4 fuzzy matching
            registry_checker: Optional registry access checker for skipping upstream discovery
            prefer_fips: If True, prefer -fips variants of Chainguard images when available
            version_matcher: Optional version matcher for intelligent version resolution
        """
        self.upstream_finder = upstream_finder
        self.registry_checker = registry_checker
        self.prefer_fips = prefer_fips
        self.version_matcher = version_matcher

        # Initialize tier-based matchers
        self.tier1 = Tier1DFCMatcher(cache_dir=cache_dir, dfc_mappings_file=dfc_mappings_file)
        self.tier2 = Tier2ManualMatcher(manual_mappings_file=manual_mappings_file)
        self.tier3 = Tier3HeuristicMatcher(github_token=github_token)
        self.tier4 = Tier4LLMMatcher(llm_matcher=llm_matcher, github_token=github_token) if llm_matcher else None

        # Image verifier for checking FIPS variant existence
        self.image_verifier = ImageVerificationService(github_token=github_token)

    def match(self, alternative_image: str) -> MatchResult:
        """
        Find Chainguard image match for alternative image.

        Orchestrates 4-tier matching strategy with upstream discovery support.

        Args:
            alternative_image: Alternative/source image reference

        Returns:
            MatchResult with matched image and metadata
        """
        # Step 1: Check if registry is accessible (skip upstream discovery if so)
        upstream_result = None
        image_to_match = alternative_image
        skip_upstream = False

        if self.registry_checker:
            if self.registry_checker.is_accessible(alternative_image):
                # Registry is known and accessible - match directly
                registry = self.registry_checker.get_registry(alternative_image)
                logger.debug(f"Registry '{registry}' is accessible - skipping upstream discovery")
                skip_upstream = True

        # Step 2: Try upstream discovery (only if registry not accessible)
        if self.upstream_finder and not skip_upstream:
            upstream_result = self.upstream_finder.find_upstream(alternative_image)
            if upstream_result.upstream_image:
                logger.info(
                    f"Upstream found: {alternative_image} → {upstream_result.upstream_image} "
                    f"(confidence: {upstream_result.confidence:.0%}, method: {upstream_result.method})"
                )
                image_to_match = upstream_result.upstream_image

        # Step 3: Try all tiers with the image to match (upstream if found, original otherwise)
        # Order: Manual (user overrides) → DFC → Heuristic → LLM
        for tier_matcher in [self.tier2, self.tier1, self.tier3, self.tier4]:
            if tier_matcher is None:
                continue

            result = tier_matcher.match(image_to_match)
            if result:
                # Add upstream information if available
                if upstream_result:
                    result.upstream_image = upstream_result.upstream_image
                    result.upstream_confidence = upstream_result.confidence
                    result.upstream_method = upstream_result.method

                # Step 4: Try FIPS variant if prefer_fips is enabled
                if self.prefer_fips:
                    result = self._try_fips_variant(result)

                # Step 5: Apply version matching or default to :latest
                if result.chainguard_image:
                    if self.version_matcher:
                        result = self._apply_version_matching(result, alternative_image)
                    else:
                        # No version matcher - append :latest if no tag present
                        result = self._apply_latest_tag(result)

                return result

        # No match found
        logger.debug(f"No match found for {image_to_match}")
        return MatchResult(
            chainguard_image=None,
            confidence=0.0,
            method="none",
            upstream_image=upstream_result.upstream_image if upstream_result else None,
            upstream_confidence=upstream_result.confidence if upstream_result else None,
            upstream_method=upstream_result.method if upstream_result else None,
        )

    def _try_fips_variant(self, result: MatchResult) -> MatchResult:
        """
        Try to find a FIPS variant of the matched Chainguard image.

        If prefer_fips is enabled and the matched image doesn't already have -fips,
        check if a -fips variant exists and use it instead.

        Args:
            result: The original match result

        Returns:
            Updated MatchResult with FIPS variant if available, otherwise original
        """
        if not result.chainguard_image:
            return result

        image = result.chainguard_image

        # Already a FIPS image - no change needed
        if "-fips:" in image or "-fips@" in image or image.endswith("-fips"):
            return result

        # Construct the FIPS variant
        # e.g., cgr.dev/chainguard-private/calico-typha:latest → cgr.dev/chainguard-private/calico-typha-fips:latest
        if ":" in image:
            base, tag = image.rsplit(":", 1)
            fips_image = f"{base}-fips:{tag}"
        elif "@" in image:
            base, digest = image.rsplit("@", 1)
            fips_image = f"{base}-fips@{digest}"
        else:
            fips_image = f"{image}-fips"

        # Check if FIPS variant exists
        if self.image_verifier.verify_image_exists(fips_image):
            logger.info(f"FIPS variant found: {image} → {fips_image}")
            result.chainguard_image = fips_image
        else:
            logger.debug(f"No FIPS variant found for {image}")

        return result

    def _apply_version_matching(
        self,
        result: MatchResult,
        source_image: str,
    ) -> MatchResult:
        """
        Apply version matching to resolve the best tag for the matched image.

        Uses the VersionMatcher to find the appropriate version tag based on:
        - Latest patch for the source major.minor
        - EOL fallback if version is stale
        - Freshness checks via image build dates

        Args:
            result: The match result with chainguard_image set
            source_image: The original source image reference

        Returns:
            Updated MatchResult with resolved version tag
        """
        if not result.chainguard_image or not self.version_matcher:
            return result

        # Extract base image (without tag)
        chainguard_image = result.chainguard_image
        if ":" in chainguard_image:
            chainguard_base = chainguard_image.rsplit(":", 1)[0]
        elif "@" in chainguard_image:
            chainguard_base = chainguard_image.rsplit("@", 1)[0]
        else:
            chainguard_base = chainguard_image

        # Resolve version
        version_result = self.version_matcher.resolve(source_image, chainguard_base)

        # Update the chainguard image with resolved tag
        result.chainguard_image = f"{chainguard_base}:{version_result.resolved_tag}"

        # Add EOL fallback note to reasoning if applicable
        if version_result.is_eol_fallback:
            eol_note = " (EOL fallback: source version unavailable or stale)"
            if result.reasoning:
                result.reasoning += eol_note
            else:
                result.reasoning = f"Version resolved{eol_note}"

        logger.debug(
            f"Version matching: {source_image} → {result.chainguard_image} "
            f"(eol_fallback={version_result.is_eol_fallback})"
        )

        return result

    def _apply_latest_tag(self, result: MatchResult) -> MatchResult:
        """
        Apply :latest tag to matched image if no tag is present.

        This is used when version matching is disabled (--always-match-cgr-latest).

        Args:
            result: The match result with chainguard_image set

        Returns:
            Updated MatchResult with :latest tag appended if needed
        """
        if not result.chainguard_image:
            return result

        image = result.chainguard_image

        # Already has a tag or digest - don't modify
        if ":" in image or "@" in image:
            return result

        # Append :latest
        result.chainguard_image = f"{image}:latest"
        return result
