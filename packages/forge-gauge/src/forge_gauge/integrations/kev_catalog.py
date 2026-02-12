"""
CISA Known Exploited Vulnerabilities (KEV) Catalog integration.

Fetches and checks CVEs against CISA's official KEV catalog.
"""

import logging
from typing import Optional

import requests

from forge_gauge.constants import KEV_CATALOG_URL
from forge_gauge.core.models import KEVEntry

logger = logging.getLogger(__name__)


class KEVCatalog:
    """
    Client for CISA's Known Exploited Vulnerabilities catalog.

    Provides methods to fetch the KEV catalog and check if specific
    CVEs are known to be exploited in the wild.
    """

    def __init__(self):
        """Initialize KEV catalog."""
        self.vulnerabilities: list[KEVEntry] = []
        self.cve_ids: set[str] = set()
        self._entries_by_id: dict[str, KEVEntry] = {}
        self.loaded = False

    def load(self) -> bool:
        """
        Fetch KEV catalog from CISA.

        Returns:
            True if loaded successfully, False otherwise
        """
        try:
            logger.info("Fetching KEV catalog from CISA...")
            response = requests.get(
                KEV_CATALOG_URL,
                timeout=30,
            )
            response.raise_for_status()

            data = response.json()

            # Parse KEV entries
            for vuln in data.get("vulnerabilities", []):
                entry = KEVEntry(
                    cve_id=vuln.get("cveID", ""),
                    vendor=vuln.get("vendorProject", ""),
                    product=vuln.get("product", ""),
                    vulnerability_name=vuln.get("vulnerabilityName", ""),
                    date_added=vuln.get("dateAdded", ""),
                )
                self.vulnerabilities.append(entry)
                self.cve_ids.add(entry.cve_id)
                self._entries_by_id[entry.cve_id] = entry

            self.loaded = True
            logger.info(f"Loaded {len(self.vulnerabilities)} KEV entries")
            return True

        except requests.Timeout:
            logger.warning("Timeout loading KEV data")
            return False
        except requests.RequestException as e:
            logger.warning(f"Failed to load KEV data: {e}")
            return False
        except Exception as e:
            logger.warning(f"Unexpected error loading KEV data: {e}")
            return False

    def is_kev(self, cve_id: str) -> bool:
        """
        Check if a CVE is in the KEV catalog.

        Args:
            cve_id: CVE identifier (e.g., "CVE-2021-44228")

        Returns:
            True if CVE is a known exploited vulnerability
        """
        return cve_id in self.cve_ids

    def get_kev_entry(self, cve_id: str) -> Optional[KEVEntry]:
        """
        Get KEV catalog entry for a CVE.

        Args:
            cve_id: CVE identifier

        Returns:
            KEVEntry if found, None otherwise
        """
        return self._entries_by_id.get(cve_id)

    def check_image_for_kevs(
        self, image_name: str, cve_ids: list[str]
    ) -> list[str]:
        """
        Check which CVEs from an image are KEVs.

        Args:
            image_name: Image being checked
            cve_ids: List of CVE IDs from the image

        Returns:
            List of CVE IDs that are KEVs
        """
        if not self.loaded:
            return []

        kevs_found = []
        for cve_id in cve_ids:
            if self.is_kev(cve_id):
                logger.info(f"KEV found in {image_name}: {cve_id}")
                kevs_found.append(cve_id)

        return kevs_found
