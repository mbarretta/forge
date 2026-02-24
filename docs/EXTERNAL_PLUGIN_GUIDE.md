# FORGE External Plugin Development Guide

This guide covers how to create external plugins for FORGE that live in separate repositories. External plugins can be installed and managed independently from FORGE's core plugins.

## Two Approaches to External Plugins

FORGE supports two types of external plugins:

### 1. Native Plugin (Minimal - Requires FORGE Awareness)

Your external project **directly implements** the `ToolPlugin` protocol. This provides the cleanest integration but requires your project to depend on `forge-core`.

**Best for:** New tools being built specifically for FORGE integration.

### 2. Wrapped Plugin (Zero External Changes)

FORGE provides an **adapter/wrapper** that interfaces with your existing tool. Your external project remains completely independent and doesn't need to know about FORGE.

**Best for:** Existing internal tools, legacy tools, or tools you don't control.

---

## Native Plugin Development

### Prerequisites

- Python 3.12+
- Git repository (can be private GitHub repo)
- Basic understanding of Python packaging

### Step 1: Create Plugin Project

```bash
# Create new project
mkdir my-security-scanner
cd my-security-scanner

# Initialize git
git init
git remote add origin git@github.com:your-org/my-security-scanner.git
```

### Step 2: Create Project Structure

```
my-security-scanner/
├── pyproject.toml
├── README.md
└── src/
    └── my_security_scanner/
        ├── __init__.py
        ├── plugin.py      # ToolPlugin implementation
        └── core.py        # Your tool logic
```

### Step 3: Configure pyproject.toml

```toml
[project]
name = "my-security-scanner"
version = "1.0.0"
description = "Security scanner for container images"
requires-python = ">=3.12"

dependencies = [
    "forge-core>=0.1.0",  # Required for ToolPlugin protocol
    # ... your other dependencies
]

# CRITICAL: Register your plugin entry point
# IMPORTANT: use the full dotted module path — never use a bare "forge_plugin" top-level
# module name, as it will collide with other plugins that do the same.
[project.entry-points."forge.plugins"]
my-scanner = "my_security_scanner.plugin:create_plugin"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

**Key points:**
- Entry point group must be `"forge.plugins"`
- Entry point value must use a **namespaced module path** (e.g. `my_security_scanner.plugin:create_plugin`). Never use the bare name `forge_plugin` — it is reserved and will collide with any other plugin that does the same.
- Entry point value points to a `create_plugin()` factory function
- Entry point name becomes the CLI command: `forge my-scanner`

**If your plugin depends on another package that is not on PyPI**, declare it with a full git URL instead of a plain version specifier, and tell hatchling to allow direct references:

```toml
[project]
dependencies = [
    "forge-core>=0.1.0",
    "my-lib @ git+https://github.com/your-org/my-lib.git",  # not on PyPI
]

[tool.hatch.metadata]
allow-direct-references = true  # required when any dep uses a URL
```

> **Pitfall — `[tool.uv.sources]` path overrides are silently skipped during remote installs.**
> It is common in monorepo development to use `[tool.uv.sources]` to point at a local path:
> ```toml
> [tool.uv.sources]
> my-lib = { path = "../my-lib" }
> ```
> This is fine for local development but uv ignores `[tool.uv.sources]` when installing a
> package from a git URL (e.g. `uv pip install git+https://...`).  The `[project.dependencies]`
> entry must already resolve on its own — using the git URL approach above.

### Step 4: Implement ToolPlugin Protocol

**File: `src/my_security_scanner/plugin.py`**

