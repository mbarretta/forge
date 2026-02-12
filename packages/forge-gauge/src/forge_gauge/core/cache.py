"""
Intelligent caching system for scan results.

Uses digest-based caching to avoid re-scanning identical images.
Cache entries are stored as individual JSON files for easy inspection and management.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from forge_gauge.core.models import ImageAnalysis, VulnerabilityCount, CHPSScore

logger = logging.getLogger(__name__)


class ScanCache:
    """
    Digest-based cache for scan results.

    Each cache entry is stored as a separate JSON file, keyed by image digest.
    This approach provides:
    - Fast lookups without loading entire cache into memory
    - Easy cache inspection and debugging
    - Atomic writes to prevent corruption
    - Simple cache management (delete individual files)
    """

    def __init__(self, cache_dir: Path, enabled: bool = True):
        """
        Initialize scan cache.

        Args:
            cache_dir: Directory to store cache files
            enabled: Whether caching is enabled
        """
        self.cache_dir = cache_dir
        self.enabled = enabled
        self.hits = 0
        self.misses = 0

        if self.enabled:
            self._setup_cache_dir()

    def _setup_cache_dir(self) -> None:
        """Create cache directory if it doesn't exist."""
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Cache directory: {self.cache_dir}")
        except Exception as e:
            logger.warning(f"Failed to create cache directory: {e}")
            logger.info("Caching disabled for this session")
            self.enabled = False

    def _get_cache_path(self, cache_key: str) -> Path:
        """
        Get file path for a cache entry.

        Args:
            cache_key: Unique cache key (typically image digest)

        Returns:
            Path to cache file
        """
        # Sanitize key for filesystem
        safe_key = cache_key.replace("/", "_").replace(":", "_").replace("#", "_")
        return self.cache_dir / f"{safe_key}.json"

    def get(
        self,
        image_name: str,
        digest: Optional[str],
        require_chps: bool = False,
        require_kevs: bool = False
    ) -> Optional[ImageAnalysis]:
        """
        Retrieve cached scan result.

        Args:
            image_name: Image reference
            digest: Image digest (sha256)
            require_chps: If True, only return cached results that have CHPS scores.
                         If False, only return cached results that don't have CHPS scores.
            require_kevs: If True, only return cached results that have KEV data.
                         If False, only return cached results that don't have KEV data.

        Returns:
            Cached ImageAnalysis if available and exactly matches requirements, None otherwise
        """
        if not self.enabled or not digest:
            self.misses += 1
            return None

        cache_path = self._get_cache_path(digest)

        try:
            if not cache_path.exists():
                logger.debug(f"Cache miss for {image_name}")
                self.misses += 1
                return None

            with open(cache_path, "r") as f:
                data = json.load(f)

            # Validate digest matches
            if data.get("digest") != digest:
                logger.warning(f"Cache digest mismatch for {image_name}")
                self.misses += 1
                return None

            # Validate CHPS requirement matches exactly
            # Cache must match the current run configuration exactly:
            # - If CHPS is required, cached result must have CHPS
            # - If CHPS is not required, cached result must NOT have CHPS
            has_chps = data.get("chps_score") is not None
            if require_chps != has_chps:
                if require_chps:
                    logger.debug(
                        f"Cache miss for {image_name}: CHPS score required but cached result has none"
                    )
                else:
                    logger.debug(
                        f"Cache miss for {image_name}: CHPS score not required but cached result has it"
                    )
                self.misses += 1
                return None

            # Validate KEV requirement matches exactly
            # Cache must match the current run configuration exactly:
            # - If KEV is required, cached result must have KEV data
            # - If KEV is not required, cached result must NOT have KEV data
            has_kevs = data.get("kev_count", 0) > 0 or len(data.get("kev_cves", [])) > 0
            if require_kevs != has_kevs:
                if require_kevs:
                    logger.debug(
                        f"Cache miss for {image_name}: KEV data required but cached result has none"
                    )
                else:
                    logger.debug(
                        f"Cache miss for {image_name}: KEV data not required but cached result has it"
                    )
                self.misses += 1
                return None

            # Reconstruct ImageAnalysis from cached data
            vuln_data = data.get("vulnerabilities", {})

            # Reconstruct CHPS score if present
            chps_score = None
            if "chps_score" in data and data["chps_score"]:
                chps_data = data["chps_score"]
                chps_score = CHPSScore(
                    score=chps_data.get("score", 0.0),
                    grade=chps_data.get("grade", "F"),
                    details=chps_data.get("details", {}),
                )

            analysis = ImageAnalysis(
                name=image_name,
                size_mb=data.get("size_mb", 0.0),
                package_count=data.get("package_count", 0),
                vulnerabilities=VulnerabilityCount.from_dict(vuln_data),
                scan_timestamp=datetime.fromisoformat(data.get("timestamp", datetime.now(timezone.utc).isoformat())),
                digest=digest,
                cache_hit=True,
                chps_score=chps_score,
                used_latest_fallback=data.get("used_latest_fallback", False),
                original_image=data.get("original_image"),
                kev_count=data.get("kev_count", 0),
                kev_cves=data.get("kev_cves", []),
            )

            logger.debug(f"Cache hit for {image_name}")
            self.hits += 1
            return analysis

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"Corrupted cache entry for {image_name}: {e}")
            # Remove corrupted cache file
            try:
                cache_path.unlink()
            except OSError as unlink_error:
                logger.debug(f"Failed to remove corrupted cache file {cache_path}: {unlink_error}")
            self.misses += 1
            return None

        except Exception as e:
            logger.error(f"Unexpected error reading cache for {image_name}: {e}")
            self.misses += 1
            return None

    def put(self, analysis: ImageAnalysis) -> None:
        """
        Store scan result in cache.

        Args:
            analysis: ImageAnalysis to cache
        """
        if not self.enabled or not analysis.digest:
            return

        cache_path = self._get_cache_path(analysis.digest)

        try:
            # Prepare cache entry
            cache_entry = {
                "digest": analysis.digest,
                "image": analysis.name,
                "timestamp": analysis.scan_timestamp.isoformat(),
                "size_mb": analysis.size_mb,
                "package_count": analysis.package_count,
                "vulnerabilities": analysis.vulnerabilities.to_dict(),
                "used_latest_fallback": analysis.used_latest_fallback,
                "original_image": analysis.original_image,
            }

            # Add CHPS score if present
            if analysis.chps_score:
                cache_entry["chps_score"] = {
                    "score": analysis.chps_score.score,
                    "grade": analysis.chps_score.grade,
                    "details": analysis.chps_score.details,
                }

            # Add KEV data if present
            if analysis.kev_count > 0:
                cache_entry["kev_count"] = analysis.kev_count
                cache_entry["kev_cves"] = analysis.kev_cves

            # Atomic write: write to temp file, then rename
            temp_path = cache_path.with_suffix(".tmp")
            with open(temp_path, "w") as f:
                json.dump(cache_entry, f, indent=2)
                f.flush()
                os.fsync(f.fileno())

            temp_path.rename(cache_path)
            logger.debug(f"Cached scan result for {analysis.name}")

        except Exception as e:
            logger.error(f"Failed to cache scan result for {analysis.name}: {e}")
            # Clean up temp file if it exists
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError as unlink_error:
                    logger.debug(f"Failed to clean up temp file {temp_path}: {unlink_error}")

    def clear(self) -> int:
        """
        Clear all cached entries.

        Returns:
            Number of cache files deleted
        """
        if not self.enabled or not self.cache_dir.exists():
            return 0

        deleted = 0
        try:
            for cache_file in self.cache_dir.glob("*.json"):
                try:
                    cache_file.unlink()
                    deleted += 1
                except Exception as e:
                    logger.warning(f"Failed to delete cache file {cache_file}: {e}")

            logger.info(f"Cleared {deleted} cache entries")
            return deleted

        except Exception as e:
            logger.error(f"Error clearing cache: {e}")
            return deleted

    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate as percentage."""
        total = self.hits + self.misses
        if total == 0:
            return 0.0
        return (self.hits / total) * 100

    def summary(self) -> str:
        """Get cache usage summary."""
        if not self.enabled:
            return "Cache disabled"

        total = self.hits + self.misses
        if total == 0:
            return "No cache activity"

        return f"Cache: {self.hits} hits, {self.misses} misses ({self.hit_rate:.1f}% hit rate)"
