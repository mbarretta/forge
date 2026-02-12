"""
Exception hierarchy for Gauge application.

Provides a standardized exception hierarchy for consistent error handling
across the application. All exceptions inherit from GaugeException.
"""


class GaugeException(Exception):
    """Base exception for all Gauge errors."""
    pass


class ScanException(GaugeException):
    """Scan operation failed."""

    def __init__(self, image: str, reason: str):
        """
        Initialize scan exception.

        Args:
            image: Image reference that failed to scan
            reason: Reason for failure
        """
        self.image = image
        self.reason = reason
        super().__init__(f"Failed to scan {image}: {reason}")


class ValidationException(GaugeException):
    """Input validation failed."""

    def __init__(self, message: str, field: str = None):
        """
        Initialize validation exception.

        Args:
            message: Validation error message
            field: Field that failed validation (optional)
        """
        self.field = field
        if field:
            super().__init__(f"Validation failed for {field}: {message}")
        else:
            super().__init__(f"Validation failed: {message}")


class CacheException(GaugeException):
    """Cache operation failed."""
    pass


class IntegrationException(GaugeException):
    """External integration/API failed."""

    def __init__(self, service: str, reason: str):
        """
        Initialize integration exception.

        Args:
            service: Service name that failed
            reason: Reason for failure
        """
        self.service = service
        self.reason = reason
        super().__init__(f"{service} integration failed: {reason}")


class OutputException(GaugeException):
    """Output generation failed."""

    def __init__(self, format_type: str, reason: str):
        """
        Initialize output exception.

        Args:
            format_type: Output format (html, xlsx, etc.)
            reason: Reason for failure
        """
        self.format_type = format_type
        self.reason = reason
        super().__init__(f"Failed to generate {format_type} output: {reason}")


class ConfigurationException(GaugeException):
    """Configuration is invalid or missing."""
    pass


__all__ = [
    "GaugeException",
    "ScanException",
    "ValidationException",
    "CacheException",
    "IntegrationException",
    "OutputException",
    "ConfigurationException",
]
