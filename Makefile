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
