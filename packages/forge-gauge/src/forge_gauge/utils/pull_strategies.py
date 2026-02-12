"""
Pull fallback strategies for container images.

Implements the Strategy pattern for various fallback approaches when
pulling container images fails.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class PullContext:
    """Context for pull strategy decisions."""

    original_image: str
    """The original image reference requested."""

    last_error: str
    """The error from the last pull attempt."""

    is_auth_error: bool
    """Whether the error is an authentication error."""

    is_recoverable: bool
    """Whether the error is potentially recoverable."""

    upstream_image: Optional[str] = None
    """Discovered upstream image (if any)."""

    allow_chainguard_private_fallback: bool = False
    """Whether chainguard-private fallback is allowed."""

    support_mode_detected: bool = False
    """Whether support mode has been detected."""

    support_mode_org: Optional[str] = None
    """The organization for support mode."""


@dataclass
class PullResult:
    """Result of a pull strategy attempt."""

    success: bool
    """Whether the pull succeeded."""

    image: str
    """The image that was pulled (or attempted)."""

    is_fallback: bool
    """Whether a fallback was used."""

    error_type: str
    """Error type: none, auth, timeout, rate_limit, not_found, unknown."""

    triggered_support_mode: bool = False
    """Whether this result should trigger support mode."""


class PullStrategy(ABC):
    """
    Abstract base class for pull fallback strategies.

    Each strategy defines:
    - Whether it can apply to a given context
    - How to transform the image reference
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Strategy name for logging."""
        ...

    @abstractmethod
    def can_apply(self, ctx: PullContext) -> bool:
        """
        Check if this strategy can apply to the given context.

        Args:
            ctx: Pull context with image and error information

        Returns:
            True if this strategy should be attempted
        """
        ...

    @abstractmethod
    def get_fallback_image(self, ctx: PullContext) -> Optional[str]:
        """
        Get the fallback image to try.

        Args:
            ctx: Pull context

        Returns:
            Fallback image reference, or None if no fallback available
        """
        ...

    def on_success(self, ctx: PullContext, fallback_image: str) -> Optional[dict]:
        """
        Called when the strategy succeeds. Can return state updates.

        Args:
            ctx: Pull context
            fallback_image: The image that was successfully pulled

        Returns:
            Optional dict of state updates (e.g., support mode detection)
        """
        return None


class ChainguardPrivateFallbackStrategy(PullStrategy):
    """
    Strategy for falling back to cgr.dev/chainguard-private when auth fails.

    Applies when:
    - Auth error on a cgr.dev/<org>/<image> reference
    - chainguard_private_fallback is allowed
    """

    def __init__(self, get_private_fallback: Callable[[str], Optional[str]],
                 extract_org: Callable[[str], Optional[str]]):
        self._get_private_fallback = get_private_fallback
        self._extract_org = extract_org

    @property
    def name(self) -> str:
        return "chainguard-private"

    def can_apply(self, ctx: PullContext) -> bool:
        if not ctx.is_auth_error:
            return False
        if not ctx.allow_chainguard_private_fallback:
            return False

        # Check if it's a CGR org image
        private = self._get_private_fallback(ctx.original_image)
        return private is not None

    def get_fallback_image(self, ctx: PullContext) -> Optional[str]:
        return self._get_private_fallback(ctx.original_image)

    def on_success(self, ctx: PullContext, fallback_image: str) -> Optional[dict]:
        org = self._extract_org(ctx.original_image)
        if org and not ctx.support_mode_detected:
            logger.info(
                f"Support mode detected: will use chainguard-private directly for '{org}' images"
            )
            return {
                "support_mode_detected": True,
                "support_mode_org": org
            }
        return None


class UpstreamFallbackStrategy(PullStrategy):
    """
    Strategy for falling back to discovered upstream image.

    Applies when:
    - An upstream image was discovered (e.g., docker.io equivalent for private registry)
    """

    @property
    def name(self) -> str:
        return "upstream"

    def can_apply(self, ctx: PullContext) -> bool:
        return ctx.upstream_image is not None

    def get_fallback_image(self, ctx: PullContext) -> Optional[str]:
        return ctx.upstream_image


class MirrorGCRFallbackStrategy(PullStrategy):
    """
    Strategy for falling back to mirror.gcr.io for Docker Hub images.

    Applies when:
    - The image is from Docker Hub (docker.io or implicit)
    - Error is rate limiting or not found
    """

    def __init__(self, get_mirror_image: Callable[[str], Optional[str]]):
        self._get_mirror_image = get_mirror_image

    @property
    def name(self) -> str:
        return "mirror.gcr.io"

    def can_apply(self, ctx: PullContext) -> bool:
        mirror = self._get_mirror_image(ctx.original_image)
        return mirror is not None

    def get_fallback_image(self, ctx: PullContext) -> Optional[str]:
        return self._get_mirror_image(ctx.original_image)


class LatestTagFallbackStrategy(PullStrategy):
    """
    Strategy for falling back to :latest tag.

    Applies when:
    - The original image has a specific tag that might not exist
    """

    def __init__(self, get_latest_fallback: Callable[[str], Optional[str]]):
        self._get_latest_fallback = get_latest_fallback

    @property
    def name(self) -> str:
        return ":latest tag"

    def can_apply(self, ctx: PullContext) -> bool:
        latest = self._get_latest_fallback(ctx.original_image)
        return latest is not None

    def get_fallback_image(self, ctx: PullContext) -> Optional[str]:
        return self._get_latest_fallback(ctx.original_image)


class SkopeoMostRecentStrategy(PullStrategy):
    """
    Strategy for finding the most recent tag using skopeo.

    Applies when:
    - Other strategies have failed
    - Skopeo can list tags for the image
    """

    def __init__(self, get_most_recent_tag: Callable[[str], Optional[str]]):
        self._get_most_recent_tag = get_most_recent_tag
        self._cached_tag: Optional[str] = None

    @property
    def name(self) -> str:
        return "skopeo most-recent"

    def can_apply(self, ctx: PullContext) -> bool:
        self._cached_tag = self._get_most_recent_tag(ctx.original_image)
        return self._cached_tag is not None

    def get_fallback_image(self, ctx: PullContext) -> Optional[str]:
        if self._cached_tag:
            base_image = ctx.original_image.rsplit(":", 1)[0]
            return f"{base_image}:{self._cached_tag}"
        return None
