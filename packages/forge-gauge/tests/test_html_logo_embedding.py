"""
Tests for base64 logo embedding in HTML reports.

Verifies that the logo is read, encoded, cached, and handles missing files.
"""

import base64
from pathlib import Path
from unittest.mock import patch

from forge_gauge.outputs.html_generator import _get_logo_data_uri
from forge_gauge import outputs; import forge_gauge.outputs.html_generator as html_gen_module


class TestLogoDataUri:
    """Tests for _get_logo_data_uri()."""

    def setup_method(self):
        """Reset the logo cache before each test."""
        html_gen_module._logo_data_uri_cache = None

    def test_returns_valid_data_uri(self):
        """Should return a data:image/png;base64,... URI."""
        result = _get_logo_data_uri()
        assert result.startswith("data:image/png;base64,")

    def test_base64_is_decodable(self):
        """The base64 portion should be valid and decode to PNG bytes."""
        result = _get_logo_data_uri()
        b64_part = result.split(",", 1)[1]
        decoded = base64.b64decode(b64_part)
        # PNG files start with the PNG magic bytes
        assert decoded[:4] == b"\x89PNG"

    def test_result_is_cached(self):
        """Second call should return the cached result without re-reading."""
        first = _get_logo_data_uri()
        # Cache is set, so even if we could break file reading, it won't re-read
        second = _get_logo_data_uri()
        assert first == second
        assert first is second  # Same object from cache

    def test_returns_empty_string_on_missing_file(self):
        """Should return empty string if logo file cannot be read."""
        # Patch read_bytes on the logo Path to simulate missing file
        original_read_bytes = Path.read_bytes

        def fake_read_bytes(self):
            if self.name == "linky-white.png":
                raise FileNotFoundError("no such file")
            return original_read_bytes(self)

        with patch.object(Path, "read_bytes", fake_read_bytes):
            result = _get_logo_data_uri()
        assert result == ""
