# FORGE Container Images

This directory contains production-ready Dockerfiles using Chainguard base images with multi-stage builds.

## Image Overview

- **Dockerfile.api**: API server (FastAPI + uvicorn)
- **Dockerfile.worker**: ARQ worker with CLI tools (chainctl, crane, cosign)
- **Dockerfile.ui**: Static UI assets served by nginx

## Multi-Stage Build Pattern

All Dockerfiles follow the Chainguard best practice of multi-stage builds:

1. **Builder stage** (`-dev` variant): Has package managers (apk) and build tools
   - Installs dependencies with `uv`
   - Compiles TypeScript (UI only)
   - Creates optimized virtual environment

2. **Runtime stage** (minimal variant): Distroless, no package manager
   - Copies only the built artifacts
   - Minimal attack surface
   - Non-root user by default

## Building Locally

### Prerequisites

You must authenticate to `cgr.dev/chainguard-private`:

```bash
# Authenticate with Chainguard registry
docker login cgr.dev/chainguard-private
```

### Build Commands

```bash
# From repository root:
cd /Users/barretta/workspace/cgr/forge

# Build API image
docker build -f deploy/Dockerfile.api -t forge-api:latest .

# Build Worker image
docker build -f deploy/Dockerfile.worker -t forge-worker:latest .

# Build UI image
docker build -f deploy/Dockerfile.ui -t forge-ui:latest .
```

### Test with Production Images

```bash
# Use the production-like compose file
docker compose -f docker-compose.prod.yml up --build
```

## Image Sizes

Chainguard images are significantly smaller than traditional base images:

- **forge-api**: ~150MB (vs ~1GB with python:3.12)
- **forge-worker**: ~200MB (includes CLI tools)
- **forge-ui**: ~40MB (vs ~200MB with nginx:alpine)

## Security Features

### Non-Root User

All Chainguard images run as non-root by default:
- API/Worker: `nonroot` user (UID 65532)
- UI (nginx): `nginx` user

### Minimal Attack Surface

Runtime images contain:
- Only runtime dependencies (no build tools)
- No shell (distroless)
- No package manager
- Verified SBOMs and signatures

### Supply Chain Security

All base images:
- Built from source with full provenance
- Signed with Sigstore
- Include SBOM (Software Bill of Materials)
- Regular security updates (< 24h for CVEs)

## CI/CD Integration

See `.github/workflows/release.yml` for automated builds on tags.

Images are pushed to:
- `cgr.dev/chainguard-private/forge-api:${VERSION}`
- `cgr.dev/chainguard-private/forge-worker:${VERSION}`
- `cgr.dev/chainguard-private/forge-ui:${VERSION}`

## Troubleshooting

### Authentication Issues

If you see `failed to authorize` errors:

1. Check authentication: `docker logout cgr.dev && docker login cgr.dev/chainguard-private`
2. Verify access to private images with your Chainguard organization
3. For public testing, you can temporarily modify Dockerfiles to use `cgr.dev/chainguard/...` (public images)

### Build Failures

Common issues:

- **uv.lock missing**: Run `uv sync` in the root directory first
- **Source files not found**: Ensure all `packages/` subdirectories exist
- **Permission denied**: Check file permissions in source directories

### Runtime Issues

- **Health checks failing**: Ensure ports are correctly exposed (8080)
- **Import errors**: Check that all packages are in workspace members
- **Redis connection**: Verify `FORGE_REDIS_URL` environment variable
