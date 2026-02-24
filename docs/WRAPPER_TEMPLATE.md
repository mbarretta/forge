# FORGE Plugin Wrapper Templates

This document provides ready-to-use templates for wrapping existing tools as FORGE plugins without modifying the external tool.

## When to Use Wrappers

Use a wrapper when:
- External tool is maintained elsewhere and you don't want to add FORGE dependencies
- Tool is written in another language (Go, Rust, shell scripts)
- Tool is proprietary or closed-source
- You want to test FORGE integration before committing to native implementation

---

## Template 1: Python Library Wrapper

For tools that provide a Python API you can import.

### Project Structure

```
forge-mytool-wrapper/
├── pyproject.toml
├── README.md
└── src/
    └── forge_mytool_wrapper/
        ├── __init__.py
        └── plugin.py
```

### pyproject.toml

```toml
[project]
name = "forge-mytool-wrapper"
version = "1.0.0"
description = "FORGE wrapper for MyTool"
requires-python = ">=3.12"
license = { text = "Apache-2.0" }

dependencies = [
    "forge-core>=0.1.0",
    # External tool as git dependency
    "mytool @ git+https://github.com/your-org/mytool.git@v2.0.0",
]

# IMPORTANT: use a namespaced module path — never "forge_plugin:create_plugin" (top-level
# collision risk). "forge_mytool_wrapper.plugin:create_plugin" is correct.
[project.entry-points."forge.plugins"]
mytool = "forge_mytool_wrapper.plugin:create_plugin"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

### \_\_init\_\_.py

```python
"""FORGE wrapper for MyTool."""

from forge_mytool_wrapper.plugin import MyToolPlugin


def create_plugin():
    """Factory function for plugin discovery."""
    return MyToolPlugin()


