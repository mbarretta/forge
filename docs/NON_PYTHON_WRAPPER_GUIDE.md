# Wrapping Non-Python Tools with `system_deps`

This guide explains how to write a FORGE plugin that wraps a Go, TypeScript/Node.js, or other
non-Python CLI tool, and how to use the `system_deps` registry field so that
`forge plugin install` installs the upstream binary automatically.

---

## 1. Overview

FORGE's Python wrapper pattern works in two flavours:

| Upstream tool type | How binary is delivered | `system_deps` needed? |
|---|---|---|
| Python package / CLI | `uv pip install` pulls it as a transitive dep | No |
| Go binary | `go install` | **Yes** |
| TypeScript/Node.js CLI | `npm install -g` | **Yes** |
| Other (Rust, shell script, …) | Manual / not yet supported | Notes only (see §7) |

When `system_deps` is present in the registry entry, `forge plugin install` runs the listed
install commands **before** installing the Python wrapper package via `uv pip install`.

---

## 2. How It Works

```
forge plugin install my-go-tool
  │
  ├─ 1. Reads plugins-registry.yaml entry for "my-go-tool"
  ├─ 2. Finds system_deps: [{manager: go, package: ..., binary: my-go-tool}]
  ├─ 3. shutil.which("my-go-tool") → not found
  ├─ 4. go install github.com/org/my-go-tool/cmd/my-go-tool@v1.2.3
  │      └─ success → prints "my-go-tool: installed via go"
  │      └─ failure → prints warning, continues to step 5
  └─ 5. uv pip install git+https://…/forge-my-go-tool.git@v1.0.0
         └─ prints "✓ Plugin 'my-go-tool' installed successfully"
```

**Failure policy: warn-and-continue.** If the runtime (`go`, `npm`) is missing or the install
fails, the Python wrapper is still installed and a clear remediation message is printed.
The command exits 0. Hard-failing would break automation even though the package is on disk.

If the binary is already present (`shutil.which` finds it), the install step is skipped silently.

---

## 3. Go Wrapper Walkthrough

### 3.1 Plugin Python package

**`src/forge_my_go_tool/plugin.py`**

```python
"""FORGE wrapper for my-go-tool (Go binary)."""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

from forge_core.context import ExecutionContext
from forge_core.plugin import ResultStatus, ToolParam, ToolPlugin, ToolResult

REQUIRED_TOOLS = ["my-go-tool"]


def assert_dependencies() -> None:
    missing = [t for t in REQUIRED_TOOLS if not shutil.which(t)]
    if missing:
        raise RuntimeError(
            f"Missing required tools: {', '.join(missing)}\n"
            "Run `forge plugin install my-go-tool` to install."
        )


class MyGoToolPlugin:
    name = "my-go-tool"
    description = "Wraps the my-go-tool Go binary"
    version = "1.0.0"
    requires_auth = False  # Set True if your wrapper needs a chainctl token

    def get_params(self) -> list[ToolParam]:
        return [
            ToolParam(name="target", description="Target to analyse", required=True),
            ToolParam(name="verbose", description="Verbose output", type="bool", default=False),
        ]

    def run(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        assert_dependencies()

        cmd = self._build_cmd(args)
        ctx.progress(0.1, f"Running my-go-tool on {args['target']}...")

        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            return ToolResult(
                status=ResultStatus.SUCCESS,
                summary=result.stdout.strip() or "Completed successfully",
                data={"stdout": result.stdout},
            )
        return ToolResult(
            status=ResultStatus.FAILURE,
            summary=f"my-go-tool failed (exit {result.returncode})",
            data={"stderr": result.stderr},
        )

    def _build_cmd(self, args: dict[str, Any]) -> list[str]:
        cmd = ["my-go-tool", args["target"]]
        if args.get("verbose"):
            cmd.append("--verbose")
        return cmd


def create_plugin() -> ToolPlugin:
    return MyGoToolPlugin()
```

### 3.2 `pyproject.toml`

```toml
[project]
name = "forge-my-go-tool"
version = "1.0.0"
description = "FORGE wrapper for my-go-tool"
requires-python = ">=3.12"
license = { text = "Apache-2.0" }

dependencies = [
    "forge-core>=0.1.0",
    # No Go dependency here — binary is installed via system_deps
]

[project.entry-points."forge.plugins"]
my-go-tool = "forge_my_go_tool:create_plugin"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

### 3.3 Registry entry

```yaml
external_plugins:
  my-go-tool:
    package: "forge-my-go-tool"
    source: "git+https://github.com/org/forge-my-go-tool.git"
    ref: "v1.0.0"
    description: "Wraps the my-go-tool Go binary"
    plugin_type: "wrapper"
    tags: [security]
    private: false
    system_deps:
      - manager: "go"
        package: "github.com/org/my-go-tool/cmd/my-go-tool@v1.2.3"
        binary: "my-go-tool"
```

### 3.4 What the user sees

```
$ forge plugin install my-go-tool
Installing plugin 'my-go-tool' from git+https://github.com/org/forge-my-go-tool.git@v1.0.0...

Installing system dependencies for 'my-go-tool'...
  my-go-tool: installed via go

Resolved 3 packages in 1.23s
...

✓ Plugin 'my-go-tool' installed successfully

