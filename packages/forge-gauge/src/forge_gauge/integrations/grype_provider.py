"""
Grype vulnerability scanner provider implementation.

Implements the VulnerabilityProvider interface for Anchore Grype scanner.
"""

import json
import logging
import subprocess
from typing import Optional

from forge_gauge.constants import GRYPE_TIMEOUT
from forge_gauge.core.exceptions import ScanException
from forge_gauge.core.models import SeverityLevel, VulnerabilityCount
from forge_gauge.core.scanner_interface import VulnerabilityProvider

logger = logging.getLogger(__name__)


class GrypeProvider(VulnerabilityProvider):
    """
    Grype vulnerability scanner provider.

    Uses Anchore Grype to scan SBOMs for vulnerabilities.
    """

    def name(self) -> str:
        """Return provider name."""
        return "grype"

    def is_available(self) -> bool:
        """Check if Grype is available."""
        try:
            result = subprocess.run(
                ["grype", "version"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def version(self) -> Optional[str]:
        """Get Grype version."""
        try:
            result = subprocess.run(
                ["grype", "version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                # Parse version from output
                lines = result.stdout.strip().split("\n")
                for line in lines:
                    if "Version:" in line or "version" in line.lower():
                        return line.strip()
                return lines[0] if lines else None
            return None
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            logger.debug(f"Failed to get Grype version: {e}")
            return None

    def scan(self, image: str, sbom_json: str) -> VulnerabilityCount:
        """
        Scan SBOM for vulnerabilities using Grype.

        Args:
            image: Image reference (for logging)
            sbom_json: SBOM in JSON format

        Returns:
            VulnerabilityCount with severity breakdown

        Raises:
            ScanException: If scan fails
        """
        try:
            result = subprocess.run(
                ["grype", "-o", "json"],
                input=sbom_json,
                capture_output=True,
                text=True,
                timeout=GRYPE_TIMEOUT,
                check=True,
            )

            grype_data = json.loads(result.stdout)
            return self._parse_grype_output(grype_data, image)

        except subprocess.CalledProcessError as e:
            raise ScanException(image, f"Grype scan failed: {e}")
        except subprocess.TimeoutExpired:
            raise ScanException(image, "Grype scan timed out")
        except json.JSONDecodeError as e:
            raise ScanException(image, f"Invalid Grype output: {e}")
        except Exception as e:
            raise ScanException(image, f"Unexpected error: {e}")

    def _parse_grype_output(
        self,
        grype_data: dict,
        image_name: str,
    ) -> VulnerabilityCount:
        """
        Parse Grype JSON output into VulnerabilityCount.

        Args:
            grype_data: Parsed Grype JSON output
            image_name: Image name for logging

        Returns:
            VulnerabilityCount with severity breakdown
        """
        counts = {
            SeverityLevel.CRITICAL.value: 0,
            SeverityLevel.HIGH.value: 0,
            SeverityLevel.MEDIUM.value: 0,
            SeverityLevel.LOW.value: 0,
            SeverityLevel.NEGLIGIBLE.value: 0,
        }

        matches = grype_data.get("matches", [])
        if not isinstance(matches, list):
            logger.warning(
                f"Unexpected grype matches format for {image_name}: {type(matches)}"
            )
            matches = []

        for match in matches:
            try:
                severity = match.get("vulnerability", {}).get("severity", "Unknown")
                if severity in counts:
                    counts[severity] += 1
                else:
                    # Unknown or unrecognized severities go into negligible
                    counts[SeverityLevel.NEGLIGIBLE.value] += 1
            except (KeyError, TypeError) as e:
                logger.warning(
                    f"Malformed match entry in {image_name}: {e}, skipping"
                )
                continue

        total = sum(counts.values())

        return VulnerabilityCount(
            total=total,
            critical=counts[SeverityLevel.CRITICAL.value],
            high=counts[SeverityLevel.HIGH.value],
            medium=counts[SeverityLevel.MEDIUM.value],
            low=counts[SeverityLevel.LOW.value],
            negligible=counts[SeverityLevel.NEGLIGIBLE.value],
        )


__all__ = ["GrypeProvider"]
