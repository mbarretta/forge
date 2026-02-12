# forge-coverage Test Suite

Comprehensive test suite for the coverage plugin covering both Python and JavaScript package coverage checking.

## Test Structure

### Unit Tests (42 tests)
Located in `tests/` directory. Run with:
```bash
pytest tests/ -v -m "not integration"
```

### Integration Tests (4 tests)
Tests that require network access and authentication. Run with:
```bash
pytest tests/ -v -m "integration"
```

## Test Files

### `test_plugin.py` (17 tests)
Tests for plugin wrapper functionality:

**TestPluginBasics** (5 tests)
- Plugin creation and metadata
- Parameter declarations
- Mode choices validation

**TestParameterValidation** (4 tests)
- CSV mode requires --csv
- API mode requires --issue
- API mode --force requires --refresh
- Non-API modes require requirements-file

**TestArgsConversion** (6 tests)
- Basic args dict → Namespace conversion
- Filter argument conversion
- API mode argument conversion
- Default value handling
- CSV path conversion

**TestPluginIntegration** (2 tests)
- Protocol conformance
- ToolResult return type

### `test_coverage_python.py` (15 tests)
Tests for Python package coverage checking:

**TestPythonCoverageBasics** (3 tests)
- Loading requirements from file
- Ignoring comments and empty lines
- Loading from multiple files

**TestPythonCoverageIndexMode** (5 tests)
- HTML parsing for package links
- Wheel filename parsing
- PackageCheckResult structure

**TestPythonCoverageWithMocks** (2 tests)
- check_package function signature
- Result type validation

**TestPythonCoverageFilters** (4 tests)
- Architecture filtering (amd64, arm64)
- Python version filtering
- Manylinux variant filtering

**TestPythonCoverageHelpers** (1 test)
- PyPI package existence checking

**TestPythonCoverageIntegration** (2 integration tests)
- Real API calls (requires auth)
- Common library coverage validation

### `test_coverage_javascript.py` (10 tests)
Tests for JavaScript package coverage checking:

**TestJavaScriptCoverageBasics** (3 tests)
- Loading package-lock.json
- Validating common packages in fixture
- JSPackageResult structure

**TestFlatcoverIntegration** (3 tests)
- Cache directory creation
- File checksum computation
- Local flatcover override detection

**TestJavaScriptCoverageWithMocks** (2 tests)
- Credential retrieval mocking
- Flatcover CSV output parsing

**TestJavaScriptCoverageAggregation** (1 test)
- OR logic for multi-file aggregation

**TestJavaScriptModeEndToEnd** (1 test)
- Complete JavaScript coverage check flow

**TestJavaScriptCoverageIntegration** (2 integration tests)
- Real flatcover execution (requires auth)
- Common library documentation

## Test Fixtures

### `fixtures/minimal_python.txt`
Minimal Python requirements for quick testing:
- requests>=2.31.0
- pyyaml>=6.0
- packaging>=23.0

### `fixtures/common_python.txt`
Common Python libraries for comprehensive testing:
- Web frameworks: requests, flask, django, fastapi
- Data science: numpy, pandas, scikit-learn, matplotlib
- Testing: pytest, pytest-cov
- Utilities: pyyaml, python-dateutil, packaging

### `fixtures/package-lock.json`
Sample JavaScript lock file with common libraries:
- express 4.18.2 (web framework)
- react 18.2.0 (UI library)
- lodash 4.17.21 (utilities)
- axios 1.6.0 (HTTP client)

## Running Tests

### All Unit Tests
```bash
pytest tests/ -v -m "not integration"
```

### All Tests (including integration)
```bash
pytest tests/ -v
```

### Specific Test File
```bash
pytest tests/test_plugin.py -v
pytest tests/test_coverage_python.py -v
pytest tests/test_coverage_javascript.py -v
```

### Specific Test Class
```bash
pytest tests/test_plugin.py::TestPluginBasics -v
```

### Specific Test
```bash
pytest tests/test_plugin.py::TestPluginBasics::test_create_plugin -v
```

### With Coverage Report
```bash
pytest tests/ --cov=forge_coverage --cov-report=html
open htmlcov/index.html
```

## Test Coverage

**Current Status**: 42/42 unit tests passing (100%)

Coverage includes:
- ✅ Plugin loading and registration
- ✅ Parameter validation
- ✅ Args conversion
- ✅ Python requirements parsing
- ✅ JavaScript lock file parsing
- ✅ Architecture/version filtering
- ✅ Mock-based unit tests
- ✅ Integration test stubs

## Integration Tests

Integration tests require:
1. **Authentication**: chainctl configured and authenticated
2. **Network Access**: Connection to Chainguard registries
3. **Permissions**: Access to libraries.cgr.dev

To skip integration tests (default):
```bash
pytest tests/ -m "not integration"
```

To run only integration tests:
```bash
pytest tests/ -m "integration"
```

## Common Test Patterns

### Testing with Mocks
```python
from unittest.mock import Mock, patch

def test_with_mock():
    with patch("forge_coverage.check_coverage.requests.Session") as mock:
        mock.return_value.get.return_value = Mock(status_code=200)
        # Test code here
```

### Testing Parameter Validation
```python
def test_validation():
    plugin = create_plugin()
    ctx = ExecutionContext()
    result = plugin.run({"mode": "csv"}, ctx)
    assert result.status == ResultStatus.FAILURE
```

### Testing Args Conversion
```python
def test_conversion():
    plugin = create_plugin()
    args = {"requirements-file": "/tmp/test.txt"}
    ns = plugin._args_to_namespace(args)
    assert ns.requirements_file == [Path("/tmp/test.txt")]
```

## Continuous Integration

Tests are designed to run in CI environments:
- Fast execution (< 1 second for unit tests)
- No external dependencies required for unit tests
- Integration tests can be skipped
- Clear pass/fail criteria

## Future Enhancements

Potential additions:
- [ ] More comprehensive mocking for HTTP responses
- [ ] Performance tests for large requirements files
- [ ] Error handling edge cases
- [ ] Cache directory cleanup tests
- [ ] Flatcover download/verification tests
