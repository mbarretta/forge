# FORGE

Chainguard Field Engineering Toolkit — Unified platform for security assessment tools.

## Quick Start

### Installation

```bash
# Install uv (one-time)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and install FORGE
git clone https://github.com/chainguard/forge
cd forge
uv sync
```

### CLI Usage

```bash
# List available tools
uv run forge

# Run a tool
uv run forge hello --name "World" --count 3

# Show version info
uv run forge version
```

### API Server (Local Development)

```bash
# Start all services (API, worker, Redis)
docker compose up

# API will be available at http://localhost:8080
# - Health: http://localhost:8080/healthz
# - Tools: http://localhost:8080/api/tools
# - Docs: http://localhost:8080/docs
```

### API Server (Manual)

```bash
# Start Redis
docker run -d -p 6379:6379 redis:7-alpine

# Start API server
uv run forge serve

# In another terminal, start worker
uv run arq forge_api.worker.WorkerSettings
```

## Architecture

FORGE uses a plugin architecture where each tool implements the `ToolPlugin` protocol:

- **forge-core**: Plugin protocol and shared utilities
- **forge-cli**: Command-line interface with auto-generated argument parsing
- **forge-api**: FastAPI web service for HTTP/WebSocket access
- **forge-ui**: React SPA (coming soon)
- **Tool plugins**: Independent packages that implement specific tools

## Development

```bash
# Run linter
make lint

# Format code
make format

# Type check
make typecheck

# Run tests
make test
```

## Status

✅ **Phase 1 Complete**: Core plugin system + CLI
✅ **Phase 2 Complete**: API server + Worker
🚧 **Phase 3 In Progress**: UI
⏳ **Phase 4 Pending**: Containerization + Deployment

## License

Apache 2.0
