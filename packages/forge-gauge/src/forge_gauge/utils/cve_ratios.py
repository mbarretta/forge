"""
CVE growth rate calculation with dynamic API fetching and static fallback.

Provides intelligent CVE monthly growth ratios by attempting to fetch real-time
data from the Chainguard API, falling back to historical static constants when
the API is unavailable or fails. Supports parallel batch fetching for efficiency.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from forge_gauge.constants import CVE_MONTHLY_RATIOS

logger = logging.getLogger(__name__)

# Module-level cache for API results to avoid repeated calls
_ratios_cache: dict[str, dict[str, float]] = {}

# Shared API client instance for connection reuse across parallel calls
_shared_api_client = None


def get_cve_monthly_ratios(
    image_name: Optional[str] = None,
    chainguard_image_name: Optional[str] = None,
    use_api: bool = True,
) -> dict[str, float]:
    """
    Get CVE monthly growth ratios with API fallback.

    This function attempts to fetch dynamic CVE growth rates from the Chainguard API
    for the corresponding Chainguard image, using that data as a proxy for estimating
    CVE growth in the alternative image. If the API call fails or returns no data,
    it falls back to historical static constants defined in constants.py.

    Args:
        image_name: Full alternative image reference (e.g., "python:3.12"). Used for logging.
        chainguard_image_name: Corresponding Chainguard image (e.g., "cgr.dev/chainguard/python:latest").
                              If provided, API will query this image's historical CVE data.
        use_api: Whether to attempt API call. Set to False to skip API and use static ratios.

    Returns:
        Dictionary mapping severity level to monthly growth ratio.
        Keys: "CRITICAL", "HIGH", "MEDIUM", "LOW", "NEGLIGIBLE"

    Example:
        >>> ratios = get_cve_monthly_ratios("python:3.12", "cgr.dev/chainguard/python:latest")
        >>> monthly_new_critical = current_critical_count * ratios["CRITICAL"]
    """
    # If API disabled or no chainguard image specified, use static fallback
    if not use_api or not chainguard_image_name:
        logger.debug("Using static CVE monthly ratios (fallback)")
        return CVE_MONTHLY_RATIOS

    # Try to fetch dynamic ratios from API using Chainguard image data
    try:
        from forge_gauge.integrations.chainguard_api import get_shared_client

        # Parse Chainguard image name to extract repo and tag
        repo, tag = _parse_image_name(chainguard_image_name)
        if not repo or not tag:
            logger.debug(f"Could not parse Chainguard image name: {chainguard_image_name}, using static ratios")
            return CVE_MONTHLY_RATIOS

        # Check cache first (keyed by repo:tag)
        cache_key = f"{repo}:{tag}"
        if cache_key in _ratios_cache:
            logger.debug(f"Using cached CVE ratios for {cache_key}")
            return _ratios_cache[cache_key]

        # Use shared API client for connection reuse
        api = get_shared_client()

        # Fetch dynamic growth rates from Chainguard image
        dynamic_ratios = api.calculate_cve_growth_rate(repo, tag)

        if dynamic_ratios:
            image_desc = f"{image_name} (using {repo}:{tag} data)" if image_name else f"{repo}:{tag}"
            logger.info(f"Using dynamic CVE growth rates for {image_desc}")
            # Normalize the keys to match our expected format
            normalized = {
                "CRITICAL": dynamic_ratios.get("CRITICAL", CVE_MONTHLY_RATIOS["CRITICAL"]),
                "HIGH": dynamic_ratios.get("HIGH", CVE_MONTHLY_RATIOS["HIGH"]),
                "MEDIUM": dynamic_ratios.get("MEDIUM", CVE_MONTHLY_RATIOS["MEDIUM"]),
                "LOW": dynamic_ratios.get("LOW", CVE_MONTHLY_RATIOS["LOW"]),
                "NEGLIGIBLE": dynamic_ratios.get("UNKNOWN", CVE_MONTHLY_RATIOS["NEGLIGIBLE"]),
            }
            # Cache the result
            _ratios_cache[cache_key] = normalized
            return normalized
        else:
            image_desc = f"{image_name} ({repo}:{tag})" if image_name else f"{repo}:{tag}"
            logger.debug(f"No dynamic data available for {image_desc}, using static ratios")
            # Cache the fallback to avoid repeated failed API calls
            _ratios_cache[cache_key] = CVE_MONTHLY_RATIOS
            return CVE_MONTHLY_RATIOS

    except RuntimeError as e:
        # chainctl not available or not authenticated
        logger.debug(f"Cannot use Chainguard API: {e}")
        return CVE_MONTHLY_RATIOS
    except Exception as e:
        # Any other error - log and fall back
        logger.warning(f"Error fetching dynamic CVE ratios: {e}, using static fallback")
        return CVE_MONTHLY_RATIOS


def _parse_image_name(image_name: str) -> tuple[Optional[str], Optional[str]]:
    """
    Parse image name into repo and tag components.

    Args:
        image_name: Full image reference (e.g., "python:3.12" or "registry.io/repo/python:3.12")

    Returns:
        Tuple of (repo, tag). Returns (None, None) if parsing fails.

    Examples:
        >>> _parse_image_name("python:3.12")
        ("python", "3.12")
        >>> _parse_image_name("cgr.dev/chainguard/python:latest")
        ("python", "latest")
        >>> _parse_image_name("docker.io/library/nginx:1.25")
        ("nginx", "1.25")
    """
    try:
        # Handle case with no tag
        if ":" not in image_name:
            return None, None

        # Split on last colon to get tag
        parts = image_name.rsplit(":", 1)
        repo_path = parts[0]
        tag = parts[1]

        # Extract just the repo name (last component of path)
        # e.g., "cgr.dev/chainguard/python" -> "python"
        repo = repo_path.split("/")[-1]

        return repo, tag

    except (IndexError, AttributeError):
        return None, None


def prefetch_cve_ratios_batch(
    image_pairs: list[tuple[str, str]],
    max_workers: int = 2,
) -> dict[str, dict[str, float]]:
    """
    Prefetch CVE ratios for multiple images in parallel.

    This function fetches CVE growth ratios for all provided image pairs
    concurrently, populating the module-level cache. Subsequent calls to
    get_cve_monthly_ratios() will use the cached values.

    Args:
        image_pairs: List of (alternative_image_name, chainguard_image_name) tuples
        max_workers: Maximum number of parallel API calls

    Returns:
        Dictionary mapping chainguard_image_name to its CVE ratios
    """
    # Filter to unique chainguard images that need fetching
    unique_cg_images = set()
    for _, cg_image in image_pairs:
        if cg_image:
            repo, tag = _parse_image_name(cg_image)
            if repo and tag:
                cache_key = f"{repo}:{tag}"
                if cache_key not in _ratios_cache:
                    unique_cg_images.add(cg_image)

    if not unique_cg_images:
        logger.debug("All CVE ratios already cached, skipping prefetch")
        return {}

    logger.info(f"Prefetching CVE ratios for {len(unique_cg_images)} images with {max_workers} workers")

    # Initialize shared API client once before parallel calls
    try:
        from forge_gauge.integrations.chainguard_api import get_shared_client
        api = get_shared_client()
    except RuntimeError as e:
        logger.debug(f"Cannot use Chainguard API for prefetch: {e}")
        return {}

    results = {}

    def fetch_single(cg_image: str) -> tuple[str, dict[str, float]]:
        """Fetch ratios for a single image."""
        repo, tag = _parse_image_name(cg_image)
        cache_key = f"{repo}:{tag}"

        try:
            dynamic_ratios = api.calculate_cve_growth_rate(repo, tag)

            if dynamic_ratios:
                normalized = {
                    "CRITICAL": dynamic_ratios.get("CRITICAL", CVE_MONTHLY_RATIOS["CRITICAL"]),
                    "HIGH": dynamic_ratios.get("HIGH", CVE_MONTHLY_RATIOS["HIGH"]),
                    "MEDIUM": dynamic_ratios.get("MEDIUM", CVE_MONTHLY_RATIOS["MEDIUM"]),
                    "LOW": dynamic_ratios.get("LOW", CVE_MONTHLY_RATIOS["LOW"]),
                    "NEGLIGIBLE": dynamic_ratios.get("UNKNOWN", CVE_MONTHLY_RATIOS["NEGLIGIBLE"]),
                }
                return cache_key, normalized
            else:
                logger.debug(f"No dynamic data available for {cg_image} ({cache_key}), using static ratios")
                return cache_key, CVE_MONTHLY_RATIOS
        except Exception as e:
            logger.warning(f"Error fetching CVE ratios for {cg_image}: {e}")
            return cache_key, CVE_MONTHLY_RATIOS

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_image = {
            executor.submit(fetch_single, cg_image): cg_image
            for cg_image in unique_cg_images
        }

        for future in as_completed(future_to_image):
            cg_image = future_to_image[future]
            try:
                cache_key, ratios = future.result()
                _ratios_cache[cache_key] = ratios
                results[cg_image] = ratios
            except Exception as e:
                logger.warning(f"Failed to prefetch CVE ratios for {cg_image}: {e}")

    logger.info(f"Prefetched CVE ratios for {len(results)} images")
    return results
