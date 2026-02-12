# Configuration Files

This directory contains YAML configuration files for Gauge. Each file has a specific purpose and schema documented below.

## Files Overview

| File | Purpose | Auto-Updated |
|------|---------|--------------|
| `image_mappings.yaml` | Manual image-to-Chainguard mappings | Yes (by gauge) |
| `image_tiers.yaml` | Chainguard image tier classifications | Yes (by gauge) |
| `llm-settings.yaml` | LLM matching configuration | No |
| `upstream_mappings.yaml` | Private-to-public image mappings | No |

---

## image_mappings.yaml

Manual mappings from source images to Chainguard equivalents. Auto-populated by successful matches above the confidence threshold.

### Schema

```yaml
# Format: "source-image:tag": "cgr.dev/chainguard[-private]/image:tag"

# Simple mapping (tag optional)
nginx: cgr.dev/chainguard-private/nginx:latest

# Mapping with specific source tag
python:3.12: cgr.dev/chainguard-private/python:latest-dev

# Full registry path mapping
ghcr.io/org/image:v1.0: cgr.dev/chainguard-private/equivalent:latest
```

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `<source-image>` | string | Source image reference (with optional tag) |
| `<chainguard-image>` | string | Target Chainguard image reference |

### Notes

- Mappings have 100% confidence and take priority over all other matching tiers
- Auto-populated entries include a comment with match source and confidence
- Header comments show last update time and total mapping count

---

## image_tiers.yaml

Classification of Chainguard images by pricing tier.

### Schema

```yaml
# Format: image-name: tier

python: base
nginx: application
python-fips: fips
pytorch: ai
```

### Fields

| Field | Type | Values | Description |
|-------|------|--------|-------------|
| `<image-name>` | string | - | Chainguard image name (without registry) |
| `<tier>` | string | `base`, `application`, `fips`, `ai` | Pricing tier classification |

### Tier Definitions

| Tier | Description | Examples |
|------|-------------|----------|
| `base` | Minimal OS and language runtime images | `chainguard-base`, `python`, `go` |
| `application` | Full application images | `nginx`, `postgres`, `redis` |
| `fips` | FIPS-validated images | `python-fips`, `nginx-fips` |
| `ai` | AI/ML framework images | `pytorch`, `tensorflow` |

---

## llm-settings.yaml

Configuration for Claude-powered LLM image matching (Tier 4).

### Schema

```yaml
# Claude model selection
model: "claude-sonnet-4-5"

# Minimum confidence for accepting matches (0.0-1.0)
confidence_threshold: 0.7

# Enable/disable LLM matching
enabled: true

# Cache settings
cache:
  enabled: true
  directory: "~/.cache/gauge"

# Telemetry settings
telemetry:
  enabled: true
  file: "~/.cache/gauge/llm_telemetry.jsonl"

# API settings
api:
  # key: "sk-ant-..."  # Or use ANTHROPIC_API_KEY env var
  timeout: 30
  max_retries: 3
```

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `model` | string | `claude-sonnet-4-5` | Claude model for matching |
| `confidence_threshold` | float | `0.7` | Minimum confidence (0.0-1.0) |
| `enabled` | bool | `true` | Enable LLM matching |
| `cache.enabled` | bool | `true` | Cache LLM responses |
| `cache.directory` | string | `~/.cache/gauge` | Cache directory path |
| `telemetry.enabled` | bool | `true` | Log match attempts |
| `telemetry.file` | string | `~/.cache/gauge/llm_telemetry.jsonl` | Telemetry log path |
| `api.key` | string | - | Anthropic API key (or use env var) |
| `api.timeout` | int | `30` | Request timeout in seconds |
| `api.max_retries` | int | `3` | Max retries for failed requests |

### Model Options

| Model | Description |
|-------|-------------|
| `claude-sonnet-4-5` | Balanced speed/accuracy (recommended) |
| `claude-opus-4-5` | Highest accuracy, slower, more expensive |
| `claude-haiku-4-5` | Fastest, cheapest, lower accuracy |

---

## upstream_mappings.yaml

Manual mappings from private/internal images to their public upstream equivalents. Used by upstream discovery to find public versions before matching to Chainguard.

### Schema

```yaml
# Format: "private-image:tag": "public-image:tag"

# Map internal image to public equivalent
"company.io/python-app:v1.0": "python:3.12"

# Map private registry to DockerHub
"myregistry.io/nginx-custom:prod": "nginx:1.25"

# Map ECR image to public
"123456789.dkr.ecr.us-east-1.amazonaws.com/app:latest": "golang:1.21"
```

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `<private-image>` | string | Private/internal image reference |
| `<public-image>` | string | Public upstream equivalent |

### Usage

```bash
gauge match --input images.txt \
            --output matched.csv \
            --upstream-mappings-file config/upstream_mappings.yaml
```

### Notes

- Manual mappings have 100% confidence
- Takes precedence over automatic upstream discovery
- Use `--skip-public-repo-search` to disable automatic discovery entirely

---

## Environment Variables

Some settings can be overridden via environment variables:

| Variable | Overrides | Description |
|----------|-----------|-------------|
| `ANTHROPIC_API_KEY` | `llm-settings.yaml` → `api.key` | Anthropic API key |
| `GAUGE_CACHE_DIR` | Default cache directory | Cache storage location |
| `GAUGE_LLM_MODEL` | `llm-settings.yaml` → `model` | Claude model selection |

---

## CLI Overrides

Many settings can be overridden via CLI flags:

```bash
# Disable LLM matching
gauge match --disable-llm-matching ...

# Use specific mappings file
gauge match --mappings-file custom_mappings.yaml ...

# Skip upstream discovery
gauge match --skip-public-repo-search ...
```

See `gauge --help` for full CLI documentation.
