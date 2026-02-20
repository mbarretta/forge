# FORGE

**Field Operations Resources for GTM Engineering**

FORGE consolidates multiple field engineering tools into a single, consistent interface available as a CLI, REST API, and web UI.

## Available Tools

FORGE ships with `hello` as a bundled example plugin. Field tools like **gauge** and **provenance** live in external repositories and are installed on-demand.

### Discovering Available Plugins

```bash
# See all installable plugins from the registry
forge plugin list
```

The authoritative list of registered plugins lives in [`plugins-registry.yaml`](plugins-registry.yaml).

### Getting Started with gauge and provenance

```bash
# Install the container vulnerability scanner
forge plugin install gauge

# Install the image delivery verification tool
forge plugin install provenance
```

Once installed, the tools are available as standard FORGE commands:

```bash
forge gauge --help
forge provenance --help
```

### Managing Plugins

```bash
# List available and installed plugins
forge plugin list

# Update a plugin
forge plugin update gauge

# Update all installed plugins
forge plugin update --all

# Remove a plugin
forge plugin remove gauge
```

### Building Your Own Plugin

Plugins implement the `ToolPlugin` protocol, live in a git repository, and register themselves via Python entry points. Add your plugin to `plugins-registry.yaml` to make it discoverable.

See the [Plugin Development Guide](plans/FORGE_PLUGIN_DEVELOPMENT_GUIDE.md) for full details.

---

## Quick Start

### Installation

#### Option 1: Global Installation (Recommended)
Install FORGE as a global command available from any directory:

```bash
# Install uv (one-time setup)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install FORGE globally
cd /path/to/forge
uv tool install --editable .

# Install the tools you need
forge plugin install gauge
forge plugin install provenance

# Verify installation
forge --version
forge plugin list
```

#### Option 2: Development Mode
Run FORGE in development mode with `uv run`:

```bash
# Clone repository
git clone https://github.com/chainguard/forge
cd forge

# Install dependencies
uv sync

# Run with uv prefix
uv run forge
uv run forge plugin list
```

### Prerequisites

FORGE requires external CLI tools depending on which plugins you use:

- **gauge**: `crane`, `grype`, `chainctl`, `cosign`
- **provenance**: `chainctl`, `crane`, `cosign`

Install Chainguard tools:
```bash
# chainctl - Chainguard CLI
# See: https://edu.chainguard.dev/chainguard/chainguard-enforce/chainguard-enforce-kubernetes/chainctl-docs/chainctl/

# crane - Container registry tool
go install github.com/google/go-containerregistry/cmd/crane@latest

# cosign - Container signing
go install github.com/sigstore/cosign/v2/cmd/cosign@latest

# grype - Vulnerability scanner (for gauge)
brew install grype
# Or: https://github.com/anchore/grype#installation
```

---

## Usage Examples

### Gauge - Vulnerability Scanning

#### Scan a Single Image
```bash
forge gauge scan \
  --input nginx:latest \
  --output vuln_summary,cost_analysis \
  --customer "Acme Corp"
```

#### Scan a Chainguard Organization
```bash
forge gauge scan \
  --organization my-chainguard-org \
  --output vuln_summary,cost_analysis \
  --with-all  # Enable CHPS, FIPS, KEVs
```

#### Scan from CSV File
```bash
# Create images.csv with: image_name,image_tag
forge gauge scan \
  --input images.csv \
  --output vuln_summary,cost_analysis \
  --max-workers 4 \
  --cache-dir .cache
```

#### Match Images to Chainguard Equivalents
```bash
forge gauge match \
  --input images.csv \
  --output-dir ./output \
  --min-confidence 0.7 \
  --interactive  # Enable manual matching for low-confidence results
```

#### Advanced Scanning Options
```bash
forge gauge scan \
  --input images.csv \
  --output vuln_summary,cost_analysis,pricing:html \
  --customer "Acme Corp" \
  --pricing-policy pricing-policy.yaml \
  --exec-summary exec-summary.md \
  --appendix appendix.md \
  --hours-per-vuln 3.0 \
  --hourly-rate 100.0 \
  --max-workers 4 \
  --with-chps \
  --with-fips \
  --with-kevs \
  --resume  # Resume from checkpoint
```

**Key Parameters:**
- `<command>` - Required subcommand: `scan` or `match`
- `--input` - Image reference, CSV file, or organization
- `--organization` - Chainguard org to scan
- `--output` - Output types: `vuln_summary` (HTML), `cost_analysis` (XLSX), `pricing`, `pricing:html`, `pricing:txt` (comma-separated)
- `--customer` - Customer name for reports
- `--max-workers` - Parallel workers (default: 1)
- `--with-chps` - Include CHPS security scoring
- `--with-fips` - Include FIPS compliance analysis
- `--with-kevs` - Include Known Exploited Vulnerabilities
- `--resume` - Resume from checkpoint file
- `--cache-dir` - Cache directory (default: `.cache`)

### Provenance - Delivery Verification

#### Verify Customer Organization (Default Mode)
```bash
forge provenance \
  --customer-org my-customer-org \
  --output verification-report.csv
```