```python
"""FORGE plugin for my-security-scanner."""

from forge_core.plugin import ToolPlugin, ToolParam, ToolResult, ResultStatus
from forge_core.context import ExecutionContext

from my_security_scanner.core import scan_image  # Your actual logic


class MyScannerPlugin:
    """FORGE plugin for security scanning."""

    name = "my-scanner"
    description = "Scan container images for security issues"
    version = "1.0.0"
    requires_auth = True  # True = runner fetches a chainctl token before calling run()

    def get_params(self) -> list[ToolParam]:
        """Declare CLI parameters."""
        return [
            ToolParam(
                name="image",
                description="Container image to scan (e.g., nginx:latest)",
                required=True,
            ),
            ToolParam(
                name="severity",
                description="Minimum severity to report",
                type="str",
                default="medium",
                choices=["low", "medium", "high", "critical"],
            ),
            ToolParam(
                name="output",
                description="Output file path",
                type="str",
                default="scan-report.json",
            ),
            ToolParam(
                name="fail-on-critical",
                description="Exit with error if critical vulns found",
                type="bool",
                default=False,
            ),
        ]

    def run(self, args: dict, ctx: ExecutionContext) -> ToolResult:
        """Execute the scanner.

        Args:
            args: Parameter values from CLI/API
            ctx: Execution context (auth, progress, cancellation)

        Returns:
            ToolResult with status, summary, data, and artifacts
        """
        image = args["image"]
        severity = args["severity"]
        output_path = args["output"]

        # Report progress
        ctx.progress(0.0, f"Scanning {image}...")

        # Check for cancellation
        if ctx.is_cancelled:
            return ToolResult(
                status=ResultStatus.CANCELLED,
                summary="Scan cancelled by user",
            )

        # Run your tool logic
        try:
            results = scan_image(
                image=image,
                min_severity=severity,
                auth_token=ctx.auth_token,  # Use FORGE auth if needed
            )

            # Save output file
            with open(output_path, "w") as f:
                json.dump(results, f, indent=2)

            ctx.progress(1.0, "Scan complete")

            # Determine status
            critical_count = results.get("critical_count", 0)
            if critical_count > 0 and args["fail-on-critical"]:
                status = ResultStatus.FAILURE
            else:
                status = ResultStatus.SUCCESS

            return ToolResult(
                status=status,
                summary=f"Found {results['total_vulns']} vulnerabilities ({critical_count} critical)",
                data={
                    "total": results["total_vulns"],
                    "critical": critical_count,
                    "high": results.get("high_count", 0),
                },
                artifacts={
                    "report": output_path,  # Files produced by your tool
                },
            )

        # TIP: For plugins that produce rich text output (markdown reports, emails, etc.),
        # put the text in data["output"] and keep summary as a short status line:
        #
        #     return ToolResult(
        #         status=ResultStatus.SUCCESS,
        #         summary="Report generated",     # short; shown as fallback
        #         data={"output": markdown_text},  # printed as main output by the runner
        #     )
        #
        # The runner prints data["output"] when present, falling back to summary.

        except Exception as e:
            return ToolResult(
                status=ResultStatus.FAILURE,
                summary=f"Scan failed: {str(e)}",
            )


def create_plugin() -> ToolPlugin:
    """Factory function called by FORGE plugin discovery."""
    return MyScannerPlugin()
```

### Step 5: Write Your Tool Logic

**File: `src/my_security_scanner/core.py`**

```python
"""Core scanning logic (separate from FORGE integration)."""

def scan_image(image: str, min_severity: str, auth_token: str | None = None) -> dict:
    """Scan container image for vulnerabilities.

    This is your actual tool implementation - no FORGE dependencies here.
    """
    # Your scanning logic here
    results = {
        "image": image,
        "total_vulns": 42,
        "critical_count": 3,
        "high_count": 12,
        # ... more data
    }
    return results
```

### Step 6: Add README and Documentation

**File: `README.md`**

````markdown
# My Security Scanner

Security scanner for container images, integrated with FORGE.

## Installation

### Via FORGE Plugin Manager (Recommended)

```bash
forge plugin install my-scanner
```

### Direct Installation

```bash
# SSH
uv pip install git+ssh://git@github.com/your-org/my-security-scanner.git@v1.0.0

# HTTPS
uv pip install git+https://github.com/your-org/my-security-scanner.git@v1.0.0
```

## Usage

```bash
# Scan an image
forge my-scanner --image nginx:latest

# Scan with custom severity
forge my-scanner --image nginx:latest --severity high

# Fail on critical vulnerabilities
forge my-scanner --image nginx:latest --fail-on-critical
```

## Authentication

For private GitHub repositories, ensure you have access:

```bash
# SSH (recommended)
ssh -T git@github.com

# Or configure HTTPS credentials
git config --global credential.helper store
```
````

### Step 7: Version with Git Tags

```bash
# Commit your code
git add .
git commit -m "Initial plugin implementation"

# Tag releases
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin v1.0.0
```

**Version pinning:** Users can install specific versions:
```bash
forge plugin install my-scanner --ref v1.0.0
```

### Step 8: Submit to FORGE Registry

Create a pull request to add your plugin to `plugins-registry.yaml`:

```yaml
external_plugins:
  my-scanner:
    package: "my-security-scanner"
    source: "git+ssh://git@github.com/your-org/my-security-scanner.git"
    ref: "v1.0.0"
    description: "Security scanner for container images"
    plugin_type: "native"
    tags: [security, scanning]
    private: true  # Set to false for public repos
```

