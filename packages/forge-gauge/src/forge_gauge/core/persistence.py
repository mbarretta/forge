"""
Scan result persistence for checkpoint/resume functionality.

Enables saving and loading scan results to support long-running scans
that can be interrupted and resumed.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from forge_gauge.core.exceptions import CacheException
from forge_gauge.core.models import (
    CHPSScore,
    ImageAnalysis,
    ImagePair,
    ScanResult,
    VulnerabilityCount,
)
from forge_gauge.utils.validation import validate_image_reference

logger = logging.getLogger(__name__)


class ScanResultPersistence:
    """
    Handles persistence of scan results to disk.

    Provides checkpoint/resume functionality for long-running scans,
    allowing recovery from interruptions without re-scanning.
    """

    def __init__(self, checkpoint_path: Optional[Path] = None):
        """
        Initialize persistence manager.

        Args:
            checkpoint_path: Path for checkpoint file
                           (default: .gauge_checkpoint.json)
        """
        self.checkpoint_path = checkpoint_path or Path(".gauge_checkpoint.json")

    def save_results(
        self,
        results: List[ScanResult],
        metadata: Optional[dict] = None,
    ) -> None:
        """
        Save scan results to checkpoint file.

        Args:
            results: List of scan results to save
            metadata: Optional metadata (e.g., scan parameters)

        Raises:
            CacheException: If save fails
        """
        try:
            data = {
                "version": "2.0",
                "timestamp": datetime.now().isoformat(),
                "metadata": metadata or {},
                "results": [self._serialize_result(r) for r in results],
            }

            # Write atomically by writing to temp file then renaming
            temp_path = self.checkpoint_path.with_suffix(".tmp")
            temp_path.write_text(json.dumps(data, indent=2, default=str))
            temp_path.replace(self.checkpoint_path)

            logger.debug(
                f"Saved {len(results)} results to checkpoint: {self.checkpoint_path}"
            )

        except Exception as e:
            raise CacheException(f"Failed to save checkpoint: {e}")

    def load_results(self) -> tuple[List[ScanResult], dict]:
        """
        Load scan results from checkpoint file.

        Returns:
            Tuple of (results, metadata)

        Raises:
            CacheException: If load fails
        """
        if not self.checkpoint_path.exists():
            return [], {}

        try:
            data = json.loads(self.checkpoint_path.read_text())

            version = data.get("version", "1.0")
            if version != "2.0":
                logger.warning(
                    f"Checkpoint version mismatch: {version} (expected 2.0)"
                )

            results = [
                self._deserialize_result(r) for r in data.get("results", [])
            ]
            metadata = data.get("metadata", {})

            logger.info(
                f"Loaded {len(results)} results from checkpoint: {self.checkpoint_path}"
            )

            return results, metadata

        except json.JSONDecodeError as e:
            raise CacheException(f"Invalid checkpoint file: {e}")
        except Exception as e:
            raise CacheException(f"Failed to load checkpoint: {e}")

    def exists(self) -> bool:
        """
        Check if checkpoint file exists.

        Returns:
            True if checkpoint file exists
        """
        return self.checkpoint_path.exists()

    def clear(self) -> None:
        """Delete checkpoint file if it exists."""
        if self.checkpoint_path.exists():
            self.checkpoint_path.unlink()
            logger.debug(f"Cleared checkpoint: {self.checkpoint_path}")

    def get_metadata(self) -> Optional[dict]:
        """
        Get metadata from checkpoint without loading full results.

        Returns:
            Metadata dictionary or None if checkpoint doesn't exist
        """
        if not self.checkpoint_path.exists():
            return None

        try:
            data = json.loads(self.checkpoint_path.read_text())
            return data.get("metadata", {})
        except (json.JSONDecodeError, OSError, KeyError) as e:
            logger.debug(f"Failed to read checkpoint metadata: {e}")
            return None

    def get_failed_pairs(self, skip_permanent: bool = False) -> List[ImagePair]:
        """
        Extract image pairs from failed scan results.

        Args:
            skip_permanent: If True, skip auth/not_found errors (considered permanent)

        Returns:
            List of ImagePair objects for failed scans
        """
        results, _ = self.load_results()

        # Patterns that indicate permanent failures (auth issues, image not found)
        permanent_error_patterns = [
            "unauthorized",
            "authentication required",
            "denied",
            "not found",
            "404",
            "manifest unknown",
            "name unknown",
            "forbidden",
            "403",
        ]

        failed_pairs = []
        for result in results:
            if result.scan_successful:
                continue

            # Check if this is a permanent failure
            if skip_permanent and result.error_message:
                error_lower = result.error_message.lower()
                if any(pattern in error_lower for pattern in permanent_error_patterns):
                    logger.debug(
                        f"Skipping permanent failure: {result.pair.alternative_image} "
                        f"({result.error_message})"
                    )
                    continue

            failed_pairs.append(result.pair)

        return failed_pairs

    def merge_retry_results(
        self, retry_results: List[ScanResult]
    ) -> List[ScanResult]:
        """
        Merge retry results into existing checkpoint, replacing matching pairs.

        Args:
            retry_results: New results from retry scans

        Returns:
            Merged list of all results with retry results replacing old failures
        """
        existing_results, _ = self.load_results()

        # Create lookup for retry results by pair key
        retry_lookup = {
            (r.pair.alternative_image, r.pair.chainguard_image): r
            for r in retry_results
        }

        # Merge: replace existing results with retry results where available
        merged = []
        for result in existing_results:
            pair_key = (result.pair.alternative_image, result.pair.chainguard_image)
            if pair_key in retry_lookup:
                merged.append(retry_lookup[pair_key])
            else:
                merged.append(result)

        return merged

    @staticmethod
    def _serialize_result(result: ScanResult) -> dict:
        """
        Serialize ScanResult to dictionary.

        Args:
            result: ScanResult to serialize

        Returns:
            Dictionary representation
        """
        return {
            "pair": {
                "chainguard_image": result.pair.chainguard_image,
                "alternative_image": result.pair.alternative_image,
            },
            "scan_successful": result.scan_successful,
            "error_message": result.error_message,
            "alternative_analysis": (
                ScanResultPersistence._serialize_analysis(result.alternative_analysis)
                if result.alternative_analysis
                else None
            ),
            "chainguard_analysis": (
                ScanResultPersistence._serialize_analysis(result.chainguard_analysis)
                if result.chainguard_analysis
                else None
            ),
        }

    @staticmethod
    def _serialize_analysis(analysis: ImageAnalysis) -> dict:
        """Serialize ImageAnalysis to dictionary."""
        return {
            "name": analysis.name,
            "size_mb": analysis.size_mb,
            "package_count": analysis.package_count,
            "vulnerabilities": analysis.vulnerabilities.to_dict(),
            "scan_timestamp": analysis.scan_timestamp.isoformat(),
            "digest": analysis.digest,
            "cache_hit": analysis.cache_hit,
            "chps_score": (
                {
                    "score": analysis.chps_score.score,
                    "grade": analysis.chps_score.grade,
                    "details": analysis.chps_score.details,
                }
                if analysis.chps_score
                else None
            ),
        }

    @staticmethod
    def _deserialize_result(data: dict) -> ScanResult:
        """
        Deserialize dictionary to ScanResult.

        Args:
            data: Dictionary representation

        Returns:
            ScanResult instance
        """
        # Validate image references to prevent checkpoint injection attacks
        upstream_image = data["pair"].get("upstream_image")
        pair = ImagePair(
            chainguard_image=validate_image_reference(
                data["pair"]["chainguard_image"], "checkpoint chainguard_image"
            ),
            alternative_image=validate_image_reference(
                data["pair"]["alternative_image"], "checkpoint alternative_image"
            ),
            upstream_image=validate_image_reference(
                upstream_image, "checkpoint upstream_image"
            ) if upstream_image else None,
        )

        return ScanResult(
            pair=pair,
            scan_successful=data["scan_successful"],
            error_message=data.get("error_message"),
            alternative_analysis=(
                ScanResultPersistence._deserialize_analysis(
                    data["alternative_analysis"]
                )
                if data.get("alternative_analysis")
                else None
            ),
            chainguard_analysis=(
                ScanResultPersistence._deserialize_analysis(
                    data["chainguard_analysis"]
                )
                if data.get("chainguard_analysis")
                else None
            ),
        )

    @staticmethod
    def _deserialize_analysis(data: dict) -> ImageAnalysis:
        """Deserialize dictionary to ImageAnalysis."""
        return ImageAnalysis(
            name=data["name"],
            size_mb=data["size_mb"],
            package_count=data["package_count"],
            vulnerabilities=VulnerabilityCount(**data["vulnerabilities"]),
            scan_timestamp=datetime.fromisoformat(data["scan_timestamp"]),
            digest=data.get("digest"),
            cache_hit=data.get("cache_hit", False),
            chps_score=(
                CHPSScore(
                    score=data["chps_score"]["score"],
                    grade=data["chps_score"]["grade"],
                    details=data["chps_score"].get("details", {}),
                )
                if data.get("chps_score")
                else None
            ),
        )


__all__ = ["ScanResultPersistence"]
