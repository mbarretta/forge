# FORGE Implementation Plan

> **ARCHIVED** — This document describes the original API + Web UI architecture, which was
> removed in favour of a CLI-only single-user design. See `README.md` and
> `plans/FORGE_PLUGIN_DEVELOPMENT_GUIDE.md` for current architecture documentation.
> The content below is preserved for historical reference only.

---

## Overview

FORGE is a meta-tool that unifies Chainguard field engineering tools (Gauge, ILS-Fetcher, Verify-Provenance, and future tools) under a single CLI and web application. It uses a plugin architecture so tools can be added without modifying FORGE itself.

**Two execution modes:**
1. **CLI** — `forge gauge scan ...`, `forge ils fetch ...` — runs plugins in-process on a local machine
2. **Web service** — `forge serve` locally or deployed to Kubernetes — FastAPI + React, async job execution via workers, scales to hundreds of concurrent users

**Key architectural decision:** Every tool implements the same `ToolPlugin` protocol. The CLI runs plugins directly. The web service wraps the same plugins in async jobs via ARQ (Redis-backed task queue). The plugin author writes zero web/API code.

---

## Table of Contents

1. [Project Structure](#1-project-structure)
2. [Package: forge-core](#2-package-forge-core)
3. [Package: forge-cli](#3-package-forge-cli)
4. [Package: forge-api](#4-package-forge-api)
5. [Package: forge-ui](#5-package-forge-ui)
6. [Tool Plugin Packages](#6-tool-plugin-packages)
7. [Migrating Existing Tools](#7-migrating-existing-tools)
8. [Installation and Updates](#8-installation-and-updates)
9. [Container Images](#9-container-images)
10. [Kubernetes Deployment](#10-kubernetes-deployment)
11. [CI/CD](#11-cicd)
12. [Development Workflow](#12-development-workflow)
13. [Implementation Order](#13-implementation-order)

---

## 1. Project Structure

```
forge/
├── pyproject.toml                          # uv workspace root
├── uv.lock                                 # lockfile (auto-generated)
├── Makefile                                # dev commands
├── .github/
│   └── workflows/
│       ├── ci.yml                          # lint, type-check, test on PR
│       └── release.yml                     # build + push images on tag
├── docker-compose.yml                      # local dev: api + worker + redis
│
├── packages/
│   ├── forge-core/                         # shared kernel
│   │   ├── pyproject.toml
│   │   └── src/forge_core/
│   │       ├── __init__.py
│   │       ├── plugin.py                   # ToolPlugin protocol + ToolResult
│   │       ├── context.py                  # ExecutionContext
│   │       ├── registry.py                 # plugin discovery via entry_points
│   │       ├── auth.py                     # chainctl auth helpers
│   │       └── deps.py                     # external tool dependency checking
│   │
│   ├── forge-cli/                          # CLI entry point
│   │   ├── pyproject.toml
│   │   └── src/forge_cli/
│   │       ├── __init__.py
│   │       ├── main.py                     # CLI dispatcher
│   │       └── runner.py                   # in-process plugin runner
│   │
│   ├── forge-api/                          # FastAPI web service
│   │   ├── pyproject.toml
│   │   └── src/forge_api/
│   │       ├── __init__.py
│   │       ├── app.py                      # FastAPI app factory
│   │       ├── config.py                   # settings via pydantic-settings
│   │       ├── models.py                   # Pydantic request/response schemas
│   │       ├── worker.py                   # ARQ worker + task definitions
│   │       └── routes/
│   │           ├── __init__.py
│   │           ├── tools.py                # GET /api/tools
│   │           ├── jobs.py                 # POST/GET /api/jobs, WS streaming
│   │           └── health.py               # GET /healthz, /readyz
│   │
│   ├── forge-ui/                           # React SPA
│   │   ├── package.json
│   │   ├── tsconfig.json
│   │   ├── vite.config.ts
│   │   └── src/
│   │       ├── main.tsx
│   │       ├── App.tsx
│   │       ├── api/                        # API client (generated from OpenAPI)
│   │       ├── components/
│   │       └── pages/
│   │
│   ├── forge-gauge/                        # tool plugin: gauge
│   │   ├── pyproject.toml
│   │   └── src/forge_gauge/
│   │       ├── __init__.py
│   │       ├── plugin.py
│   │       └── ... (migrated gauge source)
│   │
│   ├── forge-ils/                          # tool plugin: ils-fetcher
│   │   ├── pyproject.toml
│   │   └── src/forge_ils/
│   │       ├── __init__.py
│   │       ├── plugin.py
│   │       └── ... (migrated ils-fetcher source)
│   │
│   └── forge-provenance/                   # tool plugin: verify-provenance
│       ├── pyproject.toml
│       └── src/forge_provenance/
│           ├── __init__.py
│           ├── plugin.py
│           └── ... (migrated verify-provenance source)
│
├── deploy/
│   ├── Dockerfile.api                      # API server image
│   ├── Dockerfile.worker                   # Worker image
│   ├── Dockerfile.ui                       # UI static build
│   └── helm/
│       └── forge/
│           ├── Chart.yaml
│           ├── values.yaml
│           ├── templates/
│           │   ├── api-deployment.yaml
│           │   ├── api-service.yaml
│           │   ├── worker-deployment.yaml
│           │   ├── redis-deployment.yaml
│           │   ├── redis-service.yaml
│           │   ├── ui-deployment.yaml
│           │   ├── ui-service.yaml
│           │   ├── ingress.yaml
│           │   └── configmap.yaml
│           └── values.prod.yaml
│
└── tests/
    ├── unit/
    │   ├── test_plugin_protocol.py
    │   ├── test_registry.py
    │   ├── test_context.py
    │   └── test_runner.py
    ├── integration/
    │   ├── test_api_routes.py
    │   └── test_worker.py
    └── e2e/
        └── test_cli.py
```

---

## 2. Package: forge-core

This is the shared kernel. It has **zero framework dependencies** — only stdlib and typing. Every other package depends on it.

### 2.1 pyproject.toml

```toml
[project]
name = "forge-core"
version = "0.1.0"
description = "Core plugin protocol and utilities for FORGE"
requires-python = ">=3.12"
license = { text = "Apache-2.0" }
# No dependencies — stdlib only

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/forge_core"]

[tool.mypy]
python_version = "3.12"
strict = true

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP", "B", "C4", "SIM"]
```

### 2.2 plugin.py — The ToolPlugin Protocol

This is the **central abstraction** of the entire system. Every tool implements this.

```python
"""Plugin protocol that all FORGE tools must implement."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class ResultStatus(Enum):
    """Outcome of a tool run."""
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ToolResult:
    """Returned by every plugin run.

    Attributes:
        status: Overall outcome.
        summary: Human-readable one-line summary.
        data: Arbitrary structured output (must be JSON-serializable).
        artifacts: Mapping of artifact name to file path for any files
                   the tool produced (reports, CSVs, SBOMs, etc.).
    """
    status: ResultStatus
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolParam:
    """Declares a parameter that the tool accepts.

    Used by the CLI to build argparse arguments and by the API
    to build request schemas.

    Attributes:
        name: Parameter name (used as CLI flag --name and JSON key).
        description: Help text.
        type: Python type name as string: "str", "int", "float", "bool".
        required: Whether the parameter must be provided.
        default: Default value if not required.
        choices: Optional list of allowed values.
    """
    name: str
    description: str
    type: str = "str"
    required: bool = False
    default: Any = None
    choices: list[str] | None = None


@runtime_checkable
class ToolPlugin(Protocol):
    """Protocol that every FORGE tool must implement.

    A tool plugin provides:
    - Metadata (name, description, version)
    - Parameter declarations (so CLI and API can auto-generate interfaces)
    - A run method that does the actual work

    Example implementation:

        class MyPlugin:
            name = "my-tool"
            description = "Does something useful"
            version = "1.0.0"

            def get_params(self) -> list[ToolParam]:
                return [
                    ToolParam(name="org", description="Target org", required=True),
                    ToolParam(name="limit", description="Max items", type="int", default=0),
                ]

            def run(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
                org = args["org"]
                ctx.progress(0.0, f"Starting scan of {org}")
                # ... do work ...
                ctx.progress(1.0, "Done")
                return ToolResult(status=ResultStatus.SUCCESS, summary="Scanned 42 images")
    """

    name: str
    description: str
    version: str

    def get_params(self) -> list[ToolParam]:
        """Declare the parameters this tool accepts."""
        ...

    def run(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        """Execute the tool.

        Args:
            args: Dictionary of parameter values. Keys match ToolParam.name.
                  Values are already coerced to the declared types.
            ctx: Execution context providing auth, progress reporting,
                 and cancellation.

        Returns:
            ToolResult with status, summary, optional data and artifacts.
        """
        ...
```

**Important design notes for implementers:**
- `name` is the CLI subcommand name: `forge <name> [args]`
- `get_params()` returns a static list. The CLI uses it to build argparse. The API uses it to build Pydantic models. The UI uses it to render form fields.
- `run()` receives a plain `dict[str, Any]` — not argparse.Namespace. This keeps it framework-agnostic.
- `run()` receives an `ExecutionContext` for auth, progress, and cancellation.

### 2.3 context.py — ExecutionContext

```python
"""Execution context passed to every plugin run."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class ExecutionContext:
    """Context provided to plugins during execution.

    Attributes:
        auth_token: Chainguard auth token (from chainctl).
        config: Arbitrary configuration dict (from env vars or config file).
        on_progress: Callback to report progress. Called with (fraction, message)
                     where fraction is 0.0-1.0.
        cancel_event: Threading event that is set when cancellation is requested.
                      Plugins should check this periodically in long-running loops.
    """
    auth_token: str = ""
    config: dict = field(default_factory=dict)
    on_progress: Callable[[float, str], None] = field(default=lambda f, m: None)
    cancel_event: threading.Event = field(default_factory=threading.Event)

    def progress(self, fraction: float, message: str) -> None:
        """Report progress. Convenience wrapper around on_progress."""
        self.on_progress(fraction, message)

    @property
    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested."""
        return self.cancel_event.is_set()
```

### 2.4 registry.py — Plugin Discovery

Uses Python's standard `importlib.metadata.entry_points` to discover plugins.

```python
"""Discover and load ToolPlugin implementations via entry_points."""

from __future__ import annotations

import importlib.metadata
import logging
from typing import Any

from forge_core.plugin import ToolPlugin

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "forge.plugins"


def discover_plugins() -> dict[str, ToolPlugin]:
    """Find all installed packages that declare a forge.plugins entry point.

    Each entry point must resolve to a callable that returns a ToolPlugin instance.
    Convention: the entry point value is a module-level function called `create_plugin`.

    Example pyproject.toml entry in a tool plugin package:

        [project.entry-points."forge.plugins"]
        gauge = "forge_gauge:create_plugin"

    Returns:
        Dict mapping plugin name to plugin instance.
    """
    plugins: dict[str, ToolPlugin] = {}

    eps = importlib.metadata.entry_points()
    forge_eps = eps.select(group=ENTRY_POINT_GROUP)

    for ep in forge_eps:
        try:
            factory = ep.load()
            plugin = factory()

            if not isinstance(plugin, ToolPlugin):
                logger.warning(
                    "Entry point '%s' returned %s, expected ToolPlugin. Skipping.",
                    ep.name,
                    type(plugin).__name__,
                )
                continue

            if plugin.name in plugins:
                logger.warning(
                    "Duplicate plugin name '%s' from entry point '%s'. Skipping.",
                    plugin.name,
                    ep.name,
                )
                continue

            plugins[plugin.name] = plugin
            logger.info("Loaded plugin: %s v%s", plugin.name, plugin.version)

        except Exception:
            logger.exception("Failed to load plugin from entry point '%s'", ep.name)

    return plugins
```

### 2.5 auth.py — Chainctl Auth Helper

```python
"""Authentication helpers for Chainguard tools."""

from __future__ import annotations

import shutil
import subprocess


def get_chainctl_token(timeout: int = 30) -> str:
    """Get an auth token from chainctl.

    Returns:
        Token string.

    Raises:
        RuntimeError: If chainctl is not installed or not authenticated.
    """
    if shutil.which("chainctl") is None:
        raise RuntimeError(
            "chainctl is not installed. "
            "Install from https://edu.chainguard.dev/chainguard/administration/how-to-install-chainctl/"
        )

    try:
        result = subprocess.run(
            ["chainctl", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"chainctl auth failed. Run 'chainctl auth login' first. Error: {e.stderr}"
        ) from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"chainctl auth timed out after {timeout}s") from e


def check_tool_available(tool_name: str) -> bool:
    """Check if a CLI tool is available on PATH."""
    return shutil.which(tool_name) is not None
```

### 2.6 deps.py — Dependency Checking

```python
"""Check external tool dependencies."""

from __future__ import annotations

import shutil
from dataclasses import dataclass


@dataclass(frozen=True)
class DependencyCheck:
    """Result of checking a required external tool."""
    name: str
    available: bool
    path: str | None


def check_dependencies(required: list[str]) -> list[DependencyCheck]:
    """Check that all required CLI tools are installed.

    Args:
        required: List of tool names (e.g. ["chainctl", "crane", "cosign"]).

    Returns:
        List of DependencyCheck results.
    """
    results = []
    for tool in required:
        path = shutil.which(tool)
        results.append(DependencyCheck(name=tool, available=path is not None, path=path))
    return results


def assert_dependencies(required: list[str]) -> None:
    """Check dependencies and raise if any are missing.

    Raises:
        RuntimeError: With list of missing tools.
    """
    checks = check_dependencies(required)
    missing = [c.name for c in checks if not c.available]
    if missing:
        raise RuntimeError(f"Missing required tools: {', '.join(missing)}")
```

---

## 3. Package: forge-cli

The CLI is a thin dispatcher. It discovers plugins, builds an argparse interface from their `get_params()`, and runs them in-process.

### 3.1 pyproject.toml

```toml
[project]
name = "forge-cli"
version = "0.1.0"
description = "FORGE CLI - unified Chainguard field engineering toolkit"
requires-python = ">=3.12"
license = { text = "Apache-2.0" }
dependencies = [
    "forge-core",
]

[project.scripts]
forge = "forge_cli.main:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/forge_cli"]
```

### 3.2 main.py — CLI Entry Point

```python
"""FORGE CLI entry point.

Usage:
    forge                           Show help and list available tools
    forge <tool> [args]             Run a tool
    forge <tool> --help             Show tool-specific help
    forge serve                     Start the web server (requires forge-api)
    forge --version                 Show version
"""

from __future__ import annotations

import argparse
import sys

from forge_core.registry import discover_plugins

FORGE_BANNER = r"""
   ███████╗ ██████╗ ██████╗  ██████╗ ███████╗
   ██╔════╝██╔═══██╗██╔══██╗██╔════╝ ██╔════╝
   █████╗  ██║   ██║██████╔╝██║  ███╗█████╗
   ██╔══╝  ██║   ██║██╔══██╗██║   ██║██╔══╝
   ██║     ╚██████╔╝██║  ██║╚██████╔╝███████╗
   ╚═╝      ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚══════╝
"""

__version__ = "0.1.0"


def show_help(plugins: dict) -> None:
    """Print help with available tools."""
    print(FORGE_BANNER)
    print(f"  FORGE v{__version__} — Chainguard Field Engineering Toolkit\n")
    print("Usage: forge <tool> [options]\n")
    print("Available tools:")
    for name, plugin in sorted(plugins.items()):
        print(f"  {name:<20} {plugin.description}")
    print()
    print("Global options:")
    print("  --version, -V        Show version")
    print("  --help, -h           Show this help")
    print()
    print("Use 'forge <tool> --help' for tool-specific options.")


def main() -> None:
    """Main entry point."""
    plugins = discover_plugins()

    # No arguments — show help
    if len(sys.argv) < 2:
        show_help(plugins)
        sys.exit(0)

    command = sys.argv[1]

    # Global flags
    if command in ("-h", "--help"):
        show_help(plugins)
        sys.exit(0)

    if command in ("-V", "--version"):
        print(f"forge {__version__}")
        sys.exit(0)

    # "serve" subcommand — delegate to forge-api if installed
    if command == "serve":
        _launch_server(sys.argv[2:])
        return

    # Tool dispatch
    if command not in plugins:
        print(f"Unknown tool: {command}")
        print()
        show_help(plugins)
        sys.exit(1)

    plugin = plugins[command]

    # Build argparse from plugin params
    parser = argparse.ArgumentParser(
        prog=f"forge {plugin.name}",
        description=plugin.description,
    )

    from forge_cli.runner import add_params_to_parser, run_plugin

    add_params_to_parser(parser, plugin.get_params())

    # Remove the tool name from argv so argparse sees only the tool's args
    args = parser.parse_args(sys.argv[2:])
    exit_code = run_plugin(plugin, vars(args))
    sys.exit(exit_code)


def _launch_server(argv: list[str]) -> None:
    """Start the FORGE API server. Requires forge-api to be installed."""
    try:
        from forge_api.app import create_app
        import uvicorn
    except ImportError:
        print("Error: forge-api is not installed.")
        print("Install it with: uv pip install -e packages/forge-api")
        sys.exit(1)

    # Parse serve-specific args
    parser = argparse.ArgumentParser(prog="forge serve")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Bind port (default: 8080)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for dev")
    args = parser.parse_args(argv)

    app = create_app()
    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)
```

### 3.3 runner.py — In-Process Plugin Execution

```python
"""Run a plugin in-process with console progress output."""

from __future__ import annotations

import sys
import threading
from typing import Any

from forge_core.auth import get_chainctl_token
from forge_core.context import ExecutionContext
from forge_core.plugin import ToolParam, ToolPlugin, ResultStatus


# Map ToolParam.type strings to Python types for argparse
TYPE_MAP: dict[str, type] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
}


def add_params_to_parser(parser, params: list[ToolParam]) -> None:
    """Add ToolParam declarations to an argparse.ArgumentParser.

    Args:
        parser: The ArgumentParser to add arguments to.
        params: List of ToolParam from plugin.get_params().
    """
    for param in params:
        flag = f"--{param.name}"
        kwargs: dict[str, Any] = {
            "help": param.description,
        }

        if param.type == "bool":
            # Boolean params become --flag / --no-flag
            kwargs["action"] = "store_true"
            kwargs["default"] = param.default if param.default is not None else False
        else:
            kwargs["type"] = TYPE_MAP.get(param.type, str)
            kwargs["required"] = param.required
            if param.default is not None:
                kwargs["default"] = param.default
            if param.choices:
                kwargs["choices"] = param.choices

        parser.add_argument(flag, **kwargs)


def _console_progress(fraction: float, message: str) -> None:
    """Print progress to stderr."""
    pct = int(fraction * 100)
    print(f"  [{pct:3d}%] {message}", file=sys.stderr, flush=True)


def run_plugin(plugin: ToolPlugin, args: dict[str, Any]) -> int:
    """Run a plugin in-process and return an exit code.

    Args:
        plugin: The plugin to run.
        args: Dict of parsed arguments.

    Returns:
        0 on success, 1 on failure.
    """
    # Get auth token
    try:
        token = get_chainctl_token()
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    ctx = ExecutionContext(
        auth_token=token,
        on_progress=_console_progress,
        cancel_event=threading.Event(),
    )

    try:
        result = plugin.run(args, ctx)
    except KeyboardInterrupt:
        ctx.cancel_event.set()
        print("\nCancelled.", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Print result summary
    print(f"\n{result.summary}")

    if result.artifacts:
        print("\nArtifacts:")
        for name, path in result.artifacts.items():
            print(f"  {name}: {path}")

    return 0 if result.status == ResultStatus.SUCCESS else 1
```

---

## 4. Package: forge-api

The web service. Stateless FastAPI app + ARQ workers connected via Redis.

### 4.1 pyproject.toml

```toml
[project]
name = "forge-api"
version = "0.1.0"
description = "FORGE API server and async job worker"
requires-python = ">=3.12"
license = { text = "Apache-2.0" }
dependencies = [
    "forge-core",
    "fastapi>=0.115.0,<1.0.0",
    "uvicorn[standard]>=0.30.0,<1.0.0",
    "arq>=0.26.0,<1.0.0",
    "redis>=5.0.0,<6.0.0",
    "pydantic-settings>=2.0.0,<3.0.0",
    "websockets>=13.0,<15.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/forge_api"]
```

### 4.2 config.py — Settings

```python
"""Application settings loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """FORGE API settings.

    All values can be overridden via environment variables with the
    FORGE_ prefix. Example: FORGE_REDIS_URL=redis://my-redis:6379
    """

    redis_url: str = "redis://localhost:6379"
    cors_origins: list[str] = ["http://localhost:5173"]  # Vite dev server
    api_prefix: str = "/api"
    job_timeout_seconds: int = 600  # 10 minutes max per job
    job_result_ttl_seconds: int = 3600  # keep results for 1 hour

    model_config = {"env_prefix": "FORGE_"}
```

### 4.3 models.py — Request/Response Schemas

```python
"""Pydantic models for API request and response bodies."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ToolInfo(BaseModel):
    """Information about an available tool (returned by GET /api/tools)."""
    name: str
    description: str
    version: str
    params: list[ParamInfo]


class ParamInfo(BaseModel):
    """Parameter declaration for a tool."""
    name: str
    description: str
    type: str
    required: bool
    default: Any = None
    choices: list[str] | None = None


class JobCreateRequest(BaseModel):
    """Request body for POST /api/jobs."""
    tool: str
    args: dict[str, Any] = {}


class JobResponse(BaseModel):
    """Response body for job operations."""
    id: str
    tool: str
    status: JobStatus
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    progress: float = 0.0
    progress_message: str = ""
    summary: str | None = None
    data: dict[str, Any] | None = None
    artifacts: dict[str, str] | None = None
    error: str | None = None


class ProgressEvent(BaseModel):
    """WebSocket message for real-time progress updates."""
    job_id: str
    progress: float
    message: str
    status: JobStatus
```

### 4.4 app.py — FastAPI Application Factory

```python
"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from forge_api.config import Settings
from forge_api.routes import health, jobs, tools


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle.

    Creates and tears down the Redis connection pool used for
    job status and progress pub/sub.
    """
    import redis.asyncio as aioredis

    settings: Settings = app.state.settings
    app.state.redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    yield

    await app.state.redis.aclose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        settings: Optional settings override (useful for testing).

    Returns:
        Configured FastAPI app.
    """
    if settings is None:
        settings = Settings()

    app = FastAPI(
        title="FORGE API",
        description="Chainguard Field Engineering Toolkit",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.state.settings = settings

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routes
    prefix = settings.api_prefix
    app.include_router(health.router, tags=["health"])
    app.include_router(tools.router, prefix=prefix, tags=["tools"])
    app.include_router(jobs.router, prefix=prefix, tags=["jobs"])

    return app
```

### 4.5 routes/tools.py — Tool Listing

```python
"""Tool listing endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from forge_api.models import ParamInfo, ToolInfo
from forge_core.registry import discover_plugins

router = APIRouter()


@router.get("/tools", response_model=list[ToolInfo])
async def list_tools() -> list[ToolInfo]:
    """List all available tools and their parameters."""
    plugins = discover_plugins()
    result = []
    for plugin in sorted(plugins.values(), key=lambda p: p.name):
        params = [
            ParamInfo(
                name=p.name,
                description=p.description,
                type=p.type,
                required=p.required,
                default=p.default,
                choices=p.choices,
            )
            for p in plugin.get_params()
        ]
        result.append(
            ToolInfo(
                name=plugin.name,
                description=plugin.description,
                version=plugin.version,
                params=params,
            )
        )
    return result
```

### 4.6 routes/jobs.py — Job Management

```python
"""Job submission, status, and progress streaming endpoints."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.requests import Request

from forge_api.models import JobCreateRequest, JobResponse, JobStatus, ProgressEvent
from forge_core.registry import discover_plugins

router = APIRouter()

# Redis key prefixes
JOB_KEY = "forge:job:"          # Hash: job metadata
JOB_PROGRESS = "forge:progress:"  # Pub/sub channel per job


@router.post("/jobs", response_model=JobResponse, status_code=201)
async def create_job(req: JobCreateRequest, request: Request) -> JobResponse:
    """Submit a new tool run as an async job.

    The job is enqueued to ARQ and executed by a worker process.
    Returns immediately with a job ID for polling or WebSocket streaming.
    """
    redis = request.app.state.redis
    settings = request.app.state.settings

    # Validate tool exists
    plugins = discover_plugins()
    if req.tool not in plugins:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {req.tool}")

    # Create job record
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    job_data = {
        "id": job_id,
        "tool": req.tool,
        "args": json.dumps(req.args),
        "status": JobStatus.QUEUED.value,
        "created_at": now.isoformat(),
        "progress": "0.0",
        "progress_message": "",
    }

    # Store in Redis
    await redis.hset(f"{JOB_KEY}{job_id}", mapping=job_data)
    await redis.expire(f"{JOB_KEY}{job_id}", settings.job_result_ttl_seconds)

    # Enqueue to ARQ
    from arq.connections import ArqRedis

    arq: ArqRedis = request.app.state.redis
    await arq.enqueue_job(
        "run_tool",
        job_id=job_id,
        tool_name=req.tool,
        tool_args=req.args,
        _job_id=job_id,
    )

    return JobResponse(
        id=job_id,
        tool=req.tool,
        status=JobStatus.QUEUED,
        created_at=now,
    )


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, request: Request) -> JobResponse:
    """Get current status of a job."""
    redis = request.app.state.redis
    data = await redis.hgetall(f"{JOB_KEY}{job_id}")

    if not data:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobResponse(
        id=data["id"],
        tool=data["tool"],
        status=JobStatus(data["status"]),
        created_at=datetime.fromisoformat(data["created_at"]),
        started_at=_parse_dt(data.get("started_at")),
        completed_at=_parse_dt(data.get("completed_at")),
        progress=float(data.get("progress", 0)),
        progress_message=data.get("progress_message", ""),
        summary=data.get("summary"),
        data=json.loads(data["result_data"]) if data.get("result_data") else None,
        artifacts=json.loads(data["artifacts"]) if data.get("artifacts") else None,
        error=data.get("error"),
    )


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(job_id: str, request: Request) -> JobResponse:
    """Request cancellation of a running job."""
    redis = request.app.state.redis

    # Signal cancellation via Redis pub/sub
    await redis.publish(f"forge:cancel:{job_id}", "cancel")
    await redis.hset(f"{JOB_KEY}{job_id}", "status", JobStatus.CANCELLED.value)

    return await get_job(job_id, request)


@router.websocket("/jobs/{job_id}/ws")
async def job_progress_ws(websocket: WebSocket, job_id: str) -> None:
    """WebSocket endpoint for real-time job progress.

    Subscribes to Redis pub/sub channel for the job and forwards
    progress events to the WebSocket client.
    """
    await websocket.accept()
    redis = websocket.app.state.redis

    pubsub = redis.pubsub()
    await pubsub.subscribe(f"{JOB_PROGRESS}{job_id}")

    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue

            event = json.loads(message["data"])
            await websocket.send_json(event)

            # Close when job is terminal
            if event.get("status") in (
                JobStatus.COMPLETED.value,
                JobStatus.FAILED.value,
                JobStatus.CANCELLED.value,
            ):
                break
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe(f"{JOB_PROGRESS}{job_id}")
        await pubsub.aclose()


def _parse_dt(val: str | None) -> datetime | None:
    """Parse ISO datetime string or return None."""
    if val:
        return datetime.fromisoformat(val)
    return None
```

### 4.7 routes/health.py

```python
"""Health check endpoints for Kubernetes probes."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.requests import Request

router = APIRouter()


@router.get("/healthz")
async def health() -> dict:
    """Liveness probe. Returns 200 if the process is running."""
    return {"status": "ok"}


@router.get("/readyz")
async def ready(request: Request) -> dict:
    """Readiness probe. Returns 200 if Redis is reachable."""
    try:
        redis = request.app.state.redis
        await redis.ping()
        return {"status": "ready"}
    except Exception as e:
        return {"status": "not ready", "error": str(e)}
```

### 4.8 worker.py — ARQ Worker

This is the process that actually runs tools. It runs separately from the API.

```python
"""ARQ worker that executes tool plugins as async jobs.

Start with:
    arq forge_api.worker.WorkerSettings
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any

from arq import cron
from arq.connections import ArqRedis, RedisSettings

from forge_core.auth import get_chainctl_token
from forge_core.context import ExecutionContext
from forge_core.plugin import ResultStatus
from forge_core.registry import discover_plugins

logger = logging.getLogger(__name__)

# Redis key prefixes (must match routes/jobs.py)
JOB_KEY = "forge:job:"
JOB_PROGRESS = "forge:progress:"


async def run_tool(
    ctx: dict[str, Any],
    *,
    job_id: str,
    tool_name: str,
    tool_args: dict[str, Any],
) -> None:
    """ARQ task function: run a tool plugin.

    Called by the ARQ worker when a job is dequeued from Redis.

    Args:
        ctx: ARQ worker context (contains 'redis' connection).
        job_id: Unique job identifier.
        tool_name: Name of the tool plugin to run.
        tool_args: Arguments to pass to plugin.run().
    """
    redis: ArqRedis = ctx["redis"]

    # Mark job as running
    now = datetime.now(timezone.utc).isoformat()
    await redis.hset(f"{JOB_KEY}{job_id}", mapping={
        "status": "running",
        "started_at": now,
    })

    # Load plugin
    plugins = discover_plugins()
    plugin = plugins.get(tool_name)
    if plugin is None:
        await _fail_job(redis, job_id, f"Plugin '{tool_name}' not found")
        return

    # Build progress callback that publishes to Redis
    async def _publish_progress(fraction: float, message: str) -> None:
        event = {
            "job_id": job_id,
            "progress": fraction,
            "message": message,
            "status": "running",
        }
        await redis.publish(f"{JOB_PROGRESS}{job_id}", json.dumps(event))
        await redis.hset(f"{JOB_KEY}{job_id}", mapping={
            "progress": str(fraction),
            "progress_message": message,
        })

    # Because plugin.run() is synchronous and may use threading internally,
    # we need a sync-to-async bridge for the progress callback.
    import asyncio
    loop = asyncio.get_event_loop()

    def sync_progress(fraction: float, message: str) -> None:
        asyncio.run_coroutine_threadsafe(_publish_progress(fraction, message), loop)

    # Set up cancellation listener
    cancel_event = threading.Event()

    async def _listen_for_cancel() -> None:
        pubsub = redis.pubsub()
        await pubsub.subscribe(f"forge:cancel:{job_id}")
        async for msg in pubsub.listen():
            if msg["type"] == "message":
                cancel_event.set()
                break
        await pubsub.unsubscribe(f"forge:cancel:{job_id}")
        await pubsub.aclose()

    cancel_task = asyncio.create_task(_listen_for_cancel())

    # Get auth token
    try:
        auth_token = get_chainctl_token()
    except RuntimeError as e:
        await _fail_job(redis, job_id, str(e))
        cancel_task.cancel()
        return

    # Build execution context
    exec_ctx = ExecutionContext(
        auth_token=auth_token,
        on_progress=sync_progress,
        cancel_event=cancel_event,
    )

    # Run the plugin in a thread to avoid blocking the async event loop
    try:
        result = await asyncio.to_thread(plugin.run, tool_args, exec_ctx)
    except Exception as e:
        logger.exception("Plugin '%s' raised an exception", tool_name)
        await _fail_job(redis, job_id, str(e))
        cancel_task.cancel()
        return

    cancel_task.cancel()

    # Store result
    completed_at = datetime.now(timezone.utc).isoformat()
    status = "completed" if result.status == ResultStatus.SUCCESS else "failed"

    await redis.hset(f"{JOB_KEY}{job_id}", mapping={
        "status": status,
        "completed_at": completed_at,
        "progress": "1.0",
        "progress_message": "Done",
        "summary": result.summary,
        "result_data": json.dumps(result.data),
        "artifacts": json.dumps(result.artifacts),
    })

    # Publish terminal event
    await redis.publish(f"{JOB_PROGRESS}{job_id}", json.dumps({
        "job_id": job_id,
        "progress": 1.0,
        "message": result.summary,
        "status": status,
    }))


async def _fail_job(redis: ArqRedis, job_id: str, error: str) -> None:
    """Mark a job as failed."""
    await redis.hset(f"{JOB_KEY}{job_id}", mapping={
        "status": "failed",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "error": error,
    })
    await redis.publish(f"{JOB_PROGRESS}{job_id}", json.dumps({
        "job_id": job_id,
        "progress": 0.0,
        "message": error,
        "status": "failed",
    }))


async def startup(ctx: dict[str, Any]) -> None:
    """ARQ worker startup hook."""
    logger.info("FORGE worker starting up")


async def shutdown(ctx: dict[str, Any]) -> None:
    """ARQ worker shutdown hook."""
    logger.info("FORGE worker shutting down")


class WorkerSettings:
    """ARQ worker configuration.

    Start the worker with:
        arq forge_api.worker.WorkerSettings
    """
    functions = [run_tool]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings()  # defaults to localhost:6379
    max_jobs = 10  # concurrent jobs per worker process
    job_timeout = 600  # 10 minutes
```

---

## 5. Package: forge-ui

React SPA built with Vite. Talks to the API.

### 5.1 Key Files

**package.json** — dependencies:
```json
{
  "name": "forge-ui",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "react-router-dom": "^7.0.0",
    "@tanstack/react-query": "^5.0.0"
  },
  "devDependencies": {
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "typescript": "^5.7.0",
    "vite": "^6.0.0",
    "@vitejs/plugin-react": "^4.0.0"
  }
}
```

### 5.2 Pages / Components (high-level)

The UI is intentionally simple at first:

1. **ToolListPage** — calls `GET /api/tools`, shows cards for each tool
2. **ToolRunPage** — for a given tool, renders a form from `params`, submits `POST /api/jobs`, opens WebSocket for progress, shows result
3. **JobHistoryPage** — lists recent jobs (from `GET /api/jobs?limit=50`)

The API's OpenAPI spec (auto-generated by FastAPI at `/docs`) can be used to generate a TypeScript client. Use `openapi-typescript-codegen` or `@hey-api/openapi-ts`.

### 5.3 vite.config.ts

```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8080",
      "/api/jobs/ws": {
        target: "ws://localhost:8080",
        ws: true,
      },
    },
  },
});
```

---

## 6. Tool Plugin Packages

Every tool plugin follows the same structure.

### 6.1 Anatomy of a Plugin Package

```
packages/forge-<name>/
├── pyproject.toml
└── src/forge_<name>/
    ├── __init__.py        # exports create_plugin()
    ├── plugin.py          # ToolPlugin implementation
    └── ...                # tool-specific modules
```

### 6.2 pyproject.toml Template

```toml
[project]
name = "forge-<name>"
version = "0.1.0"
description = "<one-line description>"
requires-python = ">=3.12"
license = { text = "Apache-2.0" }
dependencies = [
    "forge-core",
    # ... tool-specific deps
]

[project.entry-points."forge.plugins"]
<name> = "forge_<name>:create_plugin"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/forge_<name>"]
```

**Critical:** The `[project.entry-points."forge.plugins"]` section is what makes the plugin discoverable. The key (`<name>`) is the entry point name. The value is a dotted path to a callable that returns a `ToolPlugin` instance.

### 6.3 __init__.py Template

```python
"""FORGE plugin: <name>."""

from forge_<name>.plugin import <Name>Plugin


def create_plugin() -> <Name>Plugin:
    """Entry point for forge plugin discovery."""
    return <Name>Plugin()
```

### 6.4 plugin.py Template

```python
"""ToolPlugin implementation for <name>."""

from __future__ import annotations

from typing import Any

from forge_core.context import ExecutionContext
from forge_core.plugin import ToolParam, ToolResult, ResultStatus


class <Name>Plugin:
    name = "<name>"
    description = "<one-line description>"
    version = "0.1.0"

    def get_params(self) -> list[ToolParam]:
        return [
            ToolParam(
                name="<param>",
                description="<desc>",
                required=True,
            ),
            # ... more params
        ]

    def run(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        # Access args
        param_value = args["<param>"]

        # Report progress
        ctx.progress(0.0, "Starting...")

        # Check cancellation in loops
        for i, item in enumerate(items):
            if ctx.is_cancelled:
                return ToolResult(
                    status=ResultStatus.CANCELLED,
                    summary="Cancelled by user",
                )
            # ... do work ...
            ctx.progress((i + 1) / len(items), f"Processing {item}")

        return ToolResult(
            status=ResultStatus.SUCCESS,
            summary=f"Processed {len(items)} items",
            data={"count": len(items)},
            artifacts={"report": "/path/to/report.csv"},
        )
```

---

## 7. Migrating Existing Tools

### 7.1 Migrating verify-provenance → forge-provenance

This is the simplest migration because verify-provenance is a single file with no external Python dependencies.

**Step-by-step:**

1. Create `packages/forge-provenance/` with the directory structure from section 6.1.

2. Create `pyproject.toml`:
   ```toml
   [project]
   name = "forge-provenance"
   version = "0.1.0"
   description = "Verify Chainguard image provenance and delivery authenticity"
   requires-python = ">=3.12"
   license = { text = "Apache-2.0" }
   dependencies = ["forge-core"]

   [project.entry-points."forge.plugins"]
   provenance = "forge_provenance:create_plugin"

   [build-system]
   requires = ["hatchling"]
   build-backend = "hatchling.build"

   [tool.hatch.build.targets.wheel]
   packages = ["src/forge_provenance"]
   ```

3. Copy the existing `verify_provenance.py` into `src/forge_provenance/core.py`. Remove the `main()` function and `argparse` setup from it — those become part of `plugin.py`.

4. Create `src/forge_provenance/plugin.py`:
   ```python
   from __future__ import annotations
   from typing import Any
   from forge_core.context import ExecutionContext
   from forge_core.deps import assert_dependencies
   from forge_core.plugin import ToolParam, ToolResult, ResultStatus

   # Import the existing logic
   from forge_provenance.core import (
       get_image_list,
       verify_image,
       VerificationResult,
   )

   REQUIRED_TOOLS = ["chainctl", "crane", "cosign"]

   class ProvenancePlugin:
       name = "provenance"
       description = "Verify Chainguard image provenance and delivery authenticity"
       version = "0.1.0"

       def get_params(self) -> list[ToolParam]:
           return [
               ToolParam(name="customer-org", description="Customer organization to verify", required=True),
               ToolParam(name="full", description="Full verification mode (includes reference org check)", type="bool"),
               ToolParam(name="verify-signatures", description="Enable cryptographic signature verification", type="bool"),
               ToolParam(name="limit", description="Max images to check (0 = all)", type="int", default=0),
           ]

       def run(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
           assert_dependencies(REQUIRED_TOOLS)

           customer_org = args["customer-org"]
           full_mode = args.get("full", False)
           verify_sigs = args.get("verify-signatures", False) or full_mode
           limit = args.get("limit", 0)
           customer_only = not full_mode

           ctx.progress(0.0, f"Fetching images for '{customer_org}'")
           images = get_image_list(customer_org)
           if not images:
               return ToolResult(status=ResultStatus.FAILURE, summary="No images found")

           if limit > 0:
               images = images[:limit]

           results: list[VerificationResult] = []
           for i, img in enumerate(images):
               if ctx.is_cancelled:
                   return ToolResult(status=ResultStatus.CANCELLED, summary="Cancelled")

               result = verify_image(
                   img, "cgr.dev", customer_org, "chainguard-private",
                   verify_sigs, capture_details=True, customer_only=customer_only,
               )
               results.append(result)
               ctx.progress((i + 1) / len(images), f"Verified {img}: {result.status}")

           # ... write CSV, compute summary counts ...

           verified = sum(1 for r in results if r.status in ("VERIFIED", "DELIVERY_VERIFIED"))
           return ToolResult(
               status=ResultStatus.SUCCESS,
               summary=f"Verified {verified}/{len(results)} images for {customer_org}",
               data={"results": [{"image": r.image, "status": r.status} for r in results]},
               artifacts={"csv": f"{customer_org}.csv"},
           )
   ```

5. Create `src/forge_provenance/__init__.py`:
   ```python
   from forge_provenance.plugin import ProvenancePlugin

   def create_plugin() -> ProvenancePlugin:
       return ProvenancePlugin()
   ```

### 7.2 Migrating ils-fetcher → forge-ils

Similar pattern. ILS-fetcher has two Python dependencies: `pyyaml` and `requests`.

1. Create `packages/forge-ils/` with standard structure.

2. `pyproject.toml` dependencies:
   ```toml
   dependencies = [
       "forge-core",
       "pyyaml>=6.0,<7.0",
       "requests>=2.32.0,<3.0.0",
   ]
   ```

3. Copy `ils_fetcher.py` into `src/forge_ils/core.py`. Remove `main()` and argparse. Keep all the functions: `get_auth_token`, `get_organizations`, `get_images`, `process_repo`, `generate_report`, etc.

4. **Key change in `generate_report`**: Replace `print()` progress statements with `ctx.progress()` calls. Replace `sys.exit(1)` with raising exceptions or returning error results. The function currently uses `ThreadPoolExecutor` — that's fine, keep it.

5. `plugin.py` params:
   ```python
   def get_params(self) -> list[ToolParam]:
       return [
           ToolParam(name="organization", description="Organization name or ID", required=False),
           ToolParam(name="output-dir", description="Output directory", default="output"),
           ToolParam(name="workers", description="Concurrent API workers", type="int", default=10),
           ToolParam(name="skip-sbom", description="Skip SBOM downloads", type="bool"),
           ToolParam(name="skip-advisory", description="Skip advisory data fetch", type="bool"),
       ]
   ```

6. **Note on interactive prompts**: The current `ils_fetcher.py` prompts the user to select an org if `--organization` is not specified. In the FORGE plugin, make `organization` required instead (the web UI will provide a dropdown, the CLI requires the flag). Move org-listing to a separate helper or a dedicated endpoint.

### 7.3 Migrating gauge → forge-gauge

Gauge has its own internal plugin system with multiple plugins (gauge-core, dhi-compete, ecosystems-coverage, plugin-manager). **FORGE replaces that internal plugin system entirely.** Only the gauge-core plugin's functionality migrates into `forge-gauge`. The other gauge plugins become independent FORGE plugins later (forge-dhi-compete, forge-coverage, etc.). Gauge's PluginRegistry, GaugePlugin base class, and plugin discovery code are not migrated — FORGE provides all of that.

**What to migrate:** Only the gauge-core plugin's two commands — `scan` and `match` — plus the shared `core/`, `utils/`, and `constants.py` modules they depend on. Gauge's `update` command is not migrated — it is superseded by `forge update` (section 8).

**What to discard:**
- `src/core/command_plugin.py` (GaugePlugin base class — replaced by FORGE's ToolPlugin)
- `src/core/plugin_registry.py` (plugin discovery — replaced by FORGE's entry_points registry)
- `src/plugins/dhi_compete/` (becomes its own FORGE plugin later)
- `src/plugins/ecosystems_coverage/` (becomes its own FORGE plugin later)
- `src/plugins/plugin_manager/` (unnecessary — FORGE's entry_points discovery replaces it)
- `src/cli.py` (main dispatch — replaced by forge-cli)
- `src/__main__.py` (entry point — replaced by forge-cli)

**What to keep (under `src/forge_gauge/`):**
- `constants.py` — version, timeouts, URLs, LLM model config
- `common.py` — shared utilities
- `core/` — models, orchestration (minus command_plugin.py and plugin_registry.py)
- `utils/` — cve_ratios, image_classifier, console, version_check, etc.
- `plugins/gauge_core/scan_command.py` → `src/forge_gauge/commands/scan.py`
- `plugins/gauge_core/match_command.py` → `src/forge_gauge/commands/match.py`
- `outputs/` — HTML/XLSX report generation, styles, templates

**Step-by-step:**

1. Create `packages/forge-gauge/`.

2. `pyproject.toml` dependencies:
   ```toml
   dependencies = [
       "forge-core",
       "anthropic>=0.40.0,<1.0.0",
       "markdown>=3.0.0,<4.0.0",
       "pyyaml>=6.0,<7.0",
       "requests>=2.32.0,<3.0.0",
       "xlsxwriter>=3.2.0,<4.0.0",
   ]
   ```

3. Copy source selectively into `src/forge_gauge/`:
   ```
   src/forge_gauge/
   ├── __init__.py
   ├── plugin.py              # NEW: ToolPlugin implementation
   ├── constants.py            # from gauge src/constants.py
   ├── common.py               # from gauge src/common.py
   ├── core/                   # from gauge src/core/ (minus command_plugin.py, plugin_registry.py)
   │   ├── __init__.py
   │   ├── models.py
   │   └── ...
   ├── commands/               # extracted from gauge src/plugins/gauge_core/
   │   ├── __init__.py
   │   ├── scan.py             # from scan_command.py
   │   └── match.py            # from match_command.py
   ├── utils/                  # from gauge src/utils/
   │   ├── __init__.py
   │   └── ...
   └── outputs/                # from gauge src/outputs/ (HTML/XLSX generation)
       └── ...
   ```

4. Create `plugin.py` with a `command` parameter to route between scan/match/update:
   ```python
   class GaugePlugin:
       name = "gauge"
       description = "Container vulnerability assessment and image matching"
       version = "2.2.0"  # from constants.py

       def get_params(self) -> list[ToolParam]:
           return [
               ToolParam(name="command", description="Gauge command to run",
                         required=True, choices=["scan", "match"]),
               # Input/output (scan + match)
               ToolParam(name="input", description="Input CSV file or single image reference"),
               ToolParam(name="organization", description="Chainguard organization to scan"),
               ToolParam(name="output", description="Output types (comma-separated)"),
               ToolParam(name="output-dir", description="Output directory", default="."),
               ToolParam(name="customer", description="Customer name", default="Customer"),
               # Scan options
               ToolParam(name="max-workers", description="Parallel workers", type="int"),
               ToolParam(name="with-chps", description="Include CHPS scoring", type="bool"),
               ToolParam(name="with-fips", description="Include FIPS analysis", type="bool"),
               ToolParam(name="with-kevs", description="Include KEV data", type="bool"),
               ToolParam(name="with-all", description="Enable all optional features", type="bool"),
               ToolParam(name="resume", description="Resume from checkpoint", type="bool"),
               ToolParam(name="no-cache", description="Disable caching", type="bool"),
               # Matching options
               ToolParam(name="min-confidence", description="Min match confidence (0.0-1.0)"),
               ToolParam(name="disable-llm-matching", description="Disable LLM matching", type="bool"),
               ToolParam(name="llm-model", description="Claude model for LLM matching"),
               # General
               ToolParam(name="verbose", description="Enable verbose logging", type="bool"),
           ]

       def run(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
           command = args["command"]
           if command == "scan":
               return self._run_scan(args, ctx)
           elif command == "match":
               return self._run_match(args, ctx)
           return ToolResult(status=ResultStatus.FAILURE, summary=f"Unknown command: {command}")

       def _run_scan(self, args, ctx):
           from forge_gauge.commands.scan import execute_scan
           # Adapt execute_scan to use ctx for progress and return ToolResult
           ...

       def _run_match(self, args, ctx):
           from forge_gauge.commands.match import execute_match
           ...
   ```

5. **Import path fixup**: Update all internal imports in the copied source:
   - `from core.` → `from forge_gauge.core.`
   - `from utils.` → `from forge_gauge.utils.`
   - `from constants` → `from forge_gauge.constants`
   - `import common` → `from forge_gauge import common`
   - `from outputs.` → `from forge_gauge.outputs.`
   - Remove all imports of `GaugePlugin`, `CommandDefinition`, `PluginRegistry`

6. **Remove internal plugin machinery** from copied source:
   - Delete any `get_plugin()` factory functions
   - Delete any `GaugePlugin` subclass definitions in gauge-core
   - Delete `configure_*_parser()` functions (argument parsing is now handled by `get_params()`)
   - Refactor `execute_*()` functions to accept a plain `dict` + `ExecutionContext` instead of `argparse.Namespace`

7. **Progress integration**: Gauge's scan command uses `ThreadPoolExecutor`. Thread progress reporting through `ctx.progress()` in the main scan loop.

8. **Future gauge plugins as FORGE plugins**: When migrating dhi-compete or ecosystems-coverage later, each becomes its own top-level FORGE plugin package (e.g., `packages/forge-dhi-compete/`) following the standard plugin template. They do NOT live inside forge-gauge.

---

## 8. Installation and Updates

FORGE is distributed via `uv tool install`. Engineers do not need Python installed — `uv` is a single static Rust binary that bootstraps a managed Python interpreter automatically.

### 8.1 End-User Installation

```bash
# Install uv (one-time, if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install FORGE (installs forge-cli + all plugins in an isolated environment)
uv tool install forge --from git+https://github.com/chainguard/forge

# Verify
forge --version
forge version    # detailed: shows all plugin versions
```

The root `pyproject.toml` meta-package depends on `forge-cli` and all plugins, so `uv tool install forge` gets everything in one command. `uv` manages the Python interpreter and creates an isolated environment — the engineer never touches Python directly.

### 8.2 forge update — Built-In CLI Command

`forge update` replaces gauge's self-update mechanism. It updates the entire FORGE installation to the latest version from the repository.

```bash
# Update FORGE and all plugins to latest
forge update

# Check what would change without applying
forge update --dry-run
```

Output:
```
Updating FORGE...
  Fetching latest from git+https://github.com/chainguard/forge
  2 packages updated:
    forge-gauge      2.2.0 → 2.3.0
    forge-provenance 0.1.0 → 0.2.0
  1 package unchanged:
    forge-ils        0.1.0
```

Implementation: `forge update` calls `uv tool upgrade forge --from git+https://github.com/chainguard/forge` under the hood. It then runs `forge version` to show the result.

### 8.3 forge version — Built-In CLI Command

`forge version` shows the installed version of FORGE and every plugin.

```bash
$ forge version
FORGE v0.1.0
  gauge        2.3.0
  ils          0.1.0
  provenance   0.2.0
```

Implementation: iterates `discover_plugins()` and prints each plugin's `version` attribute.

### 8.4 Updated main.py with update and version Commands

The `main.py` from section 3.2 should include these built-in commands. Here are the additions:

```python
def main() -> None:
    """Main entry point."""
    plugins = discover_plugins()

    if len(sys.argv) < 2:
        show_help(plugins)
        sys.exit(0)

    command = sys.argv[1]

    if command in ("-h", "--help"):
        show_help(plugins)
        sys.exit(0)

    if command in ("-V", "--version"):
        print(f"forge {__version__}")
        sys.exit(0)

    # Built-in commands (not plugins)
    if command == "version":
        _show_version(plugins)
        sys.exit(0)

    if command == "update":
        sys.exit(_run_update(sys.argv[2:]))

    if command == "serve":
        _launch_server(sys.argv[2:])
        return

    # Plugin dispatch
    if command not in plugins:
        print(f"Unknown tool: {command}")
        print()
        show_help(plugins)
        sys.exit(1)

    # ... rest of plugin dispatch unchanged ...


def _show_version(plugins: dict) -> None:
    """Show FORGE version and all installed plugin versions."""
    print(f"FORGE v{__version__}")
    for name, plugin in sorted(plugins.items()):
        print(f"  {name:<20} {plugin.version}")


def _run_update(argv: list[str]) -> int:
    """Update FORGE and all plugins via uv tool upgrade."""
    import subprocess

    parser = argparse.ArgumentParser(prog="forge update")
    parser.add_argument("--dry-run", action="store_true", help="Check for updates without applying")
    args = parser.parse_args(argv)

    repo_url = "git+https://github.com/chainguard/forge"
    cmd = ["uv", "tool", "upgrade", "forge", "--from", repo_url]

    if args.dry_run:
        print("Checking for updates...")
        # uv tool upgrade with --dry-run is not supported, so we show current state
        print("Current versions:")
        plugins = discover_plugins()
        _show_version(plugins)
        return 0

    print("Updating FORGE...")
    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        print("Update failed.", file=sys.stderr)
        return 1

    # Show updated versions
    print()
    plugins = discover_plugins()
    _show_version(plugins)
    return 0
```

The `show_help()` function should also list these built-in commands:

```python
def show_help(plugins: dict) -> None:
    print(FORGE_BANNER)
    print(f"  FORGE v{__version__} — Chainguard Field Engineering Toolkit\n")
    print("Usage: forge <tool> [options]\n")
    print("Available tools:")
    for name, plugin in sorted(plugins.items()):
        print(f"  {name:<20} {plugin.description}")
    print()
    print("Built-in commands:")
    print(f"  {'update':<20} Update FORGE and all plugins to latest")
    print(f"  {'version':<20} Show FORGE and plugin versions")
    print(f"  {'serve':<20} Start the web server (requires forge-api)")
    print()
    print("Global options:")
    print("  --version, -V        Show version (short)")
    print("  --help, -h           Show this help")
    print()
    print("Use 'forge <tool> --help' for tool-specific options.")
```

### 8.5 Developer Installation

For contributors working on FORGE source:

```bash
git clone https://github.com/chainguard/forge
cd forge
uv sync          # installs all packages in dev mode
forge --version  # works immediately
```

### 8.6 Production Deployment

Production (Kubernetes) does not use `uv tool install`. Container images are built by CI/CD and deployed via Helm. See section 9 (Container Images) and section 10 (Kubernetes Deployment).

---

## 9. Container Images

All images use Chainguard base images from `cgr.dev/chainguard-private`.

### 9.1 Dockerfile.api (also used for worker with different CMD)

```dockerfile
# Build stage: install Python dependencies
FROM cgr.dev/chainguard-private/python:latest-dev AS builder

WORKDIR /app

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy workspace definition and lockfile
COPY pyproject.toml uv.lock ./
COPY packages/forge-core/pyproject.toml packages/forge-core/pyproject.toml
COPY packages/forge-api/pyproject.toml packages/forge-api/pyproject.toml

# Copy all plugin pyproject.toml files
COPY packages/forge-gauge/pyproject.toml packages/forge-gauge/pyproject.toml
COPY packages/forge-ils/pyproject.toml packages/forge-ils/pyproject.toml
COPY packages/forge-provenance/pyproject.toml packages/forge-provenance/pyproject.toml

# Install dependencies (cached layer)
RUN uv sync --frozen --no-install-project

# Copy source code
COPY packages/ packages/

# Install all packages
RUN uv sync --frozen


# Runtime stage: minimal image
FROM cgr.dev/chainguard-private/python:latest

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /app/.venv /app/.venv

# Ensure venv is on PATH
ENV PATH="/app/.venv/bin:$PATH"

# Install external CLI tools needed by plugins
# These should be available as Chainguard images or installed via apk
# For production, consider a sidecar or init container pattern for CLI tools
# that are large (chainctl, crane, cosign)

EXPOSE 8080

# Default: run API server
# Override with: command: ["arq", "forge_api.worker.WorkerSettings"] for worker
CMD ["uvicorn", "forge_api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
```

### 9.2 Dockerfile.worker

```dockerfile
# Same as Dockerfile.api but with different CMD and additional CLI tools
FROM cgr.dev/chainguard-private/python:latest-dev AS builder

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
COPY packages/ packages/

RUN uv sync --frozen


FROM cgr.dev/chainguard-private/python:latest

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Workers need CLI tools that plugins depend on.
# Copy chainctl, crane, cosign from their Chainguard images.
COPY --from=cgr.dev/chainguard-private/chainctl:latest /usr/bin/chainctl /usr/bin/chainctl
COPY --from=cgr.dev/chainguard-private/crane:latest /usr/bin/crane /usr/bin/crane
COPY --from=cgr.dev/chainguard-private/cosign:latest /usr/bin/cosign /usr/bin/cosign

CMD ["arq", "forge_api.worker.WorkerSettings"]
```

### 9.3 Dockerfile.ui

```dockerfile
# Build stage
FROM cgr.dev/chainguard-private/node:latest-dev AS builder

WORKDIR /app
COPY packages/forge-ui/package.json packages/forge-ui/package-lock.json ./
RUN npm ci
COPY packages/forge-ui/ ./
RUN npm run build

# Runtime stage: serve static files with nginx
FROM cgr.dev/chainguard-private/nginx:latest

COPY --from=builder /app/dist /usr/share/nginx/html
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
```

### 9.4 deploy/nginx.conf

```nginx
server {
    listen 8080;

    root /usr/share/nginx/html;
    index index.html;

    # SPA fallback
    location / {
        try_files $uri $uri/ /index.html;
    }

    # API proxy (handled by k8s ingress in production,
    # but useful for docker-compose local dev)
    location /api/ {
        proxy_pass http://forge-api:8080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

---

## 10. Kubernetes Deployment

### 10.1 Helm Chart: values.yaml

```yaml
# deploy/helm/forge/values.yaml

image:
  registry: cgr.dev/chainguard-private
  pullPolicy: IfNotPresent

api:
  image:
    repository: forge-api
    tag: latest
  replicas: 2
  resources:
    requests:
      cpu: 250m
      memory: 256Mi
    limits:
      cpu: 1000m
      memory: 512Mi
  port: 8080

worker:
  image:
    repository: forge-worker
    tag: latest
  replicas: 3
  resources:
    requests:
      cpu: 500m
      memory: 512Mi
    limits:
      cpu: 2000m
      memory: 2Gi
  maxJobs: 10

ui:
  image:
    repository: forge-ui
    tag: latest
  replicas: 2
  resources:
    requests:
      cpu: 100m
      memory: 64Mi
    limits:
      cpu: 200m
      memory: 128Mi
  port: 8080

redis:
  image:
    repository: redis
    tag: latest
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 500m
      memory: 256Mi
  port: 6379

ingress:
  enabled: true
  className: ""
  annotations: {}
  hosts:
    - host: forge.internal.chainguard.dev
      paths:
        - path: /api
          service: api
        - path: /
          service: ui

env:
  FORGE_REDIS_URL: "redis://forge-redis:6379"
  FORGE_CORS_ORIGINS: '["https://forge.internal.chainguard.dev"]'
```

### 10.2 Key Helm Templates

**api-deployment.yaml:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Release.Name }}-api
spec:
  replicas: {{ .Values.api.replicas }}
  selector:
    matchLabels:
      app: forge-api
  template:
    metadata:
      labels:
        app: forge-api
    spec:
      containers:
        - name: api
          image: "{{ .Values.image.registry }}/{{ .Values.api.image.repository }}:{{ .Values.api.image.tag }}"
          imagePullPolicy: {{ .Values.image.pullPolicy }}
          ports:
            - containerPort: {{ .Values.api.port }}
          envFrom:
            - configMapRef:
                name: {{ .Release.Name }}-config
          resources:
            {{- toYaml .Values.api.resources | nindent 12 }}
          livenessProbe:
            httpGet:
              path: /healthz
              port: {{ .Values.api.port }}
            initialDelaySeconds: 5
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /readyz
              port: {{ .Values.api.port }}
            initialDelaySeconds: 5
            periodSeconds: 5
```

**worker-deployment.yaml:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Release.Name }}-worker
spec:
  replicas: {{ .Values.worker.replicas }}
  selector:
    matchLabels:
      app: forge-worker
  template:
    metadata:
      labels:
        app: forge-worker
    spec:
      containers:
        - name: worker
          image: "{{ .Values.image.registry }}/{{ .Values.worker.image.repository }}:{{ .Values.worker.image.tag }}"
          imagePullPolicy: {{ .Values.image.pullPolicy }}
          envFrom:
            - configMapRef:
                name: {{ .Release.Name }}-config
          resources:
            {{- toYaml .Values.worker.resources | nindent 12 }}
          # Workers don't serve HTTP, so use exec probes
          livenessProbe:
            exec:
              command: ["python", "-c", "import forge_core; print('ok')"]
            initialDelaySeconds: 10
            periodSeconds: 30
```

**HPA for workers (values.prod.yaml):**
```yaml
worker:
  replicas: 3
  autoscaling:
    enabled: true
    minReplicas: 3
    maxReplicas: 20
    targetCPUUtilization: 70
```

---

## 11. CI/CD

### 11.1 .github/workflows/ci.yml

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync --frozen
      - run: uv run ruff check packages/
      - run: uv run ruff format --check packages/

  typecheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync --frozen
      - run: uv run mypy packages/forge-core/src packages/forge-cli/src packages/forge-api/src

  test:
    runs-on: ubuntu-latest
    services:
      redis:
        image: redis:7
        ports:
          - 6379:6379
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync --frozen
      - run: uv run pytest tests/ -v --cov=packages

  ui-build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
      - run: cd packages/forge-ui && npm ci && npm run build
```

### 11.2 .github/workflows/release.yml

```yaml
name: Release

on:
  push:
    tags: ["v*"]

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        image:
          - { dockerfile: deploy/Dockerfile.api, name: forge-api }
          - { dockerfile: deploy/Dockerfile.worker, name: forge-worker }
          - { dockerfile: deploy/Dockerfile.ui, name: forge-ui }
    steps:
      - uses: actions/checkout@v4

      - name: Login to registry
        uses: docker/login-action@v3
        with:
          registry: cgr.dev
          username: ${{ secrets.CGR_USERNAME }}
          password: ${{ secrets.CGR_PASSWORD }}

      - name: Build and push
        uses: docker/build-push-action@v6
        with:
          context: .
          file: ${{ matrix.image.dockerfile }}
          push: true
          tags: |
            cgr.dev/chainguard-private/${{ matrix.image.name }}:${{ github.ref_name }}
            cgr.dev/chainguard-private/${{ matrix.image.name }}:latest
```

---

## 12. Development Workflow

### 12.1 Root pyproject.toml (uv workspace)

```toml
[project]
name = "forge"
version = "0.1.0"
description = "FORGE — Chainguard Field Engineering Toolkit"
requires-python = ">=3.12"
license = { text = "Apache-2.0" }
# The root "forge" package is a meta-package that depends on forge-cli
# and all plugins. This is what end users install via:
#   uv tool install forge --from git+https://github.com/chainguard/forge
dependencies = [
    "forge-cli",
    "forge-gauge",
    "forge-ils",
    "forge-provenance",
]

[project.scripts]
forge = "forge_cli.main:main"

[tool.uv.workspace]
members = [
    "packages/forge-core",
    "packages/forge-cli",
    "packages/forge-api",
    "packages/forge-gauge",
    "packages/forge-ils",
    "packages/forge-provenance",
]

[tool.uv]
dev-dependencies = [
    "pytest>=8.0.0,<10.0.0",
    "pytest-cov>=5.0.0,<8.0.0",
    "pytest-asyncio>=0.24.0,<1.0.0",
    "httpx>=0.27.0,<1.0.0",
    "ruff>=0.8.0",
    "mypy>=1.13.0",
]
```

The root `forge` package serves as the installable meta-package. When a user runs `uv tool install forge`, they get forge-cli plus all plugins in one command. The `[project.scripts]` entry ensures the `forge` binary is created.

### 12.2 Makefile

```makefile
.PHONY: install lint format typecheck test serve worker dev clean

install:
	uv sync

lint:
	uv run ruff check packages/

format:
	uv run ruff format packages/

typecheck:
	uv run mypy packages/forge-core/src packages/forge-cli/src packages/forge-api/src

test:
	uv run pytest tests/ -v

# Run API server locally (requires Redis running)
serve:
	uv run forge serve --reload

# Run ARQ worker locally (requires Redis running)
worker:
	uv run arq forge_api.worker.WorkerSettings

# Run everything locally with docker-compose
dev:
	docker compose up --build

clean:
	rm -rf .venv __pycache__ .mypy_cache .pytest_cache .ruff_cache
	find packages -type d -name __pycache__ -exec rm -rf {} +
```

### 12.3 docker-compose.yml (local dev only)

```yaml
services:
  redis:
    image: cgr.dev/chainguard-private/redis:latest
    ports:
      - "6379:6379"

  api:
    build:
      context: .
      dockerfile: deploy/Dockerfile.api
    ports:
      - "8080:8080"
    environment:
      FORGE_REDIS_URL: redis://redis:6379
      FORGE_CORS_ORIGINS: '["http://localhost:5173"]'
    depends_on:
      - redis

  worker:
    build:
      context: .
      dockerfile: deploy/Dockerfile.worker
    environment:
      FORGE_REDIS_URL: redis://redis:6379
    depends_on:
      - redis

  ui:
    build:
      context: .
      dockerfile: deploy/Dockerfile.ui
    ports:
      - "3000:8080"
    depends_on:
      - api
```

### 12.4 Adding a New Tool (step-by-step)

1. **Create the package directory:**
   ```
   mkdir -p packages/forge-newtool/src/forge_newtool
   ```

2. **Copy the pyproject.toml template** from section 6.2. Change:
   - `name` to `"forge-newtool"`
   - `description` to your tool's description
   - Add any tool-specific `dependencies`
   - Set the entry point key to `newtool`

3. **Create `__init__.py`** following section 6.3.

4. **Create `plugin.py`** following section 6.4. Implement:
   - `name`, `description`, `version` attributes
   - `get_params()` returning your parameter declarations
   - `run()` with your tool logic, using `ctx.progress()` and checking `ctx.is_cancelled`

5. **Add to workspace** in root `pyproject.toml`:
   ```toml
   [tool.uv.workspace]
   members = [
       # ... existing members ...
       "packages/forge-newtool",
   ]
   ```

6. **Install:** `uv sync`

7. **Verify:** `forge newtool --help` should show your tool's params.

No changes to forge-cli, forge-api, or forge-ui are needed.

---

## 13. Implementation Order

Build in this order. Each phase is independently testable.

### Phase 1: Core + CLI (get tools running locally)

1. Create root `pyproject.toml` with uv workspace
2. Build `forge-core` (plugin.py, context.py, registry.py, auth.py, deps.py)
3. Build `forge-cli` (main.py, runner.py)
4. Create a "hello world" test plugin to verify the full plugin → discovery → CLI chain works
5. Write unit tests for forge-core (protocol conformance, registry discovery, param-to-argparse conversion)
6. Migrate `verify-provenance` → `forge-provenance` (simplest tool, good first migration)
7. Verify `forge provenance --customer-org test-org` works
8. Migrate `ils-fetcher` → `forge-ils`
9. Migrate `gauge` → `forge-gauge`
10. Set up Makefile, ruff, mypy

### Phase 2: API + Worker (enable web execution)

1. Build `forge-api` config and app factory
2. Implement health routes
3. Implement `GET /api/tools` route
4. Implement `POST /api/jobs` + `GET /api/jobs/{id}` routes
5. Implement `worker.py` with `run_tool` task
6. Implement WebSocket progress streaming
7. Implement job cancellation
8. Write integration tests (use `httpx.AsyncClient` + real Redis)
9. Add `forge serve` command to CLI
10. Test locally: `docker compose up`, submit a job via curl, observe progress

### Phase 3: UI

1. Scaffold React app with Vite
2. Build ToolListPage (calls `GET /api/tools`)
3. Build ToolRunPage (form from params, submit job, WebSocket progress)
4. Build JobHistoryPage
5. Add basic styling (Tailwind or similar)
6. Generate TypeScript API client from OpenAPI spec

### Phase 4: Containerization + Deployment

1. Write Dockerfile.api, Dockerfile.worker, Dockerfile.ui
2. Test with docker-compose
3. Create Helm chart
4. Create values.prod.yaml with HPA
5. Set up CI/CD workflows
6. Deploy to staging k8s cluster
7. Load test with multiple concurrent job submissions

---

## Appendix A: External CLI Tool Strategy for Containers

Several plugins require CLI tools (chainctl, crane, cosign, grype, syft). In containers:

**Approach: Multi-stage copy from Chainguard tool images.**

```dockerfile
COPY --from=cgr.dev/chainguard-private/chainctl:latest /usr/bin/chainctl /usr/bin/chainctl
COPY --from=cgr.dev/chainguard-private/crane:latest /usr/bin/crane /usr/bin/crane
COPY --from=cgr.dev/chainguard-private/cosign:latest /usr/bin/cosign /usr/bin/cosign
```

This keeps the worker image small while providing all required tools. Only the worker image needs these — the API image does not execute plugins directly.

**Authentication in k8s:** Use workload identity (GKE) or IRSA (EKS) to provide chainctl credentials to worker pods without storing secrets. Configure via Helm values:

```yaml
worker:
  serviceAccount:
    annotations:
      iam.gke.io/gcp-service-account: forge-worker@project.iam.gserviceaccount.com
```

## Appendix B: Key Decisions Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Plugin discovery mechanism | `importlib.metadata.entry_points` | Standard Python, works with pip/uv, no custom loader needed |
| Task queue | ARQ (not Celery) | Lighter weight, native async, sufficient for this scale |
| Plugin run() is synchronous | `asyncio.to_thread()` in worker | Plugins use threading internally (ThreadPoolExecutor). Forcing async would require rewriting all existing tools |
| Migrate only gauge-core into forge-gauge | `command` parameter routes scan/match | Gauge's internal plugin system is redundant — FORGE provides plugin discovery. Other gauge plugins (dhi-compete, ecosystems-coverage) become independent FORGE plugins. Gauge's update command superseded by `forge update` |
| `ToolParam` instead of raw argparse | Declarative params | Enables auto-generation of CLI args, API schemas, and UI forms from one source |
| Progress via callback, not return values | `ctx.progress(fraction, message)` | Works for both console output and Redis pub/sub without plugin awareness |
| Redis for both queue and pub/sub | Single Redis instance | Simplicity. ARQ already requires Redis. Pub/sub is built-in. No additional infrastructure |
| Python 3.12+ | `>=3.12` in all pyproject.toml | Modern typing features, performance improvements, Chainguard provides 3.12 base images |
| Distribution mechanism | `uv tool install` only | Single static binary (uv) bootstraps Python automatically. No global Python required. PyInstaller and Homebrew options rejected for simplicity |
| Update mechanism | Single `forge update` command | Wraps `uv tool upgrade` to update entire monorepo atomically. Replaces gauge's self-update mechanism |
| Production deployment | Kubernetes (docker-compose local only) | K8s provides HPA, health probes, and production-grade orchestration. docker-compose for local dev simplicity |
| Container base images | `cgr.dev/chainguard-private/*` | Minimal, secure Chainguard images for python, node, redis, nginx, and CLI tools (chainctl, crane, cosign) |
