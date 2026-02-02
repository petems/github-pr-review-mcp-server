.PHONY: compile-check lint format test coverage sync

# Use uv consistently to avoid host Python differences

compile-check:
	uv run python -m compileall -q -f .

lint:
	uv run ruff check .

format:
	uv run ruff format .

test:
	uv run pytest -q

coverage:
	uv run pytest --cov=. --cov-report=html --cov-report=term --cov-fail-under=90

sync:
	uv sync --dev