Usage: forge forge-my-go-tool --help
```

---

## 4. Node.js / TypeScript Wrapper Walkthrough

The structure mirrors §3; the only differences are the `manager` and install invocation.

### 4.1 Registry entry

```yaml
external_plugins:
  my-ts-tool:
    package: "forge-my-ts-tool"
    source: "git+https://github.com/org/forge-my-ts-tool.git"
    ref: "v1.0.0"
    description: "Wraps the my-ts-tool Node.js CLI"
    plugin_type: "wrapper"
    tags: [security]
    private: false
    system_deps:
      - manager: "npm"
        package: "@org/my-ts-tool@2.0.0"
        binary: "my-ts-tool"
```

FORGE will run `npm install -g @org/my-ts-tool@2.0.0` during plugin install.

### 4.2 `plugin.py` differences

Replace `REQUIRED_TOOLS = ["my-go-tool"]` with `REQUIRED_TOOLS = ["my-ts-tool"]` and adjust
`_build_cmd` to invoke `my-ts-tool` instead of a Go binary. The rest is identical.

---

## 5. Testing Your Wrapper

Mock subprocess so tests never run a real binary:

```python
from unittest.mock import MagicMock, patch
from forge_core.context import ExecutionContext
from forge_my_go_tool.plugin import MyGoToolPlugin


def test_run_builds_correct_args():
    plugin = MyGoToolPlugin()
    cmd = plugin._build_cmd({"target": "nginx:latest", "verbose": False})
    assert cmd == ["my-go-tool", "nginx:latest"]


def test_run_success():
    plugin = MyGoToolPlugin()
    ctx = ExecutionContext()

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "all clear"
    mock_result.stderr = ""

    with patch("forge_my_go_tool.plugin.subprocess.run", return_value=mock_result):
        with patch("forge_my_go_tool.plugin.shutil.which", return_value="/usr/local/bin/my-go-tool"):
            result = plugin.run({"target": "nginx:latest", "verbose": False}, ctx)

    assert result.status.name == "SUCCESS"


def test_required_tools_defined():
    from forge_my_go_tool.plugin import REQUIRED_TOOLS
    assert "my-go-tool" in REQUIRED_TOOLS
```

---

## 6. Cross-Platform Notes

### Go (`go install`)

- Installs to `$GOPATH/bin` (defaults to `~/go/bin`).
- This directory **must be on `$PATH`** for the binary to be found later.
- If the user's `$GOPATH/bin` is not on `$PATH`, `shutil.which` will not find the binary even
  after a successful `go install`. Surface this in your `assert_dependencies()` error message:
  ```
  'my-go-tool' not found in PATH.
  Ensure $GOPATH/bin (~/.local/go/bin or ~/go/bin) is on your PATH.
  ```

### npm (`npm install -g`)

- Installs to the global `node_modules/.bin` (e.g. `/usr/local/lib/node_modules/.bin` on macOS,
  `~/.npm-global/bin` with user-level npm).
- Similarly, the global bin directory must be on `$PATH`.
- On some systems, `sudo npm install -g` is required for system-level install; prefer
  [configuring a user-level prefix](https://docs.npmjs.com/resolving-eacces-permissions-errors-when-installing-packages-globally).

---

## 7. Runtime Not Installed?

If the Go or Node.js runtime is missing, FORGE prints a warning and continues:

```
  Warning: my-go-tool: Go runtime not found. Install Go from https://go.dev/dl/
    then re-run: go install github.com/org/my-go-tool/cmd/my-go-tool@v1.2.3

✓ Plugin 'my-go-tool' installed successfully

Warning: 'my-go-tool' installed but these system deps need manual setup:
  my-go-tool (go): github.com/org/my-go-tool/cmd/my-go-tool@v1.2.3
    Go runtime not found. Install Go from https://go.dev/dl/
    then re-run: go install github.com/org/my-go-tool/cmd/my-go-tool@v1.2.3

The plugin is installed but may not function until the above are resolved.
```

After installing the runtime, re-run `forge plugin install my-go-tool` (or just the manual
`go install` / `npm install -g` command). The plugin package is already on disk; only the binary
install will re-run (and will be skipped if the binary is now in PATH).

---

## 8. Reference

### `system_deps` schema

```yaml
system_deps:
  - manager: "go"          # Required. "go" | "npm" | "github_release"
    package: "<arg>"       # Required. Verbatim install argument (go/npm) or unused for github_release
    binary: "<name>"       # Required. Binary name checked via shutil.which

    # github_release-only fields:
    repo: "org/repo"             # GitHub repo (e.g. "chainguard-dev/mytool")
    tag: "v1.2.3"                # Release tag to download
    asset: "mytool_{os}_{arch}"  # Asset name template; {os} → darwin/linux/windows, {arch} → amd64/arm64
    install_dir: "~/.local/bin"  # Install directory (default: ~/.local/bin)
```

### Supported managers

| `manager` | Install command | Auth |
|---|---|---|
| `go` | `go install <package>` | Go toolchain / `GOPRIVATE` |
| `npm` | `npm install -g <package>` | npm credentials |
| `github_release` | `gh release download` → GitHub API fallback | `gh auth login` or `GITHUB_TOKEN` |

Adding future managers (e.g. `cargo`, `brew`, `pipx`) requires adding one function and one
dict entry in `packages/forge-cli/src/forge_cli/system_deps.py` — no other changes needed.

### Registry file

[`plugins-registry.yaml`](../packages/forge-cli/src/forge_cli/data/plugins-registry.yaml) — the authoritative list of external plugins.
