"""Tests for ecosystems_coverage coverage_command module."""

import argparse
from pathlib import Path

import pytest

from forge_gauge.plugins.ecosystems_coverage.coverage_command import (
    configure_coverage_parser,
    detect_ecosystem,
)
from forge_gauge.plugins.ecosystems_coverage.models import Ecosystem


class TestDetectEcosystem:
    """Tests for ecosystem auto-detection from file names."""

    def test_detect_ecosystem_requirements_txt(self, tmp_path: Path):
        """Test that requirements.txt is detected as Python."""
        req_file = tmp_path / "requirements.txt"
        req_file.touch()
        assert detect_ecosystem(req_file) == Ecosystem.PYTHON

    def test_detect_ecosystem_pyproject_toml(self, tmp_path: Path):
        """Test that pyproject.toml is detected as Python."""
        req_file = tmp_path / "pyproject.toml"
        req_file.touch()
        assert detect_ecosystem(req_file) == Ecosystem.PYTHON

    def test_detect_ecosystem_requirements_variant(self, tmp_path: Path):
        """Test that requirements-dev.txt is detected as Python."""
        req_file = tmp_path / "requirements-dev.txt"
        req_file.touch()
        assert detect_ecosystem(req_file) == Ecosystem.PYTHON

    def test_detect_ecosystem_package_lock_json(self, tmp_path: Path):
        """Test that package-lock.json is detected as JavaScript."""
        req_file = tmp_path / "package-lock.json"
        req_file.touch()
        assert detect_ecosystem(req_file) == Ecosystem.JAVASCRIPT

    def test_detect_ecosystem_yarn_lock(self, tmp_path: Path):
        """Test that yarn.lock is detected as JavaScript."""
        req_file = tmp_path / "yarn.lock"
        req_file.touch()
        assert detect_ecosystem(req_file) == Ecosystem.JAVASCRIPT

    def test_detect_ecosystem_pnpm_lock(self, tmp_path: Path):
        """Test that pnpm-lock.yaml is detected as JavaScript."""
        req_file = tmp_path / "pnpm-lock.yaml"
        req_file.touch()
        assert detect_ecosystem(req_file) == Ecosystem.JAVASCRIPT

    def test_detect_ecosystem_package_json(self, tmp_path: Path):
        """Test that package.json is detected as JavaScript."""
        req_file = tmp_path / "package.json"
        req_file.touch()
        assert detect_ecosystem(req_file) == Ecosystem.JAVASCRIPT

    def test_detect_ecosystem_pom_xml(self, tmp_path: Path):
        """Test that pom.xml is detected as Java."""
        req_file = tmp_path / "pom.xml"
        req_file.touch()
        assert detect_ecosystem(req_file) == Ecosystem.JAVA

    def test_detect_ecosystem_dot_pom(self, tmp_path: Path):
        """Test that .pom files are detected as Java."""
        req_file = tmp_path / "artifact.pom"
        req_file.touch()
        assert detect_ecosystem(req_file) == Ecosystem.JAVA

    def test_detect_ecosystem_generic_txt_as_python(self, tmp_path: Path):
        """Test that generic .txt files are detected as Python."""
        req_file = tmp_path / "deps.txt"
        req_file.touch()
        assert detect_ecosystem(req_file) == Ecosystem.PYTHON

    def test_detect_ecosystem_generic_json_as_javascript(self, tmp_path: Path):
        """Test that generic .json files are detected as JavaScript."""
        req_file = tmp_path / "deps.json"
        req_file.touch()
        assert detect_ecosystem(req_file) == Ecosystem.JAVASCRIPT

    def test_detect_ecosystem_generic_xml_as_java(self, tmp_path: Path):
        """Test that generic .xml files are detected as Java."""
        req_file = tmp_path / "deps.xml"
        req_file.touch()
        assert detect_ecosystem(req_file) == Ecosystem.JAVA

    def test_detect_ecosystem_unknown_raises(self, tmp_path: Path):
        """Test that unknown file extensions raise ValueError."""
        req_file = tmp_path / "unknown.xyz"
        req_file.touch()
        with pytest.raises(ValueError) as exc_info:
            detect_ecosystem(req_file)
        assert "Cannot auto-detect ecosystem" in str(exc_info.value)
        assert "--ecosystem" in str(exc_info.value)


