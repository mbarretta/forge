# FORGE Plugin Migration Guide

This document is a self-contained recipe for converting any existing tool into a FORGE plugin. It contains everything needed — protocol definitions, file templates, conversion rules, and validation steps — so that an LLM can read this document alone and produce all necessary code to migrate a tool into the FORGE monorepo.

---

## Table of Contents

1. [Prerequisites: What You Need Before Starting](#1-prerequisites)
2. [The Plugin Protocol (exact code to implement)](#2-the-plugin-protocol)
3. [Step-by-Step Migration Procedure](#3-step-by-step-migration-procedure)
4. [Conversion Rules Reference](#4-conversion-rules-reference)
5. [Complete File Templates](#5-complete-file-templates)
6. [Worked Examples](#6-worked-examples)
7. [Validation Checklist](#7-validation-checklist)

---

## 1. Prerequisites

Before starting a migration, gather this information about the source tool:

| Item | Where to Find It | Why It's Needed |
|------|------------------|-----------------|
| **Language** | File extensions, build files | Must be Python 3.12+. Non-Python tools require a Python wrapper |
| **Entry point** | `main()` function, `if __name__ == "__main__"` block, `console_scripts` in setup.py/pyproject.toml | Becomes the body of `plugin.run()` |
| **CLI arguments** | argparse setup, click decorators, sys.argv parsing | Each argument becomes a `ToolParam` |
| **Dependencies** | requirements.txt, setup.py `install_requires`, pyproject.toml `dependencies` | Goes into the plugin's `pyproject.toml` |
| **External CLI tools** | `subprocess.run()` calls, `shutil.which()` checks | Declared in plugin for dependency checking |
| **Output files** | File writes, CSV/YAML/JSON/HTML generation | Become `ToolResult.artifacts` |
| **Progress indicators** | Print statements in loops, progress bars, counters | Become `ctx.progress()` calls |
| **Authentication** | Token fetching, `chainctl auth`, API key env vars | Use `ctx.auth_token` or `ctx.config` |
| **Interactive prompts** | `input()` calls, user selection menus | Must be eliminated — all inputs become `ToolParam` declarations |

### Required FORGE Monorepo Structure

The tool will be added to the existing FORGE monorepo at `forge/packages/forge-<name>/`. The monorepo has this relevant structure:

```
forge/
├── pyproject.toml                          # uv workspace — you will add your package here
├── packages/
│   ├── forge-core/                         # provides: ToolPlugin, ToolParam, ToolResult, ExecutionContext
│   │   └── src/forge_core/
│   │       ├── plugin.py                   # ToolPlugin protocol
│   │       ├── context.py                  # ExecutionContext
│   │       ├── registry.py                 # plugin discovery
│   │       ├── auth.py                     # get_chainctl_token()
│   │       └── deps.py                     # assert_dependencies()
│   ├── forge-cli/                          # auto-discovers and runs your plugin
│   └── forge-api/                          # auto-discovers and serves your plugin via HTTP
```

---

## 2. The Plugin Protocol

Every FORGE plugin must implement three attributes and two methods. Here is the exact protocol definition from `forge-core`:

### 2.1 ToolPlugin Protocol

```python
from __future__ import annotations
from typing import Any, Protocol, runtime_checkable

@runtime_checkable
class ToolPlugin(Protocol):
    """Every FORGE tool must implement this interface."""

    name: str               # CLI subcommand name (e.g., "gauge", "provenance")
    description: str        # One-line help text
    version: str            # Semver string (e.g., "1.0.0")

    def get_params(self) -> list[ToolParam]:
        """Declare parameters the tool accepts. Called once at startup."""
        ...

    def run(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        """Execute the tool. Called each time a user invokes the tool."""
        ...
```

### 2.2 ToolParam (parameter declaration)

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class ToolParam:
    """Declares a single parameter.

    The CLI uses this to generate argparse flags.
    The API uses this to generate Pydantic request schemas.
    The UI uses this to render form fields.
    """
    name: str                           # Flag name: becomes --name in CLI, "name" key in JSON
    description: str                    # Help text
    type: str = "str"                   # One of: "str", "int", "float", "bool"
    required: bool = False              # If True, CLI and API enforce presence
    default: Any = None                 # Default value when not provided
    choices: list[str] | None = None    # If set, value must be one of these
```

### 2.3 ToolResult (return value)

```python
from dataclasses import dataclass, field
from enum import Enum

class ResultStatus(Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"
    CANCELLED = "cancelled"

@dataclass(frozen=True)
class ToolResult:
    """Returned by plugin.run()."""
    status: ResultStatus                            # Overall outcome
    summary: str                                    # Human-readable one-line summary
    data: dict[str, Any] = field(default_factory=dict)       # Structured output (JSON-serializable)
    artifacts: dict[str, str] = field(default_factory=dict)  # name → file_path for generated files
```

### 2.4 ExecutionContext (provided to run())

```python
from dataclasses import dataclass, field
import threading
from typing import Callable

@dataclass
class ExecutionContext:
    """Provided by FORGE to every plugin.run() call."""
    auth_token: str = ""                                           # Chainguard token (pre-fetched)
    config: dict = field(default_factory=dict)                     # Extra config from env/settings
    on_progress: Callable[[float, str], None] = field(default=lambda f, m: None)
    cancel_event: threading.Event = field(default_factory=threading.Event)

    def progress(self, fraction: float, message: str) -> None:
        """Report progress. fraction is 0.0 to 1.0."""
        self.on_progress(fraction, message)

    @property
    def is_cancelled(self) -> bool:
        """Check if the user requested cancellation."""
        return self.cancel_event.is_set()
```

### 2.5 Available Helpers from forge-core

You may import and use these in your plugin:

```python
from forge_core.auth import get_chainctl_token       # Returns str, raises RuntimeError
from forge_core.auth import check_tool_available      # Returns bool
from forge_core.deps import assert_dependencies       # Raises RuntimeError if tools missing
from forge_core.deps import check_dependencies        # Returns list[DependencyCheck]
```

---

## 3. Step-by-Step Migration Procedure

Follow these steps in order. Each step produces specific files.

### Step 1: Choose the Plugin Name

The name must be:
- Lowercase alphanumeric with hyphens (for the package: `forge-<name>`)
- Lowercase alphanumeric with underscores (for the Python module: `forge_<name>`)
- A short, memorable CLI subcommand (for `plugin.name`: `<name>`)

Examples:
| Source Tool | Package Name | Module Name | CLI Name |
|-------------|-------------|-------------|----------|
| verify-provenance | forge-provenance | forge_provenance | provenance |
| ils-fetcher | forge-ils | forge_ils | ils |
| gauge | forge-gauge | forge_gauge | gauge |
| my-new-tool | forge-mytool | forge_mytool | mytool |

### Step 2: Create the Package Directory

```
packages/forge-<name>/
├── pyproject.toml
└── src/forge_<name>/
    ├── __init__.py
    ├── plugin.py
    └── ... (source modules from the original tool)
```

### Step 3: Write pyproject.toml

Use the template from [section 5.1](#51-pyprojecttoml). Fill in:
- `name`: `"forge-<name>"`
- `description`: one-line from the source tool's README or module docstring
- `dependencies`: copy from source tool's requirements.txt / pyproject.toml / setup.py, plus `"forge-core"`
- Entry point key: the CLI subcommand name

### Step 4: Copy Source Code

Copy the source tool's Python modules into `src/forge_<name>/`. Apply these transformations:

1. **Rename entry module**: If the tool is a single file (`tool.py`), rename it to `core.py`.
2. **Fix imports**: All internal imports must be updated to the new package path. See [section 4.1](#41-import-rewriting-rules).
3. **Remove entry point**: Delete `main()`, `if __name__ == "__main__"` blocks, and all argparse setup from the copied source. That logic moves to `plugin.py`.
4. **Remove sys.exit() calls**: Replace with exceptions or return values. See [section 4.3](#43-exit-and-error-handling).
5. **Remove interactive prompts**: Replace `input()` with required parameters. See [section 4.6](#46-interactive-prompts).

### Step 5: Write plugin.py

This is the adapter between the existing tool logic and the FORGE protocol. See the template in [section 5.3](#53-pluginpy).

1. **Map CLI arguments to ToolParam**: See [section 4.2](#42-argument-mapping-rules).
2. **Implement run()**: Call the existing tool functions, threading `ctx.progress()` and `ctx.is_cancelled` through the execution path. See [section 4.4](#44-progress-reporting) and [section 4.5](#45-cancellation).
3. **Map outputs to ToolResult**: See [section 4.7](#47-output-mapping).

### Step 6: Write __init__.py

Use the template from [section 5.2](#52-initpy). This is always the same pattern — just change the class name.

### Step 7: Register in Workspace

Add the package to the root `pyproject.toml` in two places:

1. Add to workspace members:

```toml
[tool.uv.workspace]
members = [
    # ... existing members ...
    "packages/forge-<name>",
]
```

2. Add to root package dependencies so `uv tool install forge` includes this plugin:

```toml
[project]
dependencies = [
    "forge-cli",
    # ... existing plugins ...
    "forge-<name>",
]
```

### Step 8: Install and Verify

```bash
uv sync
forge <name> --help       # should show params from get_params()
forge <name> <args>       # should execute the tool
```

---

## 4. Conversion Rules Reference

### 4.1 Import Rewriting Rules

Every internal import in the source tool must be rewritten to use the new package path.

**Rule: Prefix all internal imports with `forge_<name>.`**

| Source Import | Converted Import |
|--------------|-----------------|
| `from core.models import Foo` | `from forge_<name>.core.models import Foo` |
| `from utils.helpers import bar` | `from forge_<name>.utils.helpers import bar` |
| `import constants` | `from forge_<name> import constants` |
| `from constants import __version__` | `from forge_<name>.constants import __version__` |
| `from . import utils` | `from forge_<name> import utils` |
| `from plugins.core import CorePlugin` | `from forge_<name>.plugins.core import CorePlugin` |

**External imports (stdlib, third-party) are unchanged.**

If the source tool uses `sys.path` manipulation for imports, remove that and use proper package imports instead.

### 4.2 Argument Mapping Rules

Convert each CLI argument to a `ToolParam`. Use this table:

| argparse Pattern | ToolParam Equivalent |
|-----------------|---------------------|
| `parser.add_argument("--org", required=True, help="Organization")` | `ToolParam(name="org", description="Organization", required=True)` |
| `parser.add_argument("--limit", type=int, default=0, help="Max items")` | `ToolParam(name="limit", description="Max items", type="int", default=0)` |
| `parser.add_argument("--verbose", action="store_true", help="Verbose")` | `ToolParam(name="verbose", description="Verbose output", type="bool")` |
| `parser.add_argument("--format", choices=["json","csv"], default="csv")` | `ToolParam(name="format", description="Output format", choices=["json","csv"], default="csv")` |
| `parser.add_argument("-i", "--input", required=True)` | `ToolParam(name="input", description="Input file path", required=True)` |
| `parser.add_argument("--skip-sbom", action="store_true")` | `ToolParam(name="skip-sbom", description="Skip SBOM downloads", type="bool")` |
| `parser.add_argument("positional_arg")` | `ToolParam(name="positional-arg", description="...", required=True)` |

**Rules:**
- Drop short flags (`-i`, `-o`). FORGE only uses long flags.
- Hyphens in names are fine: `--skip-sbom` → `name="skip-sbom"`. The CLI framework handles it.
- `store_true` / `store_false` → `type="bool"`.
- `type=int` → `type="int"`. `type=float` → `type="float"`. Everything else → `type="str"`.
- `nargs` is NOT supported. If the source uses `nargs="+"` or `nargs="*"`, convert to a comma-separated string parameter and split in `run()`.
- `action="count"` (e.g., `-vvv`) → convert to `type="int"` with a description like "Verbosity level (0-3)".
- Mutually exclusive groups → convert to a single `choices` parameter.
- Subcommands → convert to a `ToolParam(name="command", choices=[...], required=True)`.

**Accessing args in run():**
```python
def run(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
    # Args are accessed by ToolParam.name as the key
    org = args["org"]                    # required str
    limit = args.get("limit", 0)         # optional int with default
    verbose = args.get("verbose", False)  # bool flag
    skip_sbom = args.get("skip-sbom", False)  # hyphenated name, accessed with hyphen
```

### 4.3 Exit and Error Handling

**Rule: Never call `sys.exit()` inside plugin code. Never call `sys.exit()` inside any module imported by the plugin.**

| Source Pattern | Converted Pattern |
|---------------|------------------|
| `sys.exit(1)` | `return ToolResult(status=ResultStatus.FAILURE, summary="Error message")` |
| `sys.exit(0)` | `return ToolResult(status=ResultStatus.SUCCESS, summary="Done")` |
| `print("Error: ...", file=sys.stderr); sys.exit(1)` | `return ToolResult(status=ResultStatus.FAILURE, summary="Error: ...")` |
| `parser.error("missing --org")` | Handled automatically — `required=True` in ToolParam |

For functions called by `run()` that currently call `sys.exit()`:
- Replace `sys.exit(1)` with `raise RuntimeError("descriptive message")`
- Catch in `run()` and return appropriate `ToolResult`

```python
# BEFORE (in source tool)
def get_images(org):
    if not org:
        print("Error: no org", file=sys.stderr)
        sys.exit(1)
    ...

# AFTER (in forge plugin)
def get_images(org: str) -> list[str]:
    if not org:
        raise RuntimeError("No organization specified")
    ...

def run(self, args, ctx):
    try:
        images = get_images(args["org"])
    except RuntimeError as e:
        return ToolResult(status=ResultStatus.FAILURE, summary=str(e))
```

### 4.4 Progress Reporting

**Rule: Replace print-based progress with `ctx.progress(fraction, message)`.**

The `fraction` parameter is a float from 0.0 to 1.0. The `message` parameter is a short human-readable string.

| Source Pattern | Converted Pattern |
|---------------|------------------|
| `print(f"Processing {i}/{total}")` | `ctx.progress(i / total, f"Processing item {i}/{total}")` |
| `print(f"Step 1: Fetching images...")` | `ctx.progress(0.1, "Fetching images")` |
| `print(f"Completed [{n}/{total}]: {name}")` | `ctx.progress(n / total, f"Completed: {name}")` |
| `tqdm(items)` loop | Remove tqdm; add `ctx.progress()` inside loop |
| No progress at all | Add `ctx.progress(0.0, "Starting")` at start and `ctx.progress(1.0, "Done")` before return |

**For tools with distinct phases** (e.g., fetch → process → export), divide the 0.0-1.0 range:
```python
ctx.progress(0.0, "Fetching image list")
images = get_images(org)

ctx.progress(0.2, f"Processing {len(images)} images")
for i, img in enumerate(images):
    process(img)
    ctx.progress(0.2 + 0.7 * (i + 1) / len(images), f"Processed {img}")

ctx.progress(0.9, "Writing report")
write_report(results)

ctx.progress(1.0, "Done")
```

**For ThreadPoolExecutor/concurrent workloads**, use a thread-safe counter:
```python
import threading

completed = 0
lock = threading.Lock()
total = len(items)

def on_complete(item_name: str) -> None:
    nonlocal completed
    with lock:
        completed += 1
        ctx.progress(completed / total, f"Completed: {item_name}")

with ThreadPoolExecutor(max_workers=10) as executor:
    futures = {executor.submit(process, item): item for item in items}
    for future in as_completed(futures):
        item = futures[future]
        result = future.result()
        on_complete(item)
```

### 4.5 Cancellation

**Rule: Check `ctx.is_cancelled` in every loop body and every long-running phase.**

```python
for i, item in enumerate(items):
    if ctx.is_cancelled:
        return ToolResult(status=ResultStatus.CANCELLED, summary="Cancelled by user")
    process(item)
    ctx.progress((i + 1) / len(items), f"Processing {item}")
```

For `ThreadPoolExecutor`, check cancellation between futures:
```python
for future in as_completed(futures):
    if ctx.is_cancelled:
        executor.shutdown(wait=False, cancel_futures=True)
        return ToolResult(status=ResultStatus.CANCELLED, summary="Cancelled by user")
    result = future.result()
```

### 4.6 Interactive Prompts

**Rule: All `input()` calls must be removed. Every user input becomes a ToolParam.**

| Source Pattern | Converted Pattern |
|---------------|------------------|
| `org = input("Enter organization: ")` | `ToolParam(name="org", description="Organization", required=True)` |
| Selection menu: "Choose 1-N" | `ToolParam(name="org", description="Organization name or ID", required=True)` |
| `confirm = input("Continue? [y/N]")` | Remove entirely, or add `ToolParam(name="confirm", type="bool", default=True)` |
| `password = getpass()` | Use `ctx.auth_token` or `ctx.config["api_key"]` |

If the tool has a "list then select" pattern (e.g., list orgs then ask user to pick one), split into two approaches:
- Make the selection parameter required (user provides the value directly)
- Optionally, create a second ToolParam (e.g., `list-orgs`) that, when true, just lists available options and returns without doing work

### 4.7 Output Mapping

**Rule: Structured data goes in `ToolResult.data`. Generated files go in `ToolResult.artifacts`. The one-line human summary goes in `ToolResult.summary`.**

| Source Output | ToolResult Field |
|--------------|-----------------|
| `print(f"Found {n} vulnerabilities")` | `summary="Found 42 vulnerabilities in 10 images"` |
| Writes `report.csv` to disk | `artifacts={"report": "/path/to/report.csv"}` |
| Writes `output.yaml` to disk | `artifacts={"report": "/path/to/output.yaml"}` |
| Writes multiple SBOMs to disk | `artifacts={"sbom-image1": "/path/1.json", "sbom-image2": "/path/2.json"}` |
| Prints a summary table to stdout | Put structured data in `data={"results": [...]}` |
| Returns exit code 0 | `status=ResultStatus.SUCCESS` |
| Returns exit code 1 | `status=ResultStatus.FAILURE` |

**`data` must be JSON-serializable.** No custom objects, no datetime objects (convert to ISO strings), no Path objects (convert to strings).

```python
# BEFORE
print(f"Processed {len(results)} images")
print(f"Verified: {verified_count}")
print(f"Failed: {failed_count}")
with open("results.csv", "w") as f:
    writer = csv.writer(f)
    ...
sys.exit(0 if failed_count == 0 else 1)

# AFTER
return ToolResult(
    status=ResultStatus.SUCCESS if failed_count == 0 else ResultStatus.PARTIAL,
    summary=f"Processed {len(results)} images: {verified_count} verified, {failed_count} failed",
    data={
        "total": len(results),
        "verified": verified_count,
        "failed": failed_count,
        "results": [{"image": r.image, "status": r.status} for r in results],
    },
    artifacts={"report": str(csv_path)},
)
```

### 4.8 Authentication

**Rule: Use `ctx.auth_token` for Chainguard API tokens. Use `ctx.config` for other credentials.**

| Source Pattern | Converted Pattern |
|---------------|------------------|
| `token = run_chainctl(["auth", "token"])` | `token = ctx.auth_token` (pre-fetched by FORGE) |
| `token = get_auth_token()` | `token = ctx.auth_token` |
| `api_key = os.environ["GITHUB_TOKEN"]` | `api_key = ctx.config.get("github_token", os.environ.get("GITHUB_TOKEN", ""))` |

FORGE pre-fetches the chainctl token before calling `run()`. Plugins should not call `chainctl auth token` themselves — use `ctx.auth_token`.

For non-Chainguard credentials (GitHub tokens, API keys), read from `ctx.config` with a fallback to environment variables.

### 4.9 Logging

**Rule: Use Python's `logging` module. Do not use `print()` for diagnostic output.**

```python
import logging
logger = logging.getLogger(__name__)

# BEFORE
print(f"Warning: image {name} not found", file=sys.stderr)

# AFTER
logger.warning("Image %s not found", name)
```

User-facing output (the final report, summary) goes into `ToolResult.summary` and `ToolResult.data`. Diagnostic/debug output goes through `logging`.

The one exception: if the tool generates complex formatted console output (e.g., verification chains with box-drawing characters), that logic can remain as a helper function. The plugin's `run()` can call it for CLI mode, and the structured data in `ToolResult.data` serves the web UI.

### 4.10 External CLI Tool Dependencies

If the source tool shells out to external commands (chainctl, crane, cosign, grype, docker, etc.), check for them at the start of `run()`:

```python
from forge_core.deps import assert_dependencies

REQUIRED_TOOLS = ["chainctl", "crane", "cosign"]

def run(self, args, ctx):
    assert_dependencies(REQUIRED_TOOLS)  # raises RuntimeError if any missing
    ...
```

This raises a clear error if tools are missing, rather than failing mid-execution with a confusing subprocess error.

### 4.11 Non-Python Tools

If the source tool is written in Go, Rust, JavaScript, or another language:

1. **Wrap it.** The FORGE plugin is always Python. The plugin's `run()` method invokes the tool as a subprocess.
2. **Bundle the binary.** Include the compiled binary in the plugin package or expect it on PATH.
3. **Parse output.** Capture stdout/stderr and parse into `ToolResult`.

```python
import subprocess
import json

class GoToolPlugin:
    name = "gotool"
    description = "Wraps a Go CLI tool"
    version = "1.0.0"

    def get_params(self) -> list[ToolParam]:
        return [
            ToolParam(name="target", description="Target to analyze", required=True),
        ]

    def run(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        assert_dependencies(["gotool-binary"])

        result = subprocess.run(
            ["gotool-binary", "--json", "--target", args["target"]],
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode != 0:
            return ToolResult(
                status=ResultStatus.FAILURE,
                summary=f"gotool failed: {result.stderr.strip()}",
            )

        data = json.loads(result.stdout)
        return ToolResult(
            status=ResultStatus.SUCCESS,
            summary=f"Analyzed {args['target']}",
            data=data,
        )
```

---

## 5. Complete File Templates

### 5.1 pyproject.toml

```toml
[project]
name = "forge-CHANGEME"
version = "0.1.0"
description = "CHANGEME: one-line description"
requires-python = ">=3.12"
license = { text = "Apache-2.0" }
authors = [
    { name = "Chainguard Field Engineering" }
]
dependencies = [
    "forge-core",
    # CHANGEME: add tool-specific dependencies here, e.g.:
    # "requests>=2.32.0,<3.0.0",
    # "pyyaml>=6.0,<7.0",
]

[project.entry-points."forge.plugins"]
# CHANGEME: key is the CLI subcommand name, value is the create_plugin function
CHANGEME = "forge_CHANGEME:create_plugin"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
# CHANGEME: must match the src directory name
packages = ["src/forge_CHANGEME"]

[tool.mypy]
python_version = "3.12"
strict = true

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP", "B", "C4", "SIM"]
```

**Checklist for filling this template:**
- [ ] Replace all `CHANGEME` with actual values
- [ ] Entry point key matches the desired CLI subcommand name
- [ ] Entry point value matches the actual Python module path
- [ ] All third-party dependencies from the source tool are listed with version bounds
- [ ] `forge-core` is in dependencies
- [ ] `packages` path under `[tool.hatch.build.targets.wheel]` matches `src/forge_<name>`

### 5.2 __init__.py

```python
"""FORGE plugin: CHANGEME_DESCRIPTION."""

from forge_CHANGEME.plugin import CHANGEMEPlugin


def create_plugin() -> CHANGEMEPlugin:
    """Entry point for FORGE plugin discovery."""
    return CHANGEMEPlugin()
```

**Checklist:**
- [ ] Import path matches the actual module and class name
- [ ] `create_plugin()` returns an instance (not the class itself)
- [ ] Function is named exactly `create_plugin` (this is what the entry point references)

### 5.3 plugin.py

```python
"""ToolPlugin implementation for CHANGEME."""

from __future__ import annotations

import logging
from typing import Any

from forge_core.context import ExecutionContext
from forge_core.deps import assert_dependencies
from forge_core.plugin import ToolParam, ToolResult, ResultStatus

# Import the migrated tool logic
from forge_CHANGEME.core import (
    # CHANGEME: import the functions you need from the migrated source
    pass
)

logger = logging.getLogger(__name__)

# CHANGEME: list any external CLI tools this plugin requires
REQUIRED_TOOLS: list[str] = []


class CHANGEMEPlugin:
    """CHANGEME: plugin description."""

    name = "CHANGEME"                   # CLI subcommand: forge CHANGEME ...
    description = "CHANGEME"            # One-line help text
    version = "0.1.0"                   # Semver

    def get_params(self) -> list[ToolParam]:
        """Declare parameters.

        CHANGEME: Convert each argparse argument from the source tool
        to a ToolParam using the rules in section 4.2.
        """
        return [
            # CHANGEME: add ToolParam entries here
            # Example:
            # ToolParam(name="org", description="Target organization", required=True),
            # ToolParam(name="limit", description="Max items to process", type="int", default=0),
            # ToolParam(name="verbose", description="Enable verbose output", type="bool"),
        ]

    def run(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        """Execute the tool.

        CHANGEME: Implement by calling migrated source functions.
        """
        # 1. Check external dependencies
        if REQUIRED_TOOLS:
            assert_dependencies(REQUIRED_TOOLS)

        # 2. Extract args
        # org = args["org"]
        # limit = args.get("limit", 0)

        # 3. Report starting progress
        ctx.progress(0.0, "Starting...")

        # 4. Call migrated tool logic
        # Use ctx.auth_token for Chainguard API calls
        # Use ctx.progress() to report progress
        # Check ctx.is_cancelled in loops

        try:
            # CHANGEME: call your tool's core functions here
            pass
        except Exception as e:
            logger.exception("Plugin execution failed")
            return ToolResult(status=ResultStatus.FAILURE, summary=str(e))

        # 5. Return result
        ctx.progress(1.0, "Done")
        return ToolResult(
            status=ResultStatus.SUCCESS,
            summary="CHANGEME: describe what was accomplished",
            # data={"key": "value"},           # structured output
            # artifacts={"report": "/path"},    # generated files
        )
```

---

## 6. Worked Examples

### 6.1 Example: Single-File Script with argparse

**Source: `my_scanner.py`** (simplified)

```python
#!/usr/bin/env python3
"""Scan images for vulnerabilities."""
import argparse, json, subprocess, sys

def scan_image(image: str, severity: str) -> dict:
    result = subprocess.run(["grype", image, "--output", "json", "--only-fixed",
                             "--fail-on", severity], capture_output=True, text=True)
    return json.loads(result.stdout) if result.returncode == 0 else {}

def main():
    parser = argparse.ArgumentParser(description="Scan container images")
    parser.add_argument("-i", "--images", required=True, help="File with image list")
    parser.add_argument("-s", "--severity", default="high", choices=["low","medium","high","critical"])
    parser.add_argument("-o", "--output", default="scan_results.json")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    with open(args.images) as f:
        images = [line.strip() for line in f if line.strip()]

    if not images:
        print("Error: no images in file", file=sys.stderr)
        sys.exit(1)

    results = {}
    for i, img in enumerate(images):
        if args.verbose:
            print(f"Scanning {i+1}/{len(images)}: {img}")
        results[img] = scan_image(img, args.severity)

    with open(args.output, "w") as f:
        json.dump(results, f, indent=2)

    total_vulns = sum(len(r.get("matches", [])) for r in results.values())
    print(f"Scanned {len(images)} images, found {total_vulns} vulnerabilities")
    print(f"Results written to {args.output}")

if __name__ == "__main__":
    main()
```

**Migration produces these files:**

**`packages/forge-scanner/pyproject.toml`:**
```toml
[project]
name = "forge-scanner"
version = "0.1.0"
description = "Scan container images for vulnerabilities"
requires-python = ">=3.12"
license = { text = "Apache-2.0" }
dependencies = ["forge-core"]

[project.entry-points."forge.plugins"]
scanner = "forge_scanner:create_plugin"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/forge_scanner"]
```

**`packages/forge-scanner/src/forge_scanner/__init__.py`:**
```python
"""FORGE plugin: container image vulnerability scanner."""
from forge_scanner.plugin import ScannerPlugin

def create_plugin() -> ScannerPlugin:
    return ScannerPlugin()
```

**`packages/forge-scanner/src/forge_scanner/core.py`:**
```python
"""Core scanning logic (migrated from my_scanner.py)."""
from __future__ import annotations
import json
import subprocess

def scan_image(image: str, severity: str) -> dict:
    """Scan a single image with grype."""
    result = subprocess.run(
        ["grype", image, "--output", "json", "--only-fixed", "--fail-on", severity],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode == 0 and result.stdout:
        return json.loads(result.stdout)
    return {}
```

**`packages/forge-scanner/src/forge_scanner/plugin.py`:**
```python
"""ToolPlugin implementation for scanner."""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any
from forge_core.context import ExecutionContext
from forge_core.deps import assert_dependencies
from forge_core.plugin import ToolParam, ToolResult, ResultStatus
from forge_scanner.core import scan_image

logger = logging.getLogger(__name__)

class ScannerPlugin:
    name = "scanner"
    description = "Scan container images for vulnerabilities"
    version = "0.1.0"

    def get_params(self) -> list[ToolParam]:
        return [
            ToolParam(name="images", description="File containing image list (one per line)", required=True),
            ToolParam(name="severity", description="Minimum severity to report", choices=["low", "medium", "high", "critical"], default="high"),
            ToolParam(name="output", description="Output file path", default="scan_results.json"),
        ]

    def run(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        assert_dependencies(["grype"])

        images_file = args["images"]
        severity = args.get("severity", "high")
        output_path = args.get("output", "scan_results.json")

        # Read image list
        try:
            with open(images_file) as f:
                images = [line.strip() for line in f if line.strip()]
        except FileNotFoundError:
            return ToolResult(status=ResultStatus.FAILURE, summary=f"File not found: {images_file}")

        if not images:
            return ToolResult(status=ResultStatus.FAILURE, summary="No images found in input file")

        # Scan each image
        ctx.progress(0.0, f"Scanning {len(images)} images")
        results: dict[str, Any] = {}

        for i, img in enumerate(images):
            if ctx.is_cancelled:
                return ToolResult(status=ResultStatus.CANCELLED, summary="Cancelled by user")

            ctx.progress((i + 1) / len(images), f"Scanning {img}")
            results[img] = scan_image(img, severity)

        # Write output
        output = Path(output_path)
        with open(output, "w") as f:
            json.dump(results, f, indent=2)

        total_vulns = sum(len(r.get("matches", [])) for r in results.values())

        return ToolResult(
            status=ResultStatus.SUCCESS,
            summary=f"Scanned {len(images)} images, found {total_vulns} vulnerabilities",
            data={"images_scanned": len(images), "total_vulnerabilities": total_vulns},
            artifacts={"report": str(output.resolve())},
        )
```

### 6.2 Example: Tool with Subcommands

**Source tool has subcommands:** `tool scan ...`, `tool match ...`, `tool update ...`

**Strategy:** Use a `command` parameter.

```python
class MultiCommandPlugin:
    name = "tool"
    description = "Tool with multiple commands"
    version = "1.0.0"

    def get_params(self) -> list[ToolParam]:
        return [
            ToolParam(name="command", description="Command to run", required=True,
                      choices=["scan", "match", "update"]),
            # Include params for ALL subcommands. Params specific to one subcommand
            # should not be required — validate in run() based on command value.
            ToolParam(name="input", description="Input file (for scan, match)"),
            ToolParam(name="output", description="Output directory", default="output"),
            ToolParam(name="target", description="Update target (for update)"),
        ]

    def run(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        command = args["command"]

        if command == "scan":
            if not args.get("input"):
                return ToolResult(status=ResultStatus.FAILURE,
                                  summary="--input is required for scan command")
            return self._run_scan(args, ctx)
        elif command == "match":
            return self._run_match(args, ctx)
        elif command == "update":
            return self._run_update(args, ctx)
        else:
            return ToolResult(status=ResultStatus.FAILURE,
                              summary=f"Unknown command: {command}")

    def _run_scan(self, args, ctx):
        # ... scan logic ...
        pass

    def _run_match(self, args, ctx):
        # ... match logic ...
        pass

    def _run_update(self, args, ctx):
        # ... update logic ...
        pass
```

### 6.3 Example: Tool with ThreadPoolExecutor

**Source pattern:**
```python
with ThreadPoolExecutor(max_workers=10) as executor:
    futures = {executor.submit(process, item): item for item in items}
    for future in as_completed(futures):
        name = futures[future]
        result = future.result()
        print(f"Done: {name}")
```

**Converted pattern:**
```python
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

def run(self, args, ctx):
    items = get_items()
    completed = 0
    lock = threading.Lock()
    total = len(items)
    results = {}

    def process_with_tracking(item):
        """Process item and return result. Runs in thread pool."""
        return item.name, do_work(item, ctx.auth_token)

    ctx.progress(0.0, f"Processing {total} items")

    with ThreadPoolExecutor(max_workers=args.get("workers", 10)) as executor:
        futures = {executor.submit(process_with_tracking, item): item for item in items}

        for future in as_completed(futures):
            if ctx.is_cancelled:
                executor.shutdown(wait=False, cancel_futures=True)
                return ToolResult(status=ResultStatus.CANCELLED, summary="Cancelled")

            name, result = future.result()
            results[name] = result

            with lock:
                completed += 1
                ctx.progress(completed / total, f"Completed: {name}")

    return ToolResult(
        status=ResultStatus.SUCCESS,
        summary=f"Processed {total} items",
        data=results,
    )
```

---

## 7. Validation Checklist

After completing the migration, verify each item:

### 7.1 Files Created

- [ ] `packages/forge-<name>/pyproject.toml` exists and is valid TOML
- [ ] `packages/forge-<name>/src/forge_<name>/__init__.py` exists and exports `create_plugin()`
- [ ] `packages/forge-<name>/src/forge_<name>/plugin.py` exists with a class implementing `ToolPlugin`
- [ ] All source modules are copied into `src/forge_<name>/`
- [ ] Package is added to root `pyproject.toml` workspace members

### 7.2 Protocol Compliance

- [ ] Plugin class has `name: str` attribute (class variable, not property)
- [ ] Plugin class has `description: str` attribute
- [ ] Plugin class has `version: str` attribute
- [ ] `get_params()` returns `list[ToolParam]`
- [ ] `run()` accepts `(self, args: dict[str, Any], ctx: ExecutionContext)` and returns `ToolResult`
- [ ] `run()` never calls `sys.exit()`
- [ ] `run()` never calls `input()` or reads from stdin
- [ ] `run()` never accesses `sys.argv`

### 7.3 Argument Mapping

- [ ] Every CLI argument from the source tool has a corresponding `ToolParam`
- [ ] Required arguments have `required=True`
- [ ] Boolean flags have `type="bool"`
- [ ] Integer arguments have `type="int"`
- [ ] Arguments with choices have `choices=[...]`
- [ ] Default values match the source tool's defaults
- [ ] No `nargs` — comma-separated strings used instead (if applicable)

### 7.4 Execution

- [ ] `ctx.progress()` is called at least at start (0.0) and end (1.0)
- [ ] `ctx.is_cancelled` is checked in every loop that processes multiple items
- [ ] `ctx.auth_token` is used instead of calling `chainctl auth token` directly
- [ ] External tool dependencies are checked with `assert_dependencies()` at the start of `run()`

### 7.5 Output

- [ ] `ToolResult.status` is set to the correct `ResultStatus` enum value
- [ ] `ToolResult.summary` is a concise, human-readable one-line string
- [ ] `ToolResult.data` contains only JSON-serializable values (no datetime, Path, or custom objects)
- [ ] `ToolResult.artifacts` maps descriptive names to absolute file paths for generated files
- [ ] No `print()` calls remain in plugin.py for user-facing output (use logger for diagnostics)

### 7.6 Imports

- [ ] All internal imports use the `forge_<name>.` prefix
- [ ] No `sys.path` manipulation
- [ ] No relative imports from outside the package
- [ ] `from __future__ import annotations` is at the top of every file (for modern type hint syntax)

### 7.7 Integration

- [ ] `uv sync` completes without errors
- [ ] `forge <name> --help` shows the correct parameters and descriptions
- [ ] `forge <name> <valid-args>` executes successfully
- [ ] Running `forge` with no arguments lists the new tool
