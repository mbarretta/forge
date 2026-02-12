"""
Error pattern constants for Docker/container registry operations.

Centralized definitions for classifying error messages from container
runtime operations (pull, push, etc.).
"""

# Authentication/authorization error patterns
# These indicate permanent failures that should not be retried with fallback strategies
AUTH_ERROR_PATTERNS = [
    "401",
    "403",
    "unauthorized",
    "forbidden",
    "denied",
    "authentication required",
    "access denied",
    "no basic auth credentials",
    "authentication failed",
    "not authorized",
    "authorization failed",
    # GCR-specific error patterns
    "permission denied",
    "caller does not have permission",
    "request had insufficient authentication scopes",
]

# Rate limiting error patterns
RATE_LIMIT_PATTERNS = [
    "429",
    "toomanyrequests",
    "rate limit",
    "too many requests",
]

# Not found error patterns
NOT_FOUND_PATTERNS = [
    "404",
    "not found",
    "manifest unknown",
    "does not exist",
    "no such image",
]

# Connection/network error patterns (recoverable)
CONNECTION_ERROR_PATTERNS = [
    "no such host",
    "connection refused",
    "dial tcp",
]


def is_auth_error(stderr: str) -> bool:
    """
    Check if error is due to authentication/authorization failure.

    These are permanent failures that should not be retried with fallback strategies.

    Args:
        stderr: Error output from docker command

    Returns:
        True if error is authentication-related
    """
    stderr_lower = stderr.lower()
    return any(pattern in stderr_lower for pattern in AUTH_ERROR_PATTERNS)


def is_rate_limit_error(stderr: str) -> bool:
    """
    Check if error is due to rate limiting.

    Args:
        stderr: Error output from docker command

    Returns:
        True if error is rate-limit related
    """
    stderr_lower = stderr.lower()
    return any(pattern in stderr_lower for pattern in RATE_LIMIT_PATTERNS)


def is_not_found_error(stderr: str) -> bool:
    """
    Check if error is due to image not found.

    Args:
        stderr: Error output from docker command

    Returns:
        True if error is not-found related
    """
    stderr_lower = stderr.lower()
    return any(pattern in stderr_lower for pattern in NOT_FOUND_PATTERNS)


def is_recoverable_error(stderr: str) -> bool:
    """
    Check if error is recoverable with fallback strategies.

    Authentication errors are NOT recoverable with fallbacks.

    Args:
        stderr: Error output from docker command

    Returns:
        True if error might be recoverable with fallback strategies
    """
    if is_auth_error(stderr):
        return False

    stderr_lower = stderr.lower()
    recoverable_patterns = NOT_FOUND_PATTERNS + RATE_LIMIT_PATTERNS + CONNECTION_ERROR_PATTERNS
    return any(pattern in stderr_lower for pattern in recoverable_patterns)


def classify_error_type(stderr: str) -> str:
    """
    Classify the type of error from stderr output.

    Args:
        stderr: Error output from docker command

    Returns:
        Error type: "auth", "timeout", "rate_limit", "not_found", or "unknown"
    """
    if stderr == "timeout":
        return "timeout"

    if is_auth_error(stderr):
        return "auth"

    if is_rate_limit_error(stderr):
        return "rate_limit"

    if is_not_found_error(stderr):
        return "not_found"

    return "unknown"
