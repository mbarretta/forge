"""
Scanner plugin interface for vulnerability providers.

Defines the contract for vulnerability scanning providers, enabling
easy integration of different scanners (Grype, Trivy, Snyk, etc.).
"""

from abc import ABC, abstractmethod
from typing import Optional

from forge_gauge.core.models import VulnerabilityCount


class VulnerabilityProvider(ABC):
    """
    Abstract base class for vulnerability data providers.

    All vulnerability scanners must implement this interface to be
    used with the Gauge scanning framework.
    """

    @abstractmethod
    def name(self) -> str:
        """
        Return the provider name.

        Returns:
            Provider identifier (e.g., "grype", "trivy", "snyk")
        """
        ...

    @abstractmethod
    def scan(self, image: str, sbom_json: str) -> VulnerabilityCount:
        """
        Scan for vulnerabilities using an SBOM.

        Args:
            image: Image reference being scanned (for logging)
            sbom_json: SBOM data in JSON format (from Syft)

        Returns:
            VulnerabilityCount with severity breakdown

        Raises:
            ScanException: If scan fails
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if this provider is available/installed.

        Returns:
            True if provider can be used, False otherwise
        """
        ...

    def version(self) -> Optional[str]:
        """
        Get provider version (optional).

        Returns:
            Version string if available, None otherwise
        """
        return None


class SBOMProvider(ABC):
    """
    Abstract base class for SBOM (Software Bill of Materials) providers.

    Provides an SBOM generation interface separate from vulnerability
    scanning, allowing different SBOM generators to be plugged in.
    """

    @abstractmethod
    def name(self) -> str:
        """
        Return the provider name.

        Returns:
            Provider identifier (e.g., "syft", "trivy-sbom")
        """
        ...

    @abstractmethod
    def generate_sbom(self, image: str) -> tuple[int, str]:
        """
        Generate SBOM for an image.

        Args:
            image: Image reference to scan

        Returns:
            Tuple of (package_count, sbom_json_string)

        Raises:
            ScanException: If SBOM generation fails
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if this provider is available/installed.

        Returns:
            True if provider can be used, False otherwise
        """
        ...


__all__ = [
    "VulnerabilityProvider",
    "SBOMProvider",
]
