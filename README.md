# FORGE

**Field Operations Resources for GTM Engineering**

FORGE consolidates multiple field engineering tools into a single, consistent interface available as a CLI, REST API, and web UI.

## Available Tools

### 🔍 gauge - Container Vulnerability Assessment
Scan container images for vulnerabilities and generate comprehensive security assessment reports.

**Commands:**
- `scan` - Vulnerability scanning with HTML/XLSX/YAML reports
- `match` - Match alternative images to Chainguard equivalents
- `update` - Check for gauge updates

**Key Features:**
- Multi-format reports (HTML executive summaries, XLSX cost analysis)
- AI-powered image matching with Claude
- CHPS scoring, FIPS analysis, KEV data integration
- Parallel scanning with caching and checkpointing
- Integration with Grype, Chainguard API, GitHub

### 🔐 provenance - Image Delivery Verification
Verify that customer organization images were authentically delivered by Chainguard.

**Key Features:**
- Signature verification against Chainguard Enforce
- Rekor transparency log validation
- Base digest provenance tracking
- Customer-only or full verification modes
- CSV report generation

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

# Now use from anywhere
forge --version
forge gauge --help
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
uv run forge gauge --command scan --help
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
forge gauge --command scan \
  --input nginx:latest \
  --output html,xlsx \
  --customer "Acme Corp"
```

#### Scan a Chainguard Organization
```bash
forge gauge --command scan \
  --organization my-chainguard-org \
  --output html,xlsx,yaml \
  --with-all  # Enable CHPS, FIPS, KEVs
```

#### Scan from CSV File
```bash
# Create images.csv with: image_name,image_tag
forge gauge --command scan \
  --input images.csv \
  --output html,xlsx \
  --max-workers 4 \
  --cache-dir .cache
```

#### Match Images to Chainguard Equivalents
```bash
forge gauge --command match \
  --input images.csv \
  --output matched-log.yaml \
  --min-confidence 0.7 \
  --interactive  # Enable manual matching for low-confidence results
```

#### Advanced Scanning Options
```bash
forge gauge --command scan \
  --input images.csv \
  --output html,xlsx,yaml \
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
- `--command` - Required: `scan`, `match`, or `update`
- `--input` - Image reference, CSV file, or organization
- `--organization` - Chainguard org to scan
- `--output` - Output formats: `html`, `xlsx`, `yaml` (comma-separated)
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
      "output": "html"
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
│         ┌─────────────────┼─────────────────┐             │
│         │                 │                 │             │
│    ┌────▼────┐      ┌────▼────┐      ┌────▼────┐        │
│    │  gauge  │      │provenance│     │  hello  │        │
│    │ plugin  │      │  plugin  │     │ plugin  │        │
│    └─────────┘      └─────────┘      └─────────┘        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Components

- **forge-core**: Plugin protocol (`ToolPlugin`), shared utilities
- **forge-cli**: CLI dispatcher with auto-generated argparse
- **forge-api**: FastAPI service with ARQ workers and Redis
- **forge-ui**: React SPA with real-time WebSocket updates
- **forge-gauge**: Container vulnerability scanning plugin
- **forge-provenance**: Image delivery verification plugin

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

See [plans/FORGE_PLUGIN_MIGRATION_GUIDE.md](plans/FORGE_PLUGIN_MIGRATION_GUIDE.md) for plugin development.

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
│   ├── forge-cli/           # CLI dispatcher
│   ├── forge-api/           # FastAPI server + ARQ workers
│   ├── forge-ui/            # React UI
│   ├── forge-gauge/         # Gauge plugin (vulnerability scanning)
│   └── forge-provenance/    # Provenance plugin (delivery verification)
├── deploy/
│   ├── Dockerfile.api       # API server image
│   ├── Dockerfile.worker    # Worker image
│   ├── Dockerfile.ui        # UI image
│   └── helm/forge/          # Kubernetes Helm chart
├── tests/                   # Unit and integration tests
└── plans/                   # Implementation guides
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

# Update FORGE and plugins
forge update

# Start API server
forge serve

# Get help
forge --help
forge <tool> --help
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
forge gauge --command scan --organization my-org
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

**YAML Export** (`*.yaml`):
- Structured data for automation
- Machine-readable results
- Integration with CI/CD

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
    forge gauge --command scan \
      --input production-images.csv \
      --output yaml \
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
forge gauge --command scan --input nginx:latest -v
```

---

## Contributing

See [plans/FORGE_PLUGIN_MIGRATION_GUIDE.md](plans/FORGE_PLUGIN_MIGRATION_GUIDE.md) for:
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

| Tool | Status | Description |
|------|--------|-------------|
| **gauge** | ✅ Ready | Container vulnerability scanning and image matching |
| **provenance** | ✅ Ready | Image delivery verification |
| **hello** | ✅ Test plugin | Example plugin for testing |

---

## License

Apache 2.0

---

## Resources

- **Deployment Guide**: [DEPLOYMENT.md](DEPLOYMENT.md)
- **Plugin Migration Guide**: [plans/FORGE_PLUGIN_MIGRATION_GUIDE.md](plans/FORGE_PLUGIN_MIGRATION_GUIDE.md)
- **Implementation Plan**: [plans/FORGE_IMPLEMENTATION_PLAN.md](plans/FORGE_IMPLEMENTATION_PLAN.md)
- **API Documentation**: http://localhost:8080/docs (when running)
