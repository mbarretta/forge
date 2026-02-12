"""
Error classification for intelligent retry logic.

Categorizes Docker/registry errors into classes that determine
retry strategy and handling.
"""

from enum import Enum
from dataclasses import dataclass
import re


class ErrorCategory(str, Enum):
    """
    Error categories that determine retry strategy.
    """
    PERMANENT_INFRASTRUCTURE = "permanent_infrastructure"
    """DNS errors, invalid hostnames - don't retry"""

    TRANSIENT_AUTH = "transient_auth"
    """Auth token expired/invalid - retry immediately with token refresh"""

    TRANSIENT_NETWORK = "transient_network"
    """Timeouts, connection issues - retry at end with backoff"""

    RATE_LIMIT = "rate_limit"
    """Rate limiting - retry with exponential backoff"""

    PERMANENT_NOT_FOUND = "permanent_not_found"
    """Image not found - don't retry (already handled by fallback)"""

    UNKNOWN = "unknown"
    """Unknown error - treat as transient network"""


@dataclass(frozen=True)
class ClassifiedError:
    """
    An error with its classification and metadata.
    """
    category: ErrorCategory
    original_message: str
    retry_recommended: bool
    retry_delay: float = 0.0  # seconds
    requires_auth_refresh: bool = False


class ErrorClassifier:
    """
    Classifies Docker/registry errors into categories.
    """

    # DNS and infrastructure patterns
    DNS_PATTERNS = [
        r"no such host",
        r"could not resolve host",
        r"name or service not known",
        r"temporary failure in name resolution",
        r"nodename nor servname provided",
    ]

    # Authentication patterns
    AUTH_PATTERNS = [
        r"401",
        r"403",
        r"unauthorized",
        r"forbidden",
        r"denied",
        r"authentication required",
        r"access denied",
        r"no basic auth credentials",
        r"authentication failed",
        r"not authorized",
        r"authorization failed",
        r"token expired",
        r"invalid token",
    ]

    # Rate limit patterns
    RATE_LIMIT_PATTERNS = [
        r"toomanyrequests",
        r"rate limit",
        r"too many requests",
        r"429",
    ]

    # Network/timeout patterns
    NETWORK_PATTERNS = [
        r"timeout",
        r"timed out",
        r"connection refused",
        r"connection reset",
        r"dial tcp.*i/o timeout",
        r"network is unreachable",
        r"broken pipe",
    ]

    # Not found patterns
    NOT_FOUND_PATTERNS = [
        r"not found",
        r"manifest unknown",
        r"does not exist",
        r"no such image",
        r"404",
    ]

    @classmethod
    def classify(cls, error_message: str, error_type: str = "unknown") -> ClassifiedError:
        """
        Classify an error based on error_type first, then message patterns.

        Args:
            error_message: Error message from Docker/registry
            error_type: Error type from docker_utils (auth_error, timeout, dns_error, etc.)

        Returns:
            ClassifiedError with category and retry recommendations
        """
        error_lower = error_message.lower()

        # Priority 1: Use error_type if available (more reliable than pattern matching)
        if error_type and error_type != "unknown":
            if error_type in ("auth_error", "authentication"):
                return ClassifiedError(
                    category=ErrorCategory.TRANSIENT_AUTH,
                    original_message=error_message,
                    retry_recommended=True,
                    requires_auth_refresh=True,
                    retry_delay=0.0,
                )
            elif error_type == "timeout":
                return ClassifiedError(
                    category=ErrorCategory.TRANSIENT_NETWORK,
                    original_message=error_message,
                    retry_recommended=True,
                    retry_delay=0.0,
                )
            elif error_type in ("dns_error", "infrastructure"):
                return ClassifiedError(
                    category=ErrorCategory.PERMANENT_INFRASTRUCTURE,
                    original_message=error_message,
                    retry_recommended=False,
                )
            elif error_type == "not_found":
                return ClassifiedError(
                    category=ErrorCategory.PERMANENT_NOT_FOUND,
                    original_message=error_message,
                    retry_recommended=False,
                )
            elif error_type == "rate_limit":
                return ClassifiedError(
                    category=ErrorCategory.RATE_LIMIT,
                    original_message=error_message,
                    retry_recommended=True,
                    retry_delay=60.0,
                )

        # Priority 2: Fall back to pattern matching for unclassified errors
        # Check DNS/infrastructure errors (highest priority - permanent)
        if any(re.search(pattern, error_lower) for pattern in cls.DNS_PATTERNS):
            return ClassifiedError(
                category=ErrorCategory.PERMANENT_INFRASTRUCTURE,
                original_message=error_message,
                retry_recommended=False,
            )

        # Check authentication errors (retry with token refresh)
        if any(re.search(pattern, error_lower) for pattern in cls.AUTH_PATTERNS):
            return ClassifiedError(
                category=ErrorCategory.TRANSIENT_AUTH,
                original_message=error_message,
                retry_recommended=True,
                requires_auth_refresh=True,
                retry_delay=0.0,  # Immediate retry after token refresh
            )

        # Check rate limiting (retry with exponential backoff)
        if any(re.search(pattern, error_lower) for pattern in cls.RATE_LIMIT_PATTERNS):
            return ClassifiedError(
                category=ErrorCategory.RATE_LIMIT,
                original_message=error_message,
                retry_recommended=True,
                retry_delay=60.0,  # Start with 60s backoff
            )

        # Check not found errors (permanent)
        if any(re.search(pattern, error_lower) for pattern in cls.NOT_FOUND_PATTERNS):
            return ClassifiedError(
                category=ErrorCategory.PERMANENT_NOT_FOUND,
                original_message=error_message,
                retry_recommended=False,
            )

        # Check network/timeout errors (retry at end)
        if any(re.search(pattern, error_lower) for pattern in cls.NETWORK_PATTERNS):
            return ClassifiedError(
                category=ErrorCategory.TRANSIENT_NETWORK,
                original_message=error_message,
                retry_recommended=True,
                retry_delay=0.0,  # Will be retried at end with backoff
            )

        # Unknown - treat as transient network
        return ClassifiedError(
            category=ErrorCategory.UNKNOWN,
            original_message=error_message,
            retry_recommended=True,
            retry_delay=0.0,
        )
