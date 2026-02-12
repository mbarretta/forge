"""
Utility functions for filename and customer name handling.
"""

import re

# Re-export extract_registry_from_image from image_utils for backwards compatibility
from forge_gauge.utils.image_utils import extract_registry_from_image


def sanitize_customer_name(name: str) -> str:
    """
    Sanitize customer name for use in filenames.

    Args:
        name: Raw customer name (e.g., "Acme Corp", "Test & Co.")

    Returns:
        Sanitized name suitable for filenames (e.g., "acme_corp", "test_co")
    """
    safe_name = name.replace("&", "").replace(".", "")
    safe_name = "".join(c if c.isalnum() or c in (" ", "-", "_") else "_" for c in safe_name)
    safe_name = safe_name.replace(" ", "_").lower()
    safe_name = re.sub(r"_+", "_", safe_name)
    return safe_name
