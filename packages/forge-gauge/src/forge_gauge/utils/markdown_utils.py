"""
Markdown utilities for gauge output generation.

Provides functions for loading, processing, and converting markdown files to HTML.
"""

import logging
from pathlib import Path
from typing import Optional

import markdown

logger = logging.getLogger(__name__)


def load_and_convert_markdown(
    path: Optional[Path],
    section_name: str = "markdown content",
    template_processor: Optional[callable] = None,
) -> Optional[str]:
    """
    Load markdown file, optionally apply template processing, and convert to HTML.

    Args:
        path: Path to markdown file
        section_name: Name of section for error messages (e.g., "executive summary", "appendix")
        template_processor: Optional function to process content before markdown conversion.
                          Should have signature: (content: str) -> str

    Returns:
        HTML string, or None if file doesn't exist or processing fails

    Examples:
        >>> # Load simple markdown file
        >>> html = load_and_convert_markdown(Path("readme.md"))

        >>> # Load with template processing
        >>> def apply_vars(content):
        ...     return content.replace("{{name}}", "Acme Corp")
        >>> html = load_and_convert_markdown(Path("template.md"),
        ...                                    "executive summary",
        ...                                    apply_vars)
    """
    if not path or not path.exists():
        return None

    try:
        with open(path, "r") as f:
            content = f.read()

        # Apply template processing if provided
        if template_processor:
            content = template_processor(content)

        # Convert markdown to HTML
        html_content = markdown.markdown(content)
        return html_content

    except Exception as e:
        logger.warning(f"Could not load {section_name}: {e}")
        return None