**If the plugin lives in a subdirectory of a larger repo** (e.g. a `forge-plugin/` folder inside a
multi-purpose project), append `#subdirectory=<path>` to the source URL. The `@ref` must come
**before** the `#` fragment:

```yaml
external_plugins:
  my-scanner:
    package: "my-security-scanner"
    source: "git+https://github.com/your-org/big-project.git#subdirectory=forge-plugin"
    ref: "v1.0.0"   # injected as ...git@v1.0.0#subdirectory=forge-plugin at install time
    description: "Scanner living inside big-project/forge-plugin/"
    plugin_type: "native"
    tags: [security, scanning]
    private: true
```

The corresponding `forge-plugin/pyproject.toml` should use `packages = ["src/my_security_scanner"]`
in `[tool.hatch.build.targets.wheel]` so hatchling only packages the plugin source, not the whole
outer project.

### Testing Your Plugin

```bash
# Test installation locally
uv pip install -e .

# Verify FORGE discovers it
forge --help
# Should see "my-scanner" in the list

# Test your plugin
forge my-scanner --help
forge my-scanner --image nginx:latest

# Test progress reporting
forge my-scanner --image nginx:latest --verbose
```

---

## Wrapped Plugin Development

For existing tools that you **cannot or do not want to modify**, create a FORGE wrapper.

### When to Use Wrappers

- ✅ Legacy internal tools
- ✅ Tools written in other languages (Go, Rust, etc.)
- ✅ Proprietary/closed-source tools
- ✅ CLI-only tools without Python API
- ✅ Tools you don't control (third-party)

### Wrapper Types

#### A. Python Library Wrapper

External tool is a Python package with an importable API.

**Project structure:**
```
forge-legacy-tool-wrapper/
├── pyproject.toml
├── README.md
└── src/
    └── forge_legacy_tool_wrapper/
        ├── __init__.py
        └── plugin.py      # FORGE adapter only
```

**pyproject.toml:**
```toml
[project]
name = "forge-legacy-tool-wrapper"
version = "1.0.0"
description = "FORGE wrapper for legacy-tool"
requires-python = ">=3.12"

dependencies = [
    "forge-core>=0.1.0",
    # External tool as dependency
    "legacy-tool @ git+https://github.com/your-org/legacy-tool.git@v2.1.0",
]

[project.entry-points."forge.plugins"]
legacy-tool = "forge_legacy_tool_wrapper:create_plugin"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

**plugin.py:**
```python
"""FORGE wrapper for legacy-tool (no changes to legacy-tool needed)."""

from forge_core.plugin import ToolPlugin, ToolParam, ToolResult, ResultStatus
from forge_core.context import ExecutionContext

# Import from external tool
from legacy_tool import LegacyTool


class LegacyToolWrapper:
    """FORGE adapter for legacy-tool."""

    name = "legacy-tool"
    description = "Legacy internal tool (wrapped for FORGE)"
    version = "1.0.0"
    requires_auth = False  # Set True if your wrapper needs a chainctl token

    def get_params(self) -> list[ToolParam]:
        # Map external tool's interface to FORGE params
        return [
            ToolParam(name="input", description="Input file", required=True),
            ToolParam(name="output", description="Output directory", default="./output"),
        ]

    def run(self, args: dict, ctx: ExecutionContext) -> ToolResult:
        # Translate FORGE args to external tool's API
        tool = LegacyTool(
            input_path=args["input"],
            output_dir=args["output"],
        )

        try:
            ctx.progress(0.5, "Running legacy tool...")
            result = tool.execute()

            # Translate external result to FORGE format
            return ToolResult(
                status=ResultStatus.SUCCESS if result.success else ResultStatus.FAILURE,
                summary=result.message,
                data={"processed": result.items_processed},
                artifacts={"report": str(result.report_path)},
            )
        except Exception as e:
            return ToolResult(
                status=ResultStatus.FAILURE,
                summary=f"Tool failed: {str(e)}",
            )


def create_plugin() -> ToolPlugin:
    return LegacyToolWrapper()
```

#### B. CLI Wrapper

External tool is a standalone CLI command (Go binary, shell script, etc.).

**plugin.py:**
```python
"""FORGE wrapper for CLI tool."""

import subprocess
from pathlib import Path

from forge_core.plugin import ToolPlugin, ToolParam, ToolResult, ResultStatus
from forge_core.context import ExecutionContext


