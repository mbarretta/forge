"""
Upstream image discovery for finding public equivalents of private/internal images.

This module helps convert private or internal image names to their public upstream
equivalents before matching to Chainguard images.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from forge_gauge.utils.docker_utils import image_exists_in_registry
from forge_gauge.utils.image_utils import ImageReference
from forge_gauge.utils.llm_utils import load_yaml_mappings
from forge_gauge.utils.paths import get_config_path

logger = logging.getLogger(__name__)

# Functional suffixes that indicate derivative tools, not the base image itself.
# When an image name follows the pattern <base>-<suffix>, we skip matching to <base>.
# For example: "node-exporter" should NOT match "node" (Node.js).
TOOL_SUFFIXES = {
    "exporter",    # Prometheus exporters (node-exporter, redis-exporter)
    "operator",    # Kubernetes operators
    "controller",  # Controllers
    "agent",       # Agents
    "proxy",       # Proxies
    "gateway",     # Gateways
    "client",      # Client libraries
    "driver",      # CSI drivers, device drivers
    "registrar",   # CSI node-driver-registrar
}

# Ambiguous base names that can mean different things depending on context.
# These require stricter matching - only match if the name IS the base or STARTS with base-.
# "node" is particularly problematic: Node.js vs Kubernetes/infrastructure node
AMBIGUOUS_BASES = {"node"}

# Per-strategy confidence thresholds.
# Strategies that are more error-prone require higher confidence to be accepted.
STRATEGY_THRESHOLDS = {
    "manual": 0.0,           # Manual mappings are always trusted
    "registry_strip": 0.7,   # Registry stripping is fairly reliable
    "common_registry": 0.7,  # Common registry lookup is reliable (verified)
    "base_extract": 0.85,    # Base extraction is heuristic and error-prone - require high confidence
}


@dataclass
class UpstreamResult:
    """Result of upstream image discovery."""

    upstream_image: Optional[str]
    """Discovered upstream image reference"""

    confidence: float
    """Confidence score (0.0 - 1.0)"""

    method: str
    """Discovery method used (manual, registry_strip, common_registry, base_extract, none)"""


class UpstreamImageFinder:
    """
    Discovers public upstream equivalents for private/internal images.

    Uses a 4-strategy approach with per-strategy confidence thresholds:
    1. Manual Mappings (100% confidence, threshold: 0%) - Explicit overrides
    2. Registry Strip (90% confidence, threshold: 70%) - Remove private registry prefix
    3. Common Registries (80% confidence, threshold: 70%) - Check docker.io, quay.io, ghcr.io
    4. Base Name Extract (70% confidence, threshold: 85%) - Extract base image from internal names
       Note: This strategy requires higher confidence than it provides by default,
       effectively disabling it unless confidence is boosted. This is intentional
       because heuristic name extraction is error-prone (e.g., matching "node"
       from "csi-node-driver-registrar" to Node.js).
    """

    # Common public registries to check
    COMMON_REGISTRIES = [
        "docker.io/library",
        "docker.io",
        "quay.io",
        "ghcr.io",
        "gcr.io",
    ]

    # Known private registry patterns
    PRIVATE_REGISTRY_PATTERNS = [
        r"^[a-z0-9.-]+\.(io|com|net|org|dev)/",  # company.io/image, multi-level domains
        r"^gcr\.io/[a-z0-9-]+/",  # gcr.io/project/image
        r"^[a-z0-9-]+\.gcr\.io/",  # project.gcr.io/image
        r"^[0-9]+\.dkr\.ecr\.",  # AWS ECR
        r"^.*\.azurecr\.io/",  # Azure ACR
    ]

    def __init__(
        self,
        manual_mappings_file: Optional[Path] = None,
        min_confidence: float = 0.7,
    ):
        """
        Initialize upstream image finder.

        Args:
            manual_mappings_file: Optional manual upstream mappings file
            min_confidence: Minimum confidence threshold (0.0 - 1.0)
        """
        self.manual_mappings_file = manual_mappings_file or get_config_path("upstream_mappings.yaml")
        self.min_confidence = min_confidence
        self.manual_mappings: dict[str, str] = {}

        # Load manual mappings if available
        self._load_manual_mappings()

    def find_upstream(self, alternative_image: str) -> UpstreamResult:
        """
        Find public upstream equivalent for alternative image.

        This is called as a FALLBACK when the source registry is not accessible.
        For accessible registries (public, Iron Bank with creds, etc.), this
        method is not called - the image is matched directly.

        Tries strategies in order of confidence:
        1. Manual mappings
        2. Registry strip
        3. Common registries
        4. Base name extraction

        Args:
            alternative_image: Alternative/internal image reference

        Returns:
            UpstreamResult with discovered image and metadata
        """
        # Strategy 1: Check manual mappings (100% confidence)
        if alternative_image in self.manual_mappings:
            upstream = self.manual_mappings[alternative_image]
            logger.debug(f"Manual mapping found for {alternative_image}: {upstream}")
            return UpstreamResult(
                upstream_image=upstream,
                confidence=1.0,
                method="manual"
            )

        # Strategy 2: Strip private registry prefix (90% confidence)
        stripped_result = self._try_strip_registry(alternative_image)
        if stripped_result and self._passes_threshold(stripped_result):
            return stripped_result

        # Strategy 3: Check common registries (80% confidence)
        registry_result = self._try_common_registries(alternative_image)
        if registry_result and self._passes_threshold(registry_result):
            return registry_result

        # Strategy 4: Extract base image name (70% confidence)
        # Note: This strategy has a higher per-strategy threshold (0.85) because
        # heuristic name extraction is error-prone and often produces false positives.
        base_result = self._try_base_extraction(alternative_image)
        if base_result and self._passes_threshold(base_result):
            return base_result

        # No upstream found
        logger.debug(f"No upstream found for {alternative_image}")
        return UpstreamResult(
            upstream_image=None,
            confidence=0.0,
            method="none"
        )

    def _passes_threshold(self, result: UpstreamResult) -> bool:
        """
        Check if a result passes both global and per-strategy confidence thresholds.

        Args:
            result: UpstreamResult to check

        Returns:
            True if result passes all thresholds, False otherwise
        """
        # Must pass global minimum confidence
        if result.confidence < self.min_confidence:
            return False

        # Must pass per-strategy threshold (if defined)
        strategy_threshold = STRATEGY_THRESHOLDS.get(result.method, 0.0)
        if result.confidence < strategy_threshold:
            logger.debug(
                f"Result filtered by per-strategy threshold: {result.method} "
                f"confidence {result.confidence:.0%} < required {strategy_threshold:.0%}"
            )
            return False

        return True

    def _load_manual_mappings(self) -> None:
        """Load manual upstream mappings from YAML file."""
        data = load_yaml_mappings(self.manual_mappings_file, "manual upstream mappings")
        if data:
            self.manual_mappings = data

    def _try_strip_registry(self, image: str) -> Optional[UpstreamResult]:
        """
        Try stripping private registry prefix.

        Examples:
            mycompany.io/python:3.12 → python:3.12
            gcr.io/myproject/nginx:latest → nginx:latest
            artifactory.com/jenkins/jenkins:2.426 → jenkins/jenkins:2.426

        Args:
            image: Image reference

        Returns:
            UpstreamResult if successful, None otherwise
        """
        # Check if image matches private registry pattern
        is_private = any(re.match(pattern, image) for pattern in self.PRIVATE_REGISTRY_PATTERNS)

        if not is_private:
            return None

        # Extract image name after registry (preserve path structure)
        parts = image.split("/")
        if len(parts) < 2:
            return None

        # Strip registry (first part), keep the rest of the path
        # Example: docker.artifactory.com/jenkins/jenkins:tag → jenkins/jenkins:tag
        stripped_image = "/".join(parts[1:])

        # Extract just the image name (last part) for fallback attempts
        image_name_only = parts[-1]

        # Try multiple variations in order of likelihood:

        # 1. Try with full path preserved (for multi-part names like jenkins/jenkins)
        candidate = f"docker.io/{stripped_image}"
        if self._verify_upstream_exists(candidate):
            logger.debug(f"Registry strip successful: {image} → {stripped_image}")
            return UpstreamResult(
                upstream_image=stripped_image,
                confidence=0.90,
                method="registry_strip"
            )

        # 2. Try with library/ prefix if it's a single-part name
        if "/" not in stripped_image.split(":")[0]:  # Check base name has no /
            candidate = f"docker.io/library/{stripped_image}"
            if self._verify_upstream_exists(candidate):
                logger.debug(f"Registry strip successful: {image} → {stripped_image}")
                return UpstreamResult(
                    upstream_image=stripped_image,
                    confidence=0.90,
                    method="registry_strip"
                )

        # 3. Try just the image name (last part) with docker.io
        # Handles cases like eks/coredns → coredns or jenkins/exporter → exporter
        if stripped_image != image_name_only:  # Only if they're different
            candidate = f"docker.io/{image_name_only}"
            if self._verify_upstream_exists(candidate):
                logger.debug(f"Registry strip successful: {image} → {image_name_only}")
                return UpstreamResult(
                    upstream_image=image_name_only,
                    confidence=0.85,
                    method="registry_strip"
                )

            # Try with library/ prefix for single-part
            candidate = f"docker.io/library/{image_name_only}"
            if self._verify_upstream_exists(candidate):
                logger.debug(f"Registry strip successful: {image} → {image_name_only}")
                return UpstreamResult(
                    upstream_image=image_name_only,
                    confidence=0.85,
                    method="registry_strip"
                )

        # 4. If verification fails, return the full stripped path (best guess)
        # This allows pull fallback to attempt it even if we can't verify existence
        logger.debug(
            f"Registry strip (unverified): {image} → {stripped_image} "
            f"(will attempt during pull fallback)"
        )
        return UpstreamResult(
            upstream_image=stripped_image,
            confidence=0.70,  # Lower confidence since unverified
            method="registry_strip_unverified"
        )

    def _try_common_registries(self, image: str) -> Optional[UpstreamResult]:
        """
        Try finding image in common public registries.

        Checks docker.io, quay.io, ghcr.io, gcr.io in order.
        For each registry, tries the full path first (org/image), then base name only.

        Args:
            image: Image reference

        Returns:
            UpstreamResult if successful, None otherwise
        """
        # Extract base name without registry/tag
        base_name = self._extract_base_name(image)

        # Extract full path (preserving org/image structure) without registry/tag
        full_path = self._extract_full_path(image)

        # Try each common registry
        for registry in self.COMMON_REGISTRIES:
            # First try with full path preserved (e.g., gcr.io/kaniko-project/executor)
            # This handles cases like kaniko-project/executor → gcr.io/kaniko-project/executor
            if full_path and full_path != base_name:
                candidate = f"{registry}/{full_path}"
                if self._verify_upstream_exists(candidate):
                    logger.debug(f"Found in common registry (full path): {candidate}")
                    return UpstreamResult(
                        upstream_image=candidate,
                        confidence=0.80,
                        method="common_registry"
                    )

            # Then try with just the base name (e.g., docker.io/nginx)
            candidate = f"{registry}/{base_name}"
            if self._verify_upstream_exists(candidate):
                logger.debug(f"Found in common registry: {candidate}")
                return UpstreamResult(
                    upstream_image=candidate,
                    confidence=0.80,
                    method="common_registry"
                )

        return None

    def _extract_full_path(self, image: str) -> str:
        """
        Extract full image path preserving org/image structure but removing registry.

        Examples:
            kaniko-project/executor:v1.0 → kaniko-project/executor
            gcr.io/kaniko-project/executor → kaniko-project/executor
            nginx:latest → nginx
            docker.io/library/nginx → nginx

        Args:
            image: Image reference

        Returns:
            Full image path without registry or tag
        """
        ref = ImageReference.parse(image)
        # Get org/name format, but skip "library" org for Docker Hub images
        if ref.organization and ref.organization != "library":
            return f"{ref.organization}/{ref.name}".lower()
        return ref.name.lower()

    def _try_base_extraction(self, image: str) -> Optional[UpstreamResult]:
        """
        Try extracting base image name from internal naming patterns.

        Examples:
            internal-python-app:v1 → python:latest
            company-nginx-prod:latest → nginx:latest
            my-postgres-db → postgres:latest

        Args:
            image: Image reference

        Returns:
            UpstreamResult if successful, None otherwise
        """
        # Common base images to look for
        common_bases = [
            "python", "node", "nginx", "postgres", "postgresql", "mysql", "mariadb",
            "redis", "mongo", "mongodb", "golang", "go", "java", "openjdk",
            "ruby", "php", "perl", "alpine", "ubuntu", "debian", "centos",
            "httpd", "apache", "tomcat", "rabbitmq", "kafka", "elasticsearch",
        ]

        # Extract base name and check if it contains common base image names
        base_name = self._extract_base_name(image).lower()

        for base in common_bases:
            # Skip if name follows pattern: <base>-<tool-suffix>
            # e.g., "node-exporter" starts with "node-" and ends with tool suffix
            # This prevents matching derivative tools to their base images
            if base_name.startswith(f"{base}-"):
                suffix = base_name[len(base) + 1:]  # Get part after "base-"
                # Check if suffix matches or starts with any known tool suffix
                if any(suffix == tool or suffix.startswith(f"{tool}-") for tool in TOOL_SUFFIXES):
                    continue  # Skip - this is a tool FOR base, not base itself

            # For ambiguous bases (e.g., "node"), require exact match or start-of-name match.
            # This prevents "csi-node-driver-registrar" from matching "node" (Node.js).
            if base in AMBIGUOUS_BASES:
                # Only match if base IS the name or STARTS the name
                if base_name != base and not base_name.startswith(f"{base}-"):
                    continue  # Skip - ambiguous base in middle of name

            if base in base_name:
                # Try with latest tag
                candidate = f"docker.io/library/{base}:latest"
                if self._verify_upstream_exists(candidate):
                    logger.debug(f"Base extraction successful: {image} → {base}:latest")
                    return UpstreamResult(
                        upstream_image=f"{base}:latest",
                        confidence=0.70,
                        method="base_extract"
                    )

                # Try without library prefix
                candidate = f"docker.io/{base}:latest"
                if self._verify_upstream_exists(candidate):
                    logger.debug(f"Base extraction successful: {image} → {base}:latest")
                    return UpstreamResult(
                        upstream_image=f"{base}:latest",
                        confidence=0.70,
                        method="base_extract"
                    )

        return None

    def _extract_base_name(self, image: str) -> str:
        """
        Extract base image name from full reference.

        Examples:
            mycompany.io/python:3.12 → python
            internal-python-app:v1 → internal-python-app
            gcr.io/project/nginx → nginx

        Args:
            image: Image reference

        Returns:
            Base image name
        """
        ref = ImageReference.parse(image)
        return ref.base_name()

    def _verify_upstream_exists(self, image: str) -> bool:
        """
        Verify upstream image exists in registry.

        Uses docker/podman manifest inspect for verification.

        Args:
            image: Full image reference with registry

        Returns:
            True if image exists, False otherwise
        """
        try:
            return image_exists_in_registry(image)
        except Exception as e:
            logger.debug(f"Failed to verify upstream {image}: {e}")
            return False
