"""Tests for ecosystems_coverage wrapper module."""

from forge_gauge.plugins.ecosystems_coverage.wrapper import _extract_org_list


class TestExtractOrgList:
    """Tests for _extract_org_list function."""

    def test_extract_org_list_parses_multiple_orgs(self):
        """Test extracting organization IDs from multiple orgs error output."""
        output = """Multiple organizations found. Please specify one with --organization-id:
  - org-abc-123
  - org-def-456
  - org-xyz-789
"""
        result = _extract_org_list(output)
        assert "Available organizations:" in result
        assert "org-abc-123" in result
        assert "org-def-456" in result
        assert "org-xyz-789" in result

    def test_extract_org_list_parses_single_org(self):
        """Test extracting a single organization ID."""
        output = """Multiple organizations found. Please specify one with --organization-id:
  - my-single-org
"""
        result = _extract_org_list(output)
        assert "Available organizations:" in result
        assert "my-single-org" in result

    def test_extract_org_list_empty_output(self):
        """Test handling empty input."""
        result = _extract_org_list("")
        assert result == ""

    def test_extract_org_list_no_orgs_found(self):
        """Test handling output with no organization section."""
        output = """Some other error message
Without any org list
"""
        result = _extract_org_list(output)
        assert result == ""

    def test_extract_org_list_partial_header(self):
        """Test handling output with partial match."""
        output = """Error: Multiple issues found
Not the org list you're looking for
"""
        result = _extract_org_list(output)
        assert result == ""

    def test_extract_org_list_preserves_org_format(self):
        """Test that org IDs with various formats are preserved."""
        output = """Multiple organizations found. Please specify one with --organization-id:
  - chainguard/engineering
  - org-with-numbers-123
  - simple-org
"""
        result = _extract_org_list(output)
        assert "chainguard/engineering" in result
        assert "org-with-numbers-123" in result
        assert "simple-org" in result

    def test_extract_org_list_handles_extra_whitespace(self):
        """Test handling of extra whitespace in org list."""
        output = """Multiple organizations found. Please specify one with --organization-id:
  -   org-with-spaces
  - normal-org
"""
        result = _extract_org_list(output)
        assert "org-with-spaces" in result
        assert "normal-org" in result

    def test_extract_org_list_mixed_content(self):
        """Test extracting orgs when there's content before the org list."""
        output = """INFO: Checking authentication...
DEBUG: Token valid
Multiple organizations found. Please specify one with --organization-id:
  - org-first
  - org-second
"""
        result = _extract_org_list(output)
        assert "org-first" in result
        assert "org-second" in result
        # Should not include log lines
        assert "INFO" not in result
        assert "DEBUG" not in result
