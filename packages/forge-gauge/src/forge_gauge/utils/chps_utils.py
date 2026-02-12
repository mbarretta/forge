"""
Utility functions for integrating with CHPS (Container Hardening and Provenance Scanner).

CHPS is a tool that scores container images based on hardening and provenance best practices.
See: https://github.com/chps-dev/chps-scorer

This implementation runs chps-scorer in a container, eliminating the need for local installation.
"""

import json
import logging
import subprocess
from typing import Optional

from forge_gauge.constants import CHPS_SCORER_EXPECTED_DIGEST, CHPS_SCORER_IMAGE
from forge_gauge.core.models import CHPSScore
from forge_gauge.utils.validation import validate_image_reference

logger = logging.getLogger(__name__)


class CHPSScanner:
    """
    Scanner for running CHPS (Container Hardening and Provenance Scanner).

    CHPS evaluates container images for security hardening and provenance practices,
    providing a score and grade based on various security criteria.

    Runs chps-scorer in a container to avoid requiring local installation.
    """

    def __init__(self, docker_command: str = "docker"):
        """
        Initialize CHPS scanner.

        Args:
            docker_command: Docker/Podman command to use (default: "docker")
        """
        self.docker_command = docker_command
        self.chps_available = self._check_chps_available()
        if not self.chps_available:
            logger.warning(
                f"CHPS container image not available. CHPS scoring will be skipped. "
                f"Run: {docker_command} pull {CHPS_SCORER_IMAGE}"
            )

    def _check_chps_available(self) -> bool:
        """Check if CHPS container image is available and verify its integrity."""
        try:
            logger.info(f"Checking CHPS image availability: {CHPS_SCORER_IMAGE}")
            # Try to pull the CHPS image if not already present
            result = subprocess.run(
                [self.docker_command, "pull", CHPS_SCORER_IMAGE],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                logger.warning(f"✗ Failed to pull CHPS image: {result.stderr}")
                logger.warning(f"CHPS stdout: {result.stdout}")
                return False

            # Verify the image digest matches expected value
            if not self._verify_image_digest():
                logger.error(
                    "✗ CHPS image digest verification failed. "
                    "The image may have been tampered with or the expected digest needs updating."
                )
                return False

            logger.info(f"✓ CHPS scorer container image ready and verified: {CHPS_SCORER_IMAGE}")
            return True

        except FileNotFoundError as e:
            logger.warning(f"✗ Docker/Podman command not found: {e}")
            return False
        except subprocess.TimeoutExpired:
            logger.warning("✗ Timeout pulling CHPS image (120s)")
            return False
        except Exception as e:
            logger.warning(f"✗ CHPS availability check failed: {e}")
            return False

    def _verify_image_digest(self) -> bool:
        """
        Verify the pulled CHPS image matches the expected digest.

        Returns:
            True if digest matches, False otherwise
        """
        try:
            result = subprocess.run(
                [
                    self.docker_command,
                    "inspect",
                    CHPS_SCORER_IMAGE,
                    "--format",
                    "{{index .RepoDigests 0}}",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                logger.warning(f"Failed to inspect CHPS image: {result.stderr}")
                return False

            # Extract digest from output (format: "image@sha256:...")
            repo_digest = result.stdout.strip()
            if "@" in repo_digest:
                actual_digest = repo_digest.split("@")[1]
            else:
                actual_digest = repo_digest

            if actual_digest == CHPS_SCORER_EXPECTED_DIGEST:
                logger.debug(f"CHPS image digest verified: {actual_digest}")
                return True
            else:
                logger.error(
                    f"CHPS image digest mismatch! "
                    f"Expected: {CHPS_SCORER_EXPECTED_DIGEST}, "
                    f"Actual: {actual_digest}"
                )
                return False

        except subprocess.TimeoutExpired:
            logger.warning("Timeout verifying CHPS image digest")
            return False
        except Exception as e:
            logger.warning(f"Failed to verify CHPS image digest: {e}")
            return False

    def scan_image(self, image_name: str) -> Optional[CHPSScore]:
        """
        Run CHPS scoring on a local image using containerized chps-scorer.

        Args:
            image_name: Name/reference of the local image to score

        Returns:
            CHPSScore object with score, grade, and details, or None if scan fails
        """
        if not self.chps_available:
            logger.debug(f"CHPS not available, skipping scan for {image_name}")
            return None

        # Validate image reference before passing to subprocess
        try:
            image_name = validate_image_reference(image_name, "image_name")
        except Exception as e:
            logger.warning(f"Invalid image reference for CHPS scan: {e}")
            return None

        try:
            logger.info(f"Running CHPS scan on {image_name}...")

            # Run chps-scorer in a container with access to Docker socket
            # chps-scorer uses Docker-in-Docker, requires --privileged
            # Syntax: chps-scorer -o json --skip-cves --local <image>
            cmd = [
                self.docker_command,
                "run",
                "--rm",
                "--privileged",
                "-v", "/var/run/docker.sock:/var/run/docker.sock",
                CHPS_SCORER_IMAGE,
                "-o", "json",
                "--skip-cves",
                "--local",
                image_name,
            ]

            logger.debug(f"CHPS command: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode != 0:
                logger.warning(f"CHPS scan failed for {image_name}: {result.stderr}")
                logger.debug(f"CHPS stdout: {result.stdout}")
                return None

            # Parse JSON output
            # CHPS output has "Using local image: ..." prefix before JSON, skip it
            output_text = result.stdout.strip()

            # Find the start of JSON (first '{')
            json_start = output_text.find('{')
            if json_start == -1:
                logger.warning(f"No JSON found in CHPS output for {image_name}")
                return None

            json_text = output_text[json_start:]
            logger.debug(f"CHPS JSON output for {image_name}: {json_text[:200]}...")

            output_data = json.loads(json_text)

            # Extract score and grade from the JSON structure
            # CHPS returns: {"overall": {"score": X, "max": Y, "grade": "A"}, "scores": {...}}
            overall = output_data.get("overall", {})
            scores = output_data.get("scores", {})

            # When running with --skip-cves, we need to recalculate scores
            # Original max: 20 points (4 minimalism + 8 provenance + 4 configuration + 4 cves)
            # With --skip-cves: 16 points (4 minimalism + 8 provenance + 4 configuration)
            original_score = overall.get("score", 0)
            original_max = overall.get("max", 20)

            # Calculate actual score from components (excluding CVEs)
            minimalism_score = scores.get("minimalism", {}).get("score", 0)
            provenance_score = scores.get("provenance", {}).get("score", 0)
            configuration_score = scores.get("configuration", {}).get("score", 0)

            # Recalculated score (out of 16)
            adjusted_score = minimalism_score + provenance_score + configuration_score
            adjusted_max = 16  # 4 + 8 + 4
            adjusted_percentage = (adjusted_score / adjusted_max * 100) if adjusted_max > 0 else 0

            # Recalculate grade based on adjusted percentage
            # Spec: 100=A+, 75-99=A, 50-74=B, 40-49=C, 1-39=D, 0=F
            if adjusted_percentage == 100:
                grade = "A+"
            elif adjusted_percentage >= 75:
                grade = "A"
            elif adjusted_percentage >= 50:
                grade = "B"
            elif adjusted_percentage >= 40:
                grade = "C"
            elif adjusted_percentage >= 1:
                grade = "D"
            else:
                grade = "F"

            # Store detailed breakdown with adjusted values
            details = {
                "scores": scores,  # Include all component scores
                "image": output_data.get("image", ""),
                "digest": output_data.get("digest", ""),
                "original_score": original_score,
                "original_max": original_max,
                "adjusted_max": adjusted_max,
                "adjusted_percentage": adjusted_percentage,
            }

            logger.info(
                f"CHPS scan complete for {image_name}: "
                f"Score={adjusted_score}/{adjusted_max} ({adjusted_percentage:.0f}%), Grade={grade}"
            )

            return CHPSScore(
                score=adjusted_score,
                grade=grade,
                details=details,
            )

        except subprocess.TimeoutExpired:
            logger.warning(f"CHPS scan timeout for {image_name}")
            return None
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse CHPS output for {image_name}: {e}")
            return None
        except Exception as e:
            logger.warning(f"CHPS scan error for {image_name}: {e}")
            return None