class CLIToolWrapper:
    """Wrapper for external CLI tool."""

    name = "cli-tool"
    description = "External CLI tool (wrapped)"
    version = "1.0.0"
    requires_auth = False

    def get_params(self) -> list[ToolParam]:
        return [
            ToolParam(name="input", description="Input file", required=True),
            ToolParam(name="verbose", description="Verbose output", type="bool"),
        ]

    def run(self, args: dict, ctx: ExecutionContext) -> ToolResult:
        # Build command
        cmd = [
            "external-cli-tool",  # Must be in PATH or use full path
            "--input", args["input"],
        ]

        if args.get("verbose"):
            cmd.append("--verbose")

        ctx.progress(0.5, "Running external CLI tool...")

        # Execute
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode == 0:
                return ToolResult(
                    status=ResultStatus.SUCCESS,
                    summary=result.stdout.strip() or "Command completed successfully",
                    data={"stdout": result.stdout, "stderr": result.stderr},
                )
            else:
                return ToolResult(
                    status=ResultStatus.FAILURE,
                    summary=f"Command failed with exit code {result.returncode}",
                    data={"stdout": result.stdout, "stderr": result.stderr},
                )

        except FileNotFoundError:
            return ToolResult(
                status=ResultStatus.FAILURE,
                summary="External CLI tool not found in PATH",
            )


def create_plugin() -> ToolPlugin:
    return CLIToolWrapper()
```

**Installation process:** When installing the wrapper, the external CLI tool must be available in PATH.

If the upstream CLI tool is written in Go, TypeScript, or another non-Python language, you
cannot declare it as a Python dep in `pyproject.toml`. Instead, add a `system_deps` entry to
the plugin's registry record so `forge plugin install` installs the binary automatically.
See [NON_PYTHON_WRAPPER_GUIDE.md](./NON_PYTHON_WRAPPER_GUIDE.md) for a full walkthrough.

### Wrapper Maintenance

- **Update wrapper version** when you change the FORGE integration
- **Update external tool dependency** when the tool's API changes
- **Test compatibility** between wrapper and external tool versions

---

## Binary Protocol Plugins (No Python Wrapper Needed)

If you don't want to maintain a Python wrapper repo at all, any binary that speaks a simple
JSON stdio protocol can be registered directly as a FORGE plugin.

### How it works

```
# Introspection (called once on install):
binary --forge-introspect
stdout → {"name":"...", "description":"...", "version":"...", "requires_auth":false, "params":[...]}

# Execution (called on each `forge <name>` invocation):
binary --forge-run '{"param1":"val"}'
stderr → newline-delimited {"progress":0.5, "message":"Scanning..."}
stdout → {"status":"success", "summary":"...", "data":{}, "artifacts":{}}
```

### Registry entry

```yaml
external_plugins:
  mytool:
    plugin_type: "binary"
    description: "My Go/Rust tool, speaks the forge binary protocol"
    private: true
    binary_source:
      manager: "github_release"
      repo: "org/mytool"
      tag: "v1.0.0"
      asset: "mytool_{os}_{arch}"   # {os} → darwin/linux, {arch} → amd64/arm64
      binary: "mytool"
      install_dir: "~/.local/bin"   # optional, default: ~/.local/bin
```

Binary plugins are downloaded, chmod +x'd, and introspected automatically during
`forge plugin install`. The introspection result is cached at
`~/.config/forge/binary-plugins.json` and loaded by `forge` on startup alongside
Python entry-point plugins.

> See [AUTHENTICATION.md](./AUTHENTICATION.md) for how to authenticate private
> `github_release` downloads using `gh auth login` or `GITHUB_TOKEN`.

---

## Authentication for Private Repositories

FORGE uses standard git authentication - no additional setup needed beyond what you already use for `git clone`.

### SSH Authentication (Recommended)

```bash
# Generate SSH key (if you don't have one)
ssh-keygen -t ed25519 -C "your-email@example.com"

# Add to GitHub
cat ~/.ssh/id_ed25519.pub
# Copy and paste to: https://github.com/settings/keys

# Test connection
ssh -T git@github.com
```

**Registry entry uses SSH URL:**
```yaml
external_plugins:
  my-plugin:
    source: "git+ssh://git@github.com/your-org/my-plugin.git"
    private: true
```

### HTTPS with Token

```bash
# Configure git credential helper
git config --global credential.helper store

# Clone any private repo (will prompt for credentials once)
git clone https://github.com/your-org/my-plugin.git