class TestConfigureParser:
    """Tests for argument parser configuration."""

    def setup_method(self):
        """Set up parser for each test."""
        self.parser = argparse.ArgumentParser()
        configure_coverage_parser(self.parser)

    def test_configure_parser_python_version_choices(self):
        """Test that Python version choices include 3.9 through 3.14."""
        args = self.parser.parse_args(["-i", "req.txt", "--python-version", "3.9"])
        assert args.python_version == "3.9"

        args = self.parser.parse_args(["-i", "req.txt", "--python-version", "3.14"])
        assert args.python_version == "3.14"

    def test_configure_parser_python_version_default(self):
        """Test that Python version defaults to 3.12."""
        args = self.parser.parse_args(["-i", "req.txt"])
        assert args.python_version == "3.12"

    def test_configure_parser_arch_choices(self):
        """Test architecture choices."""
        args = self.parser.parse_args(["-i", "req.txt", "--arch", "arm64"])
        assert args.arch == "arm64"

        args = self.parser.parse_args(["-i", "req.txt", "-a", "amd64"])
        assert args.arch == "amd64"

    def test_configure_parser_manylinux_choices(self):
        """Test manylinux variant choices."""
        args = self.parser.parse_args(["-i", "req.txt", "--manylinux", "2_39"])
        assert args.manylinux == "2_39"

        args = self.parser.parse_args(["-i", "req.txt", "-M", "2_28"])
        assert args.manylinux == "2_28"

    def test_configure_parser_format_choices(self):
        """Test output format choices."""
        for fmt in ["table", "csv", "json"]:
            args = self.parser.parse_args(["-i", "req.txt", "--format", fmt])
            assert args.format == fmt

    def test_configure_parser_ecosystem_choices(self):
        """Test ecosystem choices."""
        for eco in ["python", "javascript", "java"]:
            args = self.parser.parse_args(["-i", "req.txt", "--ecosystem", eco])
            assert args.ecosystem == eco

    def test_configure_parser_organization_id(self):
        """Test --organization-id argument."""
        args = self.parser.parse_args(["-i", "req.txt", "--organization-id", "org-123"])
        assert args.organization_id == "org-123"

    def test_configure_parser_index_url(self):
        """Test --index-url argument for custom Python index."""
        args = self.parser.parse_args(
            ["-i", "req.txt", "--index-url", "https://libraries.cgr.dev/cu128/simple/"]
        )
        assert args.index_url == "https://libraries.cgr.dev/cu128/simple/"

    def test_configure_parser_index_url_short(self):
        """Test -I short flag for index URL."""
        args = self.parser.parse_args(
            ["-i", "req.txt", "-I", "https://example.com/simple/"]
        )
        assert args.index_url == "https://example.com/simple/"

    def test_configure_parser_maven_repo(self):
        """Test --maven-repo argument for Java."""
        args = self.parser.parse_args(
            ["-i", "pom.xml", "--maven-repo", "https://repo.example.com/maven2"]
        )
        assert args.maven_repo == "https://repo.example.com/maven2"

    def test_configure_parser_verbose_flag(self):
        """Test verbose flag."""
        args = self.parser.parse_args(["-i", "req.txt", "-v"])
        assert args.verbose is True

        args = self.parser.parse_args(["-i", "req.txt", "--verbose"])
        assert args.verbose is True

    def test_configure_parser_output_file(self):
        """Test output file argument."""
        args = self.parser.parse_args(["-i", "req.txt", "-o", "output.csv"])
        assert args.output == Path("output.csv")

    def test_configure_parser_input_required(self):
        """Test that input file is required."""
        with pytest.raises(SystemExit):
            self.parser.parse_args([])