__all__ = ["create_plugin", "MyToolPlugin"]
```

### plugin.py

```python
"""FORGE plugin adapter for MyTool.

This wrapper provides FORGE integration for MyTool without requiring
any modifications to the MyTool codebase.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from forge_core.context import ExecutionContext
from forge_core.plugin import ResultStatus, ToolParam, ToolPlugin, ToolResult

# Import from external tool
from mytool import MyTool, MyToolConfig, MyToolError


class MyToolPlugin:
    """FORGE wrapper for MyTool."""

    name = "mytool"
    description = "MyTool functionality via FORGE"
    version = "1.0.0"
    requires_auth = False  # Set True if your wrapper needs a chainctl token

    def get_params(self) -> list[ToolParam]:
        """Declare parameters that map to MyTool's interface."""
        return [
            # Required parameters
            ToolParam(
                name="input",
                description="Input file or directory to process",
                required=True,
            ),
            # Optional parameters with defaults
            ToolParam(
                name="output",
                description="Output directory",
                default="./output",
            ),
            ToolParam(
                name="format",
                description="Output format",
                choices=["json", "yaml", "text"],
                default="json",
            ),
            # Boolean flags
            ToolParam(
                name="verbose",
                description="Enable verbose output",
                type="bool",
                default=False,
            ),
            # Numeric parameters
            ToolParam(
                name="max-items",
                description="Maximum items to process (0 = unlimited)",
                type="int",
                default=0,
            ),
        ]

    def run(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        """Execute MyTool via wrapper.

        Args:
            args: Parameter values from FORGE CLI/API
            ctx: Execution context (auth, progress, cancellation)

        Returns:
            ToolResult with status, summary, and artifacts
        """
        input_path = Path(args["input"])
        output_dir = Path(args["output"])
        output_format = args["format"]
        verbose = args["verbose"]
        max_items = args["max-items"]

        # Validate inputs
        if not input_path.exists():
            return ToolResult(
                status=ResultStatus.FAILURE,
                summary=f"Input path not found: {input_path}",
            )

        # Create output directory
        output_dir.mkdir(parents=True, exist_ok=True)

        # Report progress
        ctx.progress(0.0, f"Initializing MyTool for {input_path}")

        try:
            # Translate FORGE args to MyTool's configuration
            config = MyToolConfig(
                input=str(input_path),
                output=str(output_dir),
                format=output_format,
                verbose=verbose,
                limit=max_items if max_items > 0 else None,
            )

            # Initialize external tool
            tool = MyTool(config)

            ctx.progress(0.2, "Processing with MyTool...")

            # Check for cancellation before expensive operation
            if ctx.is_cancelled:
                return ToolResult(
                    status=ResultStatus.CANCELLED,
                    summary="Operation cancelled by user",
                )

            # Execute external tool
            result = tool.execute()

            ctx.progress(0.8, "Finalizing results...")

            # Save results if tool doesn't do it automatically
            output_file = output_dir / f"results.{output_format}"
            with open(output_file, "w") as f:
                if output_format == "json":
                    json.dump(result.to_dict(), f, indent=2)
                elif output_format == "yaml":
                    import yaml
                    yaml.dump(result.to_dict(), f)
                else:
                    f.write(str(result))

            ctx.progress(1.0, "Complete")

            # Translate external result to FORGE format
            return ToolResult(
                status=ResultStatus.SUCCESS,
                summary=f"Processed {result.items_processed} items successfully",
                data={
                    "items_processed": result.items_processed,
                    "items_skipped": result.items_skipped,
                    "warnings": result.warnings,
                },
                artifacts={
                    "results": str(output_file),
                    # Include any other files the tool created
                    **{
                        name: str(path)
                        for name, path in result.output_files.items()
                    },
                },
            )

        except MyToolError as e:
            # Handle known errors from external tool
            return ToolResult(
                status=ResultStatus.FAILURE,
                summary=f"MyTool error: {e.message}",
                data={"error_code": e.code, "details": e.details},
            )

        except Exception as e:
            # Catch-all for unexpected errors
            return ToolResult(
                status=ResultStatus.FAILURE,
                summary=f"Unexpected error: {str(e)}",
            )


def create_plugin() -> ToolPlugin:
    """Factory function for FORGE plugin discovery."""
    return MyToolPlugin()
```

---

## Template 2: CLI Wrapper (Subprocess)

For tools that are standalone executables (Go binaries, shell scripts, etc.).

### plugin.py

```python
"""FORGE wrapper for external CLI tool."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from forge_core.context import ExecutionContext
from forge_core.plugin import ResultStatus, ToolParam, ToolPlugin, ToolResult


class CLIToolPlugin:
    """FORGE wrapper for external CLI tool."""

    name = "cli-tool"
    description = "External CLI tool via FORGE"
    version = "1.0.0"
    requires_auth = False

    def get_params(self) -> list[ToolParam]:
        """Declare parameters that map to CLI flags."""
        return [
            ToolParam(
                name="input",
                description="Input file to process",
                required=True,
            ),
            ToolParam(
                name="output",
                description="Output file path",
                default="output.json",
            ),
            ToolParam(
                name="format",
                description="Output format",
                choices=["json", "text", "csv"],
                default="json",
            ),
            ToolParam(
                name="verbose",
                description="Enable verbose logging",
                type="bool",
                default=False,
            ),
            ToolParam(
                name="threads",
                description="Number of parallel threads",
                type="int",
                default=4,
            ),
        ]

    def run(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        """Execute external CLI tool via subprocess.

        Args:
            args: Parameter values from FORGE
            ctx: Execution context

        Returns:
            ToolResult with status and output
        """
        # Build command
        cmd = [
            "mytool",  # Must be in PATH, or use absolute path
            "--input", args["input"],
            "--output", args["output"],
            "--format", args["format"],
            "--threads", str(args["threads"]),
        ]

        # Add boolean flags
        if args["verbose"]:
            cmd.append("--verbose")

        ctx.progress(0.1, "Launching external CLI tool...")

        try:
            # Execute command
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,  # Don't raise on non-zero exit
                timeout=300,  # 5 minute timeout
            )

            ctx.progress(0.9, "Processing results...")

            # Check exit code
            if result.returncode == 0:
                # Parse output if JSON
                data = {}
                if args["format"] == "json" and Path(args["output"]).exists():
                    try:
                        with open(args["output"]) as f:
                            data = json.load(f)
                    except json.JSONDecodeError:
                        pass

                return ToolResult(
                    status=ResultStatus.SUCCESS,
                    summary=result.stdout.strip() or "Command completed successfully",
                    data=data,
                    artifacts={"output": args["output"]},
                )
            else:
                return ToolResult(
                    status=ResultStatus.FAILURE,
                    summary=f"Command failed with exit code {result.returncode}",
                    data={
                        "exit_code": result.returncode,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                    },
                )

        except subprocess.TimeoutExpired:
            return ToolResult(
                status=ResultStatus.FAILURE,
                summary="Command timed out after 5 minutes",
            )

        except FileNotFoundError:
            return ToolResult(
                status=ResultStatus.FAILURE,
                summary="CLI tool 'mytool' not found in PATH",
                data={
                    "hint": "Install mytool and ensure it's in your PATH",
                },
            )

        except Exception as e:
            return ToolResult(
                status=ResultStatus.FAILURE,
                summary=f"Unexpected error: {str(e)}",
            )


def create_plugin() -> ToolPlugin:
    """Factory function for FORGE plugin discovery."""
    return CLIToolPlugin()
```

---

## Template 3: Hybrid Wrapper (Library + CLI Fallback)

For tools that provide both Python API and CLI, with graceful fallback.

### plugin.py

```python
"""FORGE wrapper with library + CLI fallback."""

from __future__ import annotations

import subprocess
from typing import Any

from forge_core.context import ExecutionContext
from forge_core.plugin import ResultStatus, ToolParam, ToolPlugin, ToolResult

# Try to import library, but don't fail if unavailable
try:
    from mytool import MyTool
    HAS_LIBRARY = True
except ImportError:
    HAS_LIBRARY = False


class HybridToolPlugin:
    """FORGE wrapper with library + CLI fallback."""

    name = "hybrid-tool"
    description = "Hybrid tool with library and CLI support"
    version = "1.0.0"
    requires_auth = False

    def get_params(self) -> list[ToolParam]:
        return [
            ToolParam(name="input", description="Input file", required=True),
            ToolParam(name="output", description="Output file", default="output.json"),
            ToolParam(
                name="prefer-cli",
                description="Prefer CLI over library",
                type="bool",
                default=False,
            ),
        ]

    def run(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        """Execute tool, preferring library but falling back to CLI."""
        prefer_cli = args.get("prefer-cli", False)

        if HAS_LIBRARY and not prefer_cli:
            # Use library if available and not explicitly disabled
            return self._run_library(args, ctx)
        else:
            # Fall back to CLI
            return self._run_cli(args, ctx)

    def _run_library(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        """Run via Python library."""
        try:
            ctx.progress(0.2, "Running via Python library...")

            tool = MyTool(input=args["input"], output=args["output"])
            result = tool.execute()

            return ToolResult(
                status=ResultStatus.SUCCESS,
                summary=f"Processed {result.count} items via library",
                data={"count": result.count, "method": "library"},
                artifacts={"output": args["output"]},
            )

        except Exception as e:
            # If library fails, try CLI as fallback
            ctx.progress(0.3, "Library failed, trying CLI...")
            return self._run_cli(args, ctx)

    def _run_cli(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        """Run via CLI subprocess."""
        try:
            ctx.progress(0.2, "Running via CLI...")

            cmd = ["mytool", "--input", args["input"], "--output", args["output"]]

            result = subprocess.run(cmd, capture_output=True, text=True, check=False)

            if result.returncode == 0:
                return ToolResult(
                    status=ResultStatus.SUCCESS,
                    summary=f"Command completed via CLI",
                    data={"method": "cli", "stdout": result.stdout},
                    artifacts={"output": args["output"]},
                )
            else:
                return ToolResult(
                    status=ResultStatus.FAILURE,
                    summary=f"CLI failed: {result.stderr}",
                    data={"method": "cli", "exit_code": result.returncode},
                )

        except FileNotFoundError:
            return ToolResult(
                status=ResultStatus.FAILURE,
                summary="Neither library nor CLI available for mytool",
            )


def create_plugin() -> ToolPlugin:
    return HybridToolPlugin()
```

---

## Template 4: HTTP API Wrapper

For tools that provide HTTP/REST APIs.

### plugin.py

```python
"""FORGE wrapper for HTTP API tool."""

from __future__ import annotations

import json
from typing import Any

import requests

from forge_core.context import ExecutionContext
from forge_core.plugin import ResultStatus, ToolParam, ToolPlugin, ToolResult


class APIToolPlugin:
    """FORGE wrapper for HTTP API."""

    name = "api-tool"
    description = "Tool with HTTP API"
    version = "1.0.0"
    requires_auth = False  # Set True if you want FORGE to inject a chainctl token

    def get_params(self) -> list[ToolParam]:
        return [
            ToolParam(
                name="endpoint",
                description="API endpoint URL",
                default="https://api.example.com",
            ),
            ToolParam(
                name="resource",
                description="Resource to query",
                required=True,
            ),
            ToolParam(
                name="api-key",
                description="API authentication key",
            ),
            ToolParam(
                name="timeout",
                description="Request timeout in seconds",
                type="int",
                default=30,
            ),
        ]

    def run(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        """Execute API request."""
        endpoint = args["endpoint"].rstrip("/")
        resource = args["resource"]
        api_key = args.get("api-key")
        timeout = args["timeout"]

        url = f"{endpoint}/{resource}"

        # Build headers
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        ctx.progress(0.2, f"Querying {url}...")

        try:
            response = requests.get(url, headers=headers, timeout=timeout)

            ctx.progress(0.8, "Processing response...")

            if response.ok:
                data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {"text": response.text}

                return ToolResult(
                    status=ResultStatus.SUCCESS,
                    summary=f"API request successful (HTTP {response.status_code})",
                    data=data,
                )
            else:
                return ToolResult(
                    status=ResultStatus.FAILURE,
                    summary=f"API request failed (HTTP {response.status_code})",
                    data={
                        "status_code": response.status_code,
                        "error": response.text,
                    },
                )

        except requests.Timeout:
            return ToolResult(
                status=ResultStatus.FAILURE,
                summary=f"Request timed out after {timeout}s",
            )

        except requests.RequestException as e:
            return ToolResult(
                status=ResultStatus.FAILURE,
                summary=f"Request error: {str(e)}",
            )


def create_plugin() -> ToolPlugin:
    return APIToolPlugin()
```

---

## Installation & Testing

### Create Wrapper Repository

```bash
# Create repository
mkdir forge-mytool-wrapper
cd forge-mytool-wrapper

# Copy template files
cp path/to/template/pyproject.toml .
cp path/to/template/plugin.py src/forge_mytool_wrapper/

# Initialize git
git init
git add .
git commit -m "Initial wrapper implementation"
git remote add origin git@github.com:your-org/forge-mytool-wrapper.git
git push -u origin main

# Tag release
git tag -a v1.0.0 -m "Initial release"
git push --tags
```

### Test Locally

```bash
# Install in development mode
uv pip install -e .

# Verify discovery
forge --help

# Test execution
forge mytool --help
forge mytool --input test.txt
```

### Add to Registry

```yaml
external_plugins:
  mytool:
    package: "forge-mytool-wrapper"
    source: "git+ssh://git@github.com/your-org/forge-mytool-wrapper.git"
    ref: "v1.0.0"
    description: "MyTool wrapped for FORGE"
    plugin_type: "wrapper"
    tags: [tools]
    private: true
```

---

## Best Practices

### 1. Minimal Dependencies

Only include `forge-core` and the external tool - avoid adding unnecessary dependencies.

### 2. Error Translation

Translate external tool errors to meaningful FORGE ToolResults:

```python
try:
    result = external_tool.run()
except ExternalToolError as e:
    return ToolResult(
        status=ResultStatus.FAILURE,
        summary=f"External tool error: {e.user_friendly_message}",
        data={"error_code": e.code},  # Structured data for API consumers
    )
```

### 3. Progress Reporting

Even simple wrappers should report progress:

```python
ctx.progress(0.0, "Starting...")
# ... do work ...
ctx.progress(1.0, "Complete")
```

### 4. Versioning

- Wrapper version: Reflects wrapper code changes
- External tool version: Pinned in `pyproject.toml` dependencies

```toml
# Wrapper is v1.0.0, external tool is v2.5.0
[project]
name = "forge-mytool-wrapper"
version = "1.0.0"

dependencies = [
    "mytool @ git+https://github.com/org/mytool.git@v2.5.0",
]
```

### 5. Documentation

Include in wrapper README:
- Which version of external tool is wrapped
- Any external tool prerequisites (system dependencies, environment setup)
- Differences from direct usage of external tool

---

## Troubleshooting

### External Tool Not Found

For CLI wrappers, ensure tool is in PATH or use absolute path:

```python
# Check if tool exists
import shutil

tool_path = shutil.which("mytool")
if not tool_path:
    return ToolResult(
        status=ResultStatus.FAILURE,
        summary="External tool 'mytool' not found in PATH",
    )
```

### Dependency Conflicts

If external tool has conflicting dependencies, isolate in wrapper:

```bash
# Install wrapper in separate environment
uv venv wrapper-env
source wrapper-env/bin/activate
uv pip install -e .
```

### Authentication Issues

For private external tool repos:

```bash
# Test git access
git clone git@github.com:org/external-tool.git

# Ensure SSH key is configured
ssh -T git@github.com
```

---

## Template 5: Non-Python CLI Wrapper (with `system_deps`)

For tools written in Go, TypeScript/Node.js, or other non-Python languages where the upstream
binary cannot be declared as a Python dependency in `pyproject.toml`. The binary is installed
automatically when the user runs `forge plugin install`.

> For a full walkthrough including cross-platform notes and testing patterns, see
> [NON_PYTHON_WRAPPER_GUIDE.md](./NON_PYTHON_WRAPPER_GUIDE.md).

### pyproject.toml

```toml
[project]
name = "forge-mytool-wrapper"
version = "1.0.0"
description = "FORGE wrapper for mytool (Go/Node.js binary)"
requires-python = ">=3.12"
license = { text = "Apache-2.0" }

dependencies = [
    "forge-core>=0.1.0",
    # No upstream dep here — binary is installed via system_deps in registry
]

# IMPORTANT: use a namespaced module path — never "forge_plugin:create_plugin"
[project.entry-points."forge.plugins"]
mytool = "forge_mytool_wrapper.plugin:create_plugin"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

### plugin.py

```python
"""FORGE wrapper for mytool (non-Python CLI)."""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

from forge_core.context import ExecutionContext
from forge_core.plugin import ResultStatus, ToolParam, ToolPlugin, ToolResult

REQUIRED_TOOLS = ["mytool"]


def assert_dependencies() -> None:
    missing = [t for t in REQUIRED_TOOLS if not shutil.which(t)]
    if missing:
        raise RuntimeError(
            f"Missing required tools: {', '.join(missing)}\n"
            "Run `forge plugin install mytool` to install."
        )


class MyToolPlugin:
    name = "mytool"
    description = "Wraps the mytool binary"
    version = "1.0.0"
    requires_auth = False

    def get_params(self) -> list[ToolParam]:
        return [
            ToolParam(name="input", description="Input to process", required=True),
            ToolParam(name="verbose", description="Verbose output", type="bool", default=False),
        ]

    def run(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        assert_dependencies()

        cmd = self._build_cmd(args)
        ctx.progress(0.1, f"Running mytool on {args['input']}...")

        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            return ToolResult(
                status=ResultStatus.SUCCESS,
                summary=result.stdout.strip() or "Completed successfully",
                data={"stdout": result.stdout},
            )
        return ToolResult(
            status=ResultStatus.FAILURE,
            summary=f"mytool failed (exit {result.returncode})",
            data={"stderr": result.stderr},
        )

    def _build_cmd(self, args: dict[str, Any]) -> list[str]:
        cmd = ["mytool", args["input"]]
        if args.get("verbose"):
            cmd.append("--verbose")
        return cmd


def create_plugin() -> ToolPlugin:
    return MyToolPlugin()
```

### Registry YAML snippet

```yaml
external_plugins:
  mytool:
    package: "forge-mytool-wrapper"
    source: "git+https://github.com/your-org/forge-mytool-wrapper.git"
    ref: "v1.0.0"
    description: "Wraps the mytool binary"
    plugin_type: "wrapper"
    tags: [tools]
    private: false
    system_deps:
      # Go example:
      - manager: "go"
        package: "github.com/your-org/mytool/cmd/mytool@v1.2.3"
        binary: "mytool"
      # Node.js / TypeScript example (use one or the other):
      # - manager: "npm"
      #   package: "@your-org/mytool@2.0.0"
      #   binary: "mytool"
      # Pre-built GitHub Release binary (public or private repo):
      # - manager: "github_release"
      #   repo: "your-org/mytool"
      #   tag: "v1.2.3"
      #   asset: "mytool_{os}_{arch}"   # {os}=darwin/linux, {arch}=amd64/arm64
      #   binary: "mytool"
      #   install_dir: "~/.local/bin"
```

---

## Next Steps

1. Choose appropriate template for your external tool
2. Customize `get_params()` to match tool's interface
3. Implement `run()` to translate FORGE args to tool's API
4. Test locally: `uv pip install -e . && forge mytool --help`
5. Push to git and add to FORGE registry
6. Install via FORGE: `forge plugin install mytool`
