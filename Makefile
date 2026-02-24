.PHONY: install lint format typecheck test clean

install:
	uv sync

lint:
	uv run ruff check packages/

format:
	uv run ruff format packages/

typecheck:
	uv run mypy packages/forge-core/src packages/forge-cli/src

test:
	uv run pytest tests/ -v

test-cov:
	uv run pytest tests/ -v --cov=packages --cov-report=xml

clean:
	rm -rf .venv __pycache__ .mypy_cache .pytest_cache .ruff_cache
	find packages -type d -name __pycache__ -exec rm -rf {} +