This verifies:
1. Valid signature from Chainguard Enforce
2. Signature recorded in Rekor transparency log
3. Base digest label extraction

#### Full Verification Mode
```bash
forge provenance \
  --customer-org my-customer-org \
  --full \
  --output full-verification.csv
```

Full mode additionally verifies:
4. Base digest exists in chainguard-private
5. Base image has valid build signature from GitHub workflow
6. Build signature is in Rekor

#### Cryptographic Signature Verification
```bash
forge provenance \
  --customer-org my-customer-org \
  --verify-signatures \
  --limit 10
```

**Key Parameters:**
- `--customer-org` - Required: Customer organization to verify
- `--full` - Full verification mode (implies `--verify-signatures`)
- `--verify-signatures` - Enable cryptographic verification
- `--limit` - Limit number of images (0 = all)
- `--output` - CSV output file path

---

## Web API & UI

FORGE can run as a scalable web service with REST API and WebSocket support for real-time progress updates.

### Local Development

```bash
# Start all services (API, worker, Redis, UI)
docker compose up

# API: http://localhost:8080
# UI: http://localhost:3000
# API Docs: http://localhost:8080/docs
```

### Manual Startup

```bash
# Terminal 1: Start Redis
docker run -d -p 6379:6379 redis:7-alpine

# Terminal 2: Start API server
forge serve
# Or: uv run forge serve

# Terminal 3: Start worker
uv run arq forge_api.worker.WorkerSettings

# Terminal 4: Start UI (optional)
cd packages/forge-ui
npm run dev
```

### API Usage

```bash
# List available tools
curl http://localhost:8080/api/tools | jq

# Create a job
curl -X POST http://localhost:8080/api/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "gauge",
    "args": {
      "command": "scan",
      "input": "nginx:latest",
      "output": "vuln_summary,cost_analysis"
    }
  }' | jq

# Get job status
curl http://localhost:8080/api/jobs/{job_id} | jq

# Stream real-time progress via WebSocket
wscat -c ws://localhost:8080/api/jobs/{job_id}/ws
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for production deployment guides.

---

## Architecture

FORGE uses a plugin-based architecture that allows tools to work identically in CLI, API, and UI modes:

```
┌─────────────────────────────────────────────────────────────┐
│                         FORGE                               │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │   CLI        │  │   REST API   │  │   Web UI     │     │
│  │  (forge)     │  │  (FastAPI)   │  │  (React)     │     │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘     │
│         │                 │                  │             │
│         └─────────────────┼──────────────────┘             │
│                           │                                │
│                  ┌────────▼────────┐                       │
│                  │  Plugin Registry │                       │
│                  │  (Entry Points)  │                       │
│                  └────────┬─────────┘                       │
│                           │                                │
│         ┌─────────────────┴──────────────────┐             │
│         │                                    │             │
│    ┌────▼────┐      ┌─────────────────────▼──┐            │
│    │  hello  │      │  External Plugins       │            │
│    │(bundled)│      │  gauge, provenance, ... │            │
│    └─────────┘      │  (forge plugin install) │            │
│                     └─────────────────────────┘            │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Components

- **forge-core**: Plugin protocol (`ToolPlugin`), shared utilities
- **forge-cli**: CLI dispatcher with auto-generated argparse and plugin manager
- **forge-api**: FastAPI service with ARQ workers and Redis
- **forge-ui**: React SPA with real-time WebSocket updates
- **forge-hello**: Bundled example plugin (dev/test scaffold)
- **External plugins**: gauge, provenance, and others — installed via `forge plugin install`

### Plugin Protocol

Every FORGE plugin implements the `ToolPlugin` protocol:

```python
@dataclass
class ToolPlugin(Protocol):
    name: str              # CLI subcommand
    description: str       # Help text
    version: str           # Semver

    def get_params(self) -> list[ToolParam]:
        """Declare parameters (auto-generates CLI flags & API schema)"""

    def run(self, args: dict, ctx: ExecutionContext) -> ToolResult:
        """Execute the tool"""
```

This allows:
- **CLI**: Auto-generated argparse with `--help`
- **API**: Auto-generated Pydantic schemas and OpenAPI docs
- **UI**: Auto-generated forms with real-time progress

See [plans/FORGE_PLUGIN_DEVELOPMENT_GUIDE.md](plans/FORGE_PLUGIN_DEVELOPMENT_GUIDE.md) for plugin development.

---

## Development

### Running Tests

```bash
# Run all tests
make test

# Run specific test file
uv run pytest tests/unit/test_context.py -v

# Run with coverage
make test-cov
```

### Code Quality

```bash
# Lint
make lint

# Format
make format

# Type check
make typecheck

# All checks
make lint format typecheck test
```

### Project Structure

