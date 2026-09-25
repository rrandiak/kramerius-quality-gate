# Task entry point for kramerius-quality-gate: `make` lists the targets.

SPEC   ?= specs/tiny.yaml
SEED   ?= 1
PAGES  ?= 1000
OUT    ?= corpora/$(notdir $(basename $(SPEC)))-s$(SEED)-p$(PAGES)

.DEFAULT_GOAL := help
MAKEFLAGS     += --no-print-directory

.PHONY: help \
        install \
        format format-check lint lint-fix typecheck check \
        test \
        gen \
        clean

# ─── Help ────────────────────────────────────────────────────────────────────

help: ## Show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ─── Setup ───────────────────────────────────────────────────────────────────

install: ## Create the venv and install all dependency groups
	uv sync --all-groups

# ─── Quality ─────────────────────────────────────────────────────────────────

format-check: ## Check formatting (no changes)
	uv run ruff format --check .

format: ## Format in place
	uv run ruff format .

lint: ## Lint (no changes)
	uv run ruff check .

lint-fix: ## Apply safe lint fixes
	uv run ruff check --fix .

typecheck: ## Type-check the qg package (mypy --strict)
	uv run mypy

check: format-check lint typecheck ## Run all checks (the CI gate)

# ─── Tests ───────────────────────────────────────────────────────────────────

test: ## Run unit tests
	uv run pytest

# ─── Corpus ──────────────────────────────────────────────────────────────────

gen: ## Generate a corpus (SPEC=specs/tiny.yaml SEED=1 PAGES=1000 OUT=corpora/...)
	uv run qg gen --spec $(SPEC) --seed $(SEED) --pages $(PAGES) --out $(OUT)

# ─── Cleanup ─────────────────────────────────────────────────────────────────

clean: ## Remove generated corpora and caches
	rm -rf corpora .pytest_cache .mypy_cache .ruff_cache