# Subsequent installs use cached credentials
forge plugin install my-plugin
```

**Registry entry uses HTTPS URL:**
```yaml
external_plugins:
  my-plugin:
    source: "git+https://github.com/your-org/my-plugin.git"
    private: true
```

### GitHub CLI Integration

```bash
# Authenticate once
gh auth login

# gh configures git credentials automatically
forge plugin install my-plugin  # Just works
```

---

## Best Practices

### 1. Semantic Versioning

Use git tags with semantic versioning:

```bash
git tag -a v1.0.0 -m "Initial release"
git tag -a v1.1.0 -m "Add new feature"
git tag -a v2.0.0 -m "Breaking change"
```

### 2. Maintain Compatibility

- Keep `forge-core` dependency version broad: `forge-core>=0.1.0`
- Test against multiple FORGE versions
- Document breaking changes in release notes

### 3. Error Handling

Always return proper `ToolResult`:

```python
try:
    # Your logic
    return ToolResult(status=ResultStatus.SUCCESS, summary="...")
except SpecificError as e:
    return ToolResult(status=ResultStatus.FAILURE, summary=f"Error: {e}")
except Exception as e:
    # Catch-all for unexpected errors
    return ToolResult(status=ResultStatus.FAILURE, summary=f"Unexpected error: {e}")
```

### 4. Progress Reporting

Use `ctx.progress()` for long-running operations:

```python
def run(self, args, ctx):
    ctx.progress(0.0, "Starting...")

    for i, item in enumerate(items):
        if ctx.is_cancelled:
            return ToolResult(status=ResultStatus.CANCELLED, summary="Cancelled")

        # Process item
        ctx.progress((i + 1) / len(items), f"Processing {item}")

    ctx.progress(1.0, "Complete")
```

### 5. Testing

Include tests in your plugin repository:

```python
# tests/test_plugin.py
from forge_core.context import ExecutionContext
from my_security_scanner.plugin import MyScannerPlugin


def test_basic_scan():
    plugin = MyScannerPlugin()
    ctx = ExecutionContext()

    result = plugin.run({"image": "nginx:latest", "severity": "high"}, ctx)

    assert result.status == ResultStatus.SUCCESS
    assert "vulnerabilities" in result.summary
```

### 6. Documentation

Include in your README:
- Installation instructions (FORGE plugin manager + direct)
- Usage examples
- Parameter documentation
- Authentication requirements (if applicable)
- Troubleshooting

---

## Publishing Your Plugin

### 1. Create Repository

```bash
# Push to GitHub
git remote add origin git@github.com:your-org/my-plugin.git
git push -u origin main
git push --tags
```

### 2. Add to FORGE Registry

Submit PR to FORGE repository with registry entry:

```yaml
external_plugins:
  my-plugin:
    package: "my-plugin-package-name"
    source: "git+ssh://git@github.com/your-org/my-plugin.git"
    ref: "v1.0.0"
    description: "Brief description of your plugin"
    plugin_type: "native"  # or "wrapper"
    tags: [security, compliance, scanning]
    private: true  # or false for public repos
```

### 3. Announce

Once merged, users can install with:

```bash
forge plugin list
forge plugin install my-plugin
```

---

## Troubleshooting

### Plugin Not Discovered

```bash
# Check if package is installed
uv pip list | grep my-plugin

# Check entry point registration
python -c "import importlib.metadata; print(list(importlib.metadata.entry_points(group='forge.plugins')))"

# Verify plugin loads
python -c "from my_plugin import create_plugin; print(create_plugin())"
```

### Authentication Errors

```bash
# Test git access
git clone git@github.com:your-org/my-plugin.git

# Check SSH keys
ssh -T git@github.com

# For HTTPS, configure credentials
gh auth status
```

### Import Errors

```bash
# Reinstall with dependencies
uv pip install --force-reinstall git+https://github.com/your-org/my-plugin.git

# Check dependency versions
uv pip show my-plugin
```

---

## Examples

### Complete Native Plugin Example

See `packages/forge-hello/` in the FORGE repository for a minimal working example.

### Complete Wrapper Example

See `docs/WRAPPER_TEMPLATE.md` for detailed wrapper templates.

---

## Support

- **Issues:** https://github.com/chainguard-dev/forge/issues
- **Documentation:** https://github.com/chainguard-dev/forge/tree/main/docs
- **Plugin Registry:** https://github.com/chainguard-dev/forge/blob/main/packages/forge-cli/src/forge_cli/data/plugins-registry.yaml
