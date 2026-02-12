# forge-coverage

Python and JavaScript package coverage checking for Chainguard libraries.

## Overview

The `coverage` plugin checks package availability in Chainguard's Python and JavaScript registries. It helps Sales Engineers and technical teams assess coverage for customer onboarding and evaluate build requirements.

## Features

### Python Coverage
- Check Python packages from `requirements.txt` against Chainguard's Python index
- Multiple modes:
  - **Index mode** (default): Query Chainguard index via HTTP
  - **API mode**: Request builds via Rebuilder API
  - **Database mode**: Query internal ecosystems database
- Filters for architecture (amd64/arm64), Python version (3.9-3.14), manylinux variants (2_28, 2_39)

### JavaScript Coverage
- Check JavaScript packages from lock files against Chainguard's JavaScript registry
- Supports: package-lock.json, yarn.lock, pnpm-lock.yaml, bun.lockb
- Uses flatcover tool (automatically downloaded and cached)

## Usage

### Python Coverage - Index Mode

Check a requirements.txt file against the default Chainguard Python index:

```bash
forge coverage --requirements-file requirements.txt
```

With architecture and Python version filters:

```bash
forge coverage --requirements-file requirements.txt --arch amd64 --python-version 3.11
```

With manylinux variant:

```bash
forge coverage --requirements-file requirements.txt --manylinux-variant 2_28
```

### Python Coverage - API Mode

Create build requests for missing packages:

```bash
forge coverage --mode api --requirements-file requirements.txt --issue 12345
```

Check status of existing request group:

```bash
forge coverage --mode api --issue 12345
```

Refresh failed requests:

```bash
forge coverage --mode api --issue 12345 --refresh
```

### JavaScript Coverage

Check a package-lock.json file:

```bash
forge coverage --mode js --requirements-file package-lock.json
```

Check multiple lock files:

```bash
forge coverage --mode js --requirements-file package-lock.json yarn.lock
```

## Parameters

### Main Arguments
- `--requirements-file`: Path to requirements.txt (Python) or lock file (JavaScript). Can specify multiple files.
- `--mode`: Mode for checking coverage (default: `index`)
  - `index`: Query Python index via HTTP
  - `api`: Interact with Rebuilder API
  - `js`: Check JavaScript packages
  - `db`: Query database (requires access)
  - `sql`: Generate SQL for offline analysis
  - `csv`: Parse CSV from SQL mode
- `--index-url`: Index URL (default: `https://libraries.cgr.dev/python/simple`)

### Python Filters
- `--arch`: Architecture (amd64, arm64)
- `--python-version`: Python version (3.9, 3.10, 3.11, 3.12, 3.13, 3.14)
- `--manylinux-variant`: Manylinux variant (2_28, 2_39)
- `--workers`: Number of parallel workers for index mode (default: 10)

### API Mode Arguments
- `--issue`: GitHub issue number (required for API mode)
- `--token`: OIDC token (defaults to `chainctl auth token`)
- `--api-url`: Rebuilder API URL (default: `https://rebuilder-api-python.prod-eco.dev`)
- `--organization-id`: Organization ID (auto-detected if not specified)
- `--environment`: Environment for chainctl (prod, staging)
- `--refresh`: Refresh a request group
- `--force`: Force reprocess all requests (use with --refresh)

### Database Mode Arguments
- `--database-url`: Database connection string
- `--generation`: Specific generation to check
- `--csv`: Path to CSV input file (for csv mode)

### General
- `--verbose`: Enable verbose logging

## Authentication

### Python Index Mode
Run the netrc.sh script to set up credentials:

```bash
./netrc.sh
```

This creates/updates `~/.netrc` with credentials for `libraries.cgr.dev`.

### API Mode
Uses OIDC tokens obtained via `chainctl auth token`. Requires the `libraries.rebuilder.requests.create` role.

### JavaScript Mode
Automatically authenticates using `chainctl auth pull-token`.

## Examples

### Sales Engineer Workflow

1. Check Python coverage with specific platform requirements:
```bash
forge coverage --requirements-file requirements.txt --python-version 3.11 --arch amd64
```

2. Review output to identify missing packages

3. Request builds for missing packages:
```bash
forge coverage --mode api --requirements-file requirements.txt --issue 12345 --python-version 3.11 --arch amd64
```

4. Check build status:
```bash
forge coverage --mode api --issue 12345
```

### JavaScript Coverage Check

```bash
forge coverage --mode js --requirements-file package-lock.json --verbose
```

## Output Interpretation

### Python Index Mode
```
Total requirements: 100
Package/version found: 85 (85%)
    package-a>=1.0.0
    package-b==2.3.1
    ...
Package/version not found: 10 (10%)
    package-c>=3.0.0
    ...
Package/version not found on PyPI: 5 (5%)
    internal-package
    ...
```

### JavaScript Mode
```
Total packages: 464
Packages found: 196 (42%)
    ansi-styles@4.3.0
    acorn-jsx@5.3.2
    ...
Packages not found: 268 (57%)
    @babel/core@7.28.0
    ...
```

## Requirements File Format

### Python (requirements.txt)
```txt
# Comments are supported
requests>=2.28.0
django==4.2.0
numpy>=1.24.0,<2.0.0

# Version specifiers
flask~=2.3.0
pytest>=7.0.0
```

### JavaScript
Supports standard lock file formats:
- npm: package-lock.json (lockfileVersion 2 and 3)
- Yarn: yarn.lock
- pnpm: pnpm-lock.yaml
- Bun: bun.lockb

## Notes

- **Token validity**: Tokens obtained from chainctl are temporary. Re-run authentication if you encounter auth errors.
- **JavaScript mode**: Requires chainctl installed and configured.
- **API mode**: Consult product/engineering before requesting large numbers of builds.
- **Database mode**: Requires database access (limited to Chainguard developers).

## See Also

- [COVERAGE.md](https://github.com/chainguard-dev/ecosystems-insights/blob/main/pypi/COVERAGE.md) - Original documentation
- [Ecosystems Insights Repository](https://github.com/chainguard-dev/ecosystems-insights)
