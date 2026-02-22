.PHONY: setup test test-fast test-slow lint typecheck run clean soak-test help

VENV = .venv
PYTHON = $(VENV)/bin/python3
PIP = $(VENV)/bin/pip3
RUFF = $(VENV)/bin/ruff
BASEDPYRIGHT = $(VENV)/bin/basedpyright

help: ## Show this help message
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

setup: ## Create virtual environment and install dependencies
	@test -d $(VENV) || echo "Creating virtual environment at $(VENV)..."
	@test -d $(VENV) || python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements-dev.txt
	@echo "Setup complete. Activate with: source $(VENV)/bin/activate"

test: ## Run unit/integration tests
	$(PYTHON) -m unittest discover -s tests -v

test-fast: ## Run fast test suite
	$(PYTHON) tests/run_suites.py fast

test-slow: ## Run slow test suite
	$(PYTHON) tests/run_suites.py slow

lint: ## Run ruff linter
	$(RUFF) check .

typecheck: ## Run basedpyright type checker
	$(BASEDPYRIGHT)

check: lint typecheck ## Run all checks (lint + typecheck)
	@echo "All checks passed!"

run: ## Run the main pipeline
	$(PYTHON) run_pipeline.py

clean: ## Remove Python cache files and build artifacts
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.py[cod]" -delete 2>/dev/null || true
	find . -type f -name "*.so" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .ruff_cache
	@echo "Clean complete"

clean-all: clean ## Remove virtual environment and all generated data
	rm -rf $(VENV)
	rm -f data/*.db data/*.jsonl
	@echo "Deep clean complete (including virtual environment)"

soak-test: ## Run pipeline repeatedly for stress testing
	@echo "Starting soak test (5 iterations)..."
	@for i in $$(seq 1 5); do \
		echo "=== Iteration $$i/5 ==="; \
		$(MAKE) test || { echo "Test failed at iteration $$i"; exit 1; }; \
		$(MAKE) run || { echo "Pipeline failed at iteration $$i"; exit 1; }; \
		sleep 2; \
	done; \
	echo "Soak test completed successfully!"