```
forge/
├── packages/
│   ├── forge-core/          # Plugin protocol and shared utilities
│   ├── forge-cli/           # CLI dispatcher + plugin manager
│   ├── forge-api/           # FastAPI server + ARQ workers
│   ├── forge-ui/            # React UI
│   └── forge-hello/         # Bundled example plugin (dev scaffold)
│                            # External plugins (gauge, provenance, ...)
│                            # are installed via `forge plugin install`
├── deploy/
│   ├── Dockerfile.api       # API server image
│   ├── Dockerfile.worker    # Worker image
│   ├── Dockerfile.ui        # UI image
│   └── helm/forge/          # Kubernetes Helm chart
├── tests/                   # Unit and integration tests
└── plans/                   # Implementation and development guides
```

---

## Deployment

### Docker Compose (Local Testing)

```bash
# Development images
docker compose up

# Production images (Chainguard base)
docker compose -f docker-compose.prod.yml up --build
```

### Kubernetes (Production)

```bash
# Install to production
helm install forge ./deploy/helm/forge \
  -f deploy/helm/forge/values.prod.yaml \
  --namespace forge-prod \
  --create-namespace
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for:
- Prerequisites and setup
- Scaling configuration
- Monitoring and health checks
- Security best practices
- Production checklist

---

## Built-in Commands

FORGE includes several built-in commands in addition to plugins:

```bash
# Show all tools and versions
forge version

# Update FORGE and built-in plugins
forge update

# Manage external plugins
forge plugin list
forge plugin install <name>
forge plugin update <name>
forge plugin remove <name>

# Start API server
forge serve

# Get help
forge --help
forge <tool> --help
forge plugin --help
```

---

## Authentication

Tools that interact with Chainguard services require authentication:

```bash
# Log in to Chainguard
chainctl auth login

# Verify authentication
chainctl auth status

# FORGE automatically uses your chainctl token
forge gauge scan --organization my-org
```

For API usage, tokens can be provided via:
- `ctx.auth_token` (pre-fetched by FORGE)
- Environment variables (tool-specific)
- Configuration files

---

## Output Files

### Gauge Outputs

**HTML Report** (`*.html`):
- Executive summary with risk assessment
- Vulnerability breakdown by severity
- Image comparison tables
- ROI calculations
- Custom appendices

**XLSX Workbook** (`*.xlsx`):
- Cost analysis worksheets
- Vulnerability remediation estimates
- Multi-year ROI projections
- Detailed CVE listings

**Pricing Quote** (HTML/TXT):
- Chainguard pricing estimates
- Support and services quotes
- Custom pricing based on policy file

### Provenance Outputs

**CSV Report** (`*.csv`):
- Image-by-image verification results
- Base digest tracking
- Rekor log indices
- Signature status
- Error details

---

## CI/CD Integration

FORGE can be used in CI/CD pipelines:

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

- name: Upload scan results
  uses: actions/upload-artifact@v3
  with:
    name: security-scan
    path: ./reports/
```

---

## Troubleshooting

### Common Issues

**"Missing required tools"**
```bash
# Install missing CLI tools
brew install grype crane cosign
go install github.com/google/go-containerregistry/cmd/crane@latest
```

**"Not authenticated"**
```bash
# Log in to Chainguard
chainctl auth login
```

**"Module not found"**
```bash
# Reinstall dependencies
uv sync --force
```

**"Permission denied"**
```bash
# Ensure Docker daemon is running
docker info

# Check file permissions
ls -la /var/run/docker.sock
```

### Getting Help

```bash
# Show available commands
forge --help

# Show tool-specific help
forge gauge --help
forge provenance --help

# Show version information
forge version

# Enable verbose logging
forge gauge scan --input nginx:latest -v
```

---

## Contributing

See [plans/FORGE_PLUGIN_DEVELOPMENT_GUIDE.md](plans/FORGE_PLUGIN_DEVELOPMENT_GUIDE.md) for:
- Plugin development guide
- Converting existing tools to FORGE plugins
- Testing and validation
- Contribution guidelines

---

## Status

✅ **Phase 1**: Core plugin system + CLI
✅ **Phase 2**: API server + Worker
✅ **Phase 3**: React UI with real-time progress
✅ **Phase 4**: Containerization + Kubernetes + CI/CD

**Production Ready!** FORGE is fully implemented and deployable.

### Tools

**Bundled**

| Tool | Status | Description |
|------|--------|-------------|
| **hello** | ✅ Ready | Example plugin (dev/test scaffold) |

**External Plugins** (install via `forge plugin install <name>`)

| Tool | Status | Description |
|------|--------|-------------|
| **gauge** | ✅ Ready | Container vulnerability scanning and image matching |
| **provenance** | ✅ Ready | Image delivery verification |

---

## License

Apache 2.0

---

## Resources

- **Deployment Guide**: [DEPLOYMENT.md](DEPLOYMENT.md)
- **Plugin Development Guide**: [plans/FORGE_PLUGIN_DEVELOPMENT_GUIDE.md](plans/FORGE_PLUGIN_DEVELOPMENT_GUIDE.md)
- **Implementation Plan**: [plans/FORGE_IMPLEMENTATION_PLAN.md](plans/FORGE_IMPLEMENTATION_PLAN.md)
- **API Documentation**: http://localhost:8080/docs (when running)
