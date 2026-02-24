# FORGE

**Field Operations Resources for GTM Engineering**

FORGE is a single-user CLI tool that consolidates field engineering tools into a single, consistent interface. Plugins live in external repositories and are installed on-demand.

## Available Tools

FORGE ships with `hello` as a bundled example plugin. Field tools like **gauge** and **provenance** live in external repositories.

```bash
# See all installable plugins from the registry
forge plugin list

# Install the container vulnerability scanner
forge plugin install gauge

# Install the image delivery verification tool
forge plugin install provenance
```

Once installed, tools are available as standard FORGE commands:

```bash
forge gauge --help
forge provenance --help
```

### Managing Plugins

```bash
forge plugin list                   # List available plugins
forge plugin install <name>         # Install a plugin
forge plugin update <name>          # Update a plugin
forge plugin update --all           # Update all plugins
forge plugin remove <name>          # Remove a plugin
```

---

## Installation

### Option 1: Global Tool (Recommended)

```bash
# Install uv (one-time setup)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install FORGE globally
uv tool install --editable .

# Install the tools you need
forge plugin install gauge
forge plugin install provenance

# Verify
forge --version
forge plugin list
```

### Option 2: Development Mode

```bash
git clone https://github.com/chainguard/forge
cd forge
uv sync
uv run forge
uv run forge plugin list
```

---

## Usage

### Gauge — Vulnerability Scanning

```bash
forge gauge scan \
  --input nginx:latest \
  --output vuln_summary,cost_analysis \
  --customer "Acme Corp"

forge gauge match \
  --input images.csv \
  --output-dir ./output
```

### Provenance — Delivery Verification

```bash
forge provenance \
  --customer-org my-customer-org \
  --output verification-report.csv
```

---

## Authentication

Tools that interact with Chainguard services require `chainctl`:

```bash
chainctl auth login
forge gauge scan --organization my-org
```

Plugins declare whether they need auth via `requires_auth`. Plugins with `requires_auth = False` (like `hello`) work without `chainctl` installed.

---

## Architecture

```
forge/
├── packages/
│   ├── forge-core/          # Plugin protocol + utilities (zero deps)
│   ├── forge-cli/           # CLI dispatcher + plugin manager
│   │   └── src/forge_cli/
│   │       └── data/
│   │           └── plugins-registry.yaml   ← bundled registry
│   └── forge-hello/         # Bundled example plugin (dev scaffold)
└── tests/
```

### Plugin Protocol

Every FORGE plugin implements the `ToolPlugin` protocol:

```python
class MyPlugin:
    name = "my-tool"
    description = "Does something useful"
    version = "1.0.0"
    requires_auth = True   # False = works without chainctl

    def get_params(self) -> list[ToolParam]:
        return [
            ToolParam(name="org", description="Target org", required=True),
            ToolParam(name="limit", description="Max items", type="int", default=0),
        ]

    def run(self, args: dict, ctx: ExecutionContext) -> ToolResult:
        ctx.progress(0.0, f"Starting scan of {args['org']}")
        # ... do work ...
        return ToolResult(status=ResultStatus.SUCCESS, summary="Done")
```

### Plugin Types

| Type | Description |
|------|-------------|
| `native` | External Python package implementing `ToolPlugin` directly |
| `wrapper` | Python package wrapping an external binary |
| `binary` | Any binary speaking the forge stdio protocol (no Python needed) |

### Binary Protocol Plugins

Any binary can be a FORGE plugin by implementing a simple JSON stdio protocol:

```
# Introspection:
binary --forge-introspect
stdout → {"name":"...", "description":"...", "version":"...", "requires_auth":false, "params":[...]}

# Execution:
binary --forge-run '{"param1":"val"}'
stderr → newline-delimited {"progress":0.5, "message":"Scanning..."}
stdout → {"status":"success", "summary":"...", "data":{}, "artifacts":{}}
```

---

## Development

### Running Tests

```bash
make test
uv run pytest tests/ -v
make test-cov
```

### Code Quality

```bash
make lint
make format
make typecheck
```

---

## Built-in Commands

```bash
forge version                       # Show FORGE and plugin versions
forge update                        # Update FORGE and all plugins
forge plugin list                   # List available plugins
forge plugin install <name>         # Install a plugin
forge plugin update <name>          # Update a plugin
forge plugin remove <name>          # Remove a plugin
forge --help                        # Show help
forge <tool> --help                 # Tool-specific help
```

---

## CI/CD Integration

```yaml
# GitHub Actions example
- name: Scan container images
  run: |
    uv tool install git+https://github.com/chainguard/forge
    forge plugin install gauge
    forge gauge scan \
      --input production-images.csv \
      --output vuln_summary,cost_analysis \
      --output-dir ./reports
```

---

## Contributing

See [plans/FORGE_PLUGIN_DEVELOPMENT_GUIDE.md](plans/FORGE_PLUGIN_DEVELOPMENT_GUIDE.md) for plugin development details.

---

## Tools

**Bundled**

| Tool | Status | Description |
|------|--------|-------------|
| **hello** | Ready | Example plugin (dev/test scaffold) |

**External Plugins** (install via `forge plugin install <name>`)

| Tool | Status | Description |
|------|--------|-------------|
| **gauge** | Ready | Container vulnerability scanning and image matching |
| **provenance** | Ready | Image delivery verification |

---

## License

Apache 2.0
