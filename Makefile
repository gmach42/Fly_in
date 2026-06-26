PYTHON := uv run python
FLAKE8 := uv run flake8
MYPY := uv run mypy
PYTEST := uv run pytest
LINT_PATHS := src tests

install:
	uv sync

run:
	$(PYTHON) -m src

render:
	$(PYTHON) src/render.py

debug:
	$(PYTHON) -m pdb src/__main__.py

test:
	$(PYTEST)

test-verbose:
	$(PYTEST) -v

clean:
	find . -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -prune -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -prune -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete

lint:
	$(FLAKE8) $(LINT_PATHS)
	$(MYPY) $(LINT_PATHS) --warn-return-any --warn-unused-ignores --ignore-missing-imports --disallow-untyped-defs --check-untyped-defs

lint-strict:
	$(FLAKE8) $(LINT_PATHS)
	$(MYPY) $(LINT_PATHS) --strict

.PHONY: install run render debug test test-verbose clean lint lint-strict help
