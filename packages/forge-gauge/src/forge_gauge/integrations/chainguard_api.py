"""
Chainguard API client for historical vulnerability data.

Provides access to Chainguard's vulnerability tracking API for
historical CVE trends and projections. Uses connection pooling and
token caching for efficient batch operations.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import requests

from forge_gauge.constants import CHAINGUARD_API_URL
from forge_gauge.core.exceptions import IntegrationException
from forge_gauge.utils.chainctl_auth import get_chainctl_token, verify_chainctl_installed

logger = logging.getLogger(__name__)

# Module-level shared instance for connection reuse
_shared_instance: Optional["ChainguardAPI"] = None

# Retry configuration for rate limiting
MAX_RETRIES = 3
BASE_RETRY_DELAY = 1.0  # seconds


def get_shared_client() -> "ChainguardAPI":
    """Get or create a shared ChainguardAPI instance for connection reuse."""
    global _shared_instance
    if _shared_instance is None:
        _shared_instance = ChainguardAPI()
    return _shared_instance


class ChainguardAPI:
    """
    Client for Chainguard's vulnerability API.

    Requires authentication via chainctl (Chainguard CLI tool).
    Uses a requests Session for connection pooling and caches auth tokens.
    """

    def __init__(self):
        """Initialize Chainguard API client with connection pooling."""
        self._session = requests.Session()
        self._verify_chainctl()

    def _verify_chainctl(self) -> None:
        """Verify chainctl is available and authenticated."""
        if not verify_chainctl_installed():
            raise RuntimeError(
                "chainctl is required for Chainguard API access but not found in PATH"
            )

        token = get_chainctl_token(timeout=10)
        if not token:
            raise RuntimeError("chainctl authentication failed")

        logger.debug("chainctl authentication verified")

    def _get_auth_token(self) -> str:
        """Get auth token, using cached value if available."""
        token = get_chainctl_token(timeout=10)
        if not token:
            raise IntegrationException("chainctl", "Failed to get auth token")
        return token

    def get_vulnerability_counts(
        self,
        repo: str,
        tag: str,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> dict:
        """
        Get historical vulnerability counts for an image.

        Args:
            repo: Repository name (e.g., "python")
            tag: Image tag (e.g., "latest")
            from_date: Start date (ISO format, e.g., "2024-01-01T00:00:00Z")
            to_date: End date (ISO format)

        Returns:
            API response with historical vulnerability data
        """
        if not from_date:
            from_date = "2024-01-01T00:00:00Z"

        if not to_date:
            to_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        token = self._get_auth_token()

        for attempt in range(MAX_RETRIES + 1):
            try:
                # Use session for connection pooling
                response = self._session.get(
                    f"{CHAINGUARD_API_URL}/registry/v1/vuln_reports/counts",
                    headers={
                        "Authorization": f"Bearer {token}",
                    },
                    params={
                        "repo": repo,
                        "tag": tag,
                        "from": from_date,
                        "to": to_date,
                    },
                    timeout=30,
                )
                response.raise_for_status()

                return response.json()

            except requests.Timeout:
                logger.warning(f"Timeout fetching vulnerability data for {repo}:{tag}")
                return {"items": []}
            except requests.HTTPError as e:
                # Handle rate limiting with exponential backoff
                if e.response.status_code == 429:
                    if attempt < MAX_RETRIES:
                        # Use Retry-After header if provided, otherwise exponential backoff
                        retry_after = e.response.headers.get("Retry-After")
                        if retry_after:
                            delay = float(retry_after)
                        else:
                            delay = BASE_RETRY_DELAY * (2 ** attempt)
                        logger.debug(
                            f"Rate limited for {repo}:{tag}, retrying in {delay:.1f}s (attempt {attempt + 1}/{MAX_RETRIES})"
                        )
                        time.sleep(delay)
                        continue
                    else:
                        logger.warning(
                            f"Rate limit exceeded for {repo}:{tag} after {MAX_RETRIES} retries"
                        )
                        return {"items": []}
                # Check if it's a 403 - likely no data available for this image
                elif e.response.status_code == 403:
                    logger.debug(
                        f"No vulnerability data available for {repo}:{tag} (API returned 403 - image may not be tracked)"
                    )
                else:
                    logger.warning(
                        f"HTTP error fetching vulnerability data for {repo}:{tag}: {e}"
                    )
                return {"items": []}
            except requests.RequestException as e:
                logger.warning(
                    f"Failed to fetch vulnerability data for {repo}:{tag}: {e}"
                )
                return {"items": []}
            except Exception as e:
                logger.warning(
                    f"Unexpected error fetching vulnerability data for {repo}:{tag}: {e}"
                )
                return {"items": []}

        # Should not reach here, but return empty if all retries exhausted without explicit return
        return {"items": []}

    def calculate_cve_growth_rate(
        self, repo: str, tag: str
    ) -> Optional[dict[str, float]]:
        """
        Calculate monthly CVE growth rate for an image.

        Args:
            repo: Repository name
            tag: Image tag

        Returns:
            Dictionary of severity -> monthly growth ratio, or None if data unavailable
        """
        data = self.get_vulnerability_counts(repo, tag)

        if not data.get("items"):
            return None

        items = data["items"]

        # Get starting point
        severity_counts = {
            "CRITICAL": 0,
            "HIGH": 0,
            "MEDIUM": 0,
            "LOW": 0,
            "UNKNOWN": 0,
        }

        for count in items[0].get("vulnCounts", []):
            severity = count.get("severity")
            if severity in severity_counts:
                severity_counts[severity] = count.get("count", 0)

        # Track changes over time
        changes = {sev: 0.0 for sev in severity_counts.keys()}

        prev_counts = severity_counts.copy()
        for item in items:
            for count in item.get("vulnCounts", []):
                severity = count.get("severity")
                if severity in changes:
                    current = count.get("count", 0)
                    changes[severity] += abs(current - prev_counts[severity])
                    prev_counts[severity] = current

        # Calculate average daily change, then convert to monthly ratio
        num_days = len(items)
        if num_days == 0:
            return None

        ratios = {}
        for severity, total_change in changes.items():
            avg_daily_change = total_change / num_days
            monthly_change = avg_daily_change * 30

            # Convert to ratio of current count
            current_count = prev_counts[severity]
            if current_count > 0:
                ratios[severity] = monthly_change / current_count
            else:
                ratios[severity] = 0.0

        return ratios
