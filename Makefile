# Common tasks. `make help` lists them. Requires uv (https://docs.astral.sh/uv/).
# managed-by: vgi-starters (language section below is python-specific)

HAYBARN_VERSION ?= 2.0.0rc11
# vgi-lint is deliberately not pinned: the gate tracks the current quality bar.
VGI_LINT        := uvx --prerelease=allow --from 'vgi-lint-check>=2,<3' python test/lint_isolated.py lint
LINT_ARGS       ?=
WORKER          := $(CURDIR)/.venv/bin/vgi-trajectory-worker
TOOLS           := $(CURDIR)/.tools
HAYBARN_UNITTEST := $(TOOLS)/bin/haybarn-unittest
TRANSPORT       ?= stdio

.DEFAULT_GOAL := help
.PHONY: help build test test-unit test-sql test-sql-all lint lint-explain lint-ai fmt check run run-http debug tools template-diff clean

help: ## List the targets
	@awk 'BEGIN{FS=":.*## "} /^[a-zA-Z_-]+:.*## /{printf "  %-14s %s\n",$$1,$$2}' $(MAKEFILE_LIST)


build: ## Install the worker and dev tools into .venv
	uv sync --locked

tools: ## Install the pinned SQL test runner into .tools
	@test -x $(HAYBARN_UNITTEST) || { uv venv -q $(TOOLS) && uv pip install -q -p $(TOOLS) haybarn-unittest==$(HAYBARN_VERSION); }

fmt: ## Format the code
	uv run ruff format src tests test scripts/run_demo.py scripts/verify_package.py scripts/verify_container.py
	uv run ruff check --fix src tests test scripts/run_demo.py scripts/verify_package.py scripts/verify_container.py

lint: build ## Static checks: ruff, mypy, pydoclint
	uv run ruff format --check src tests test scripts/run_demo.py scripts/verify_package.py scripts/verify_container.py
	uv run ruff check src tests test scripts/run_demo.py scripts/verify_package.py scripts/verify_container.py
	uv run mypy
	uvx pydoclint --config=pyproject.toml src

test-unit: build ## Unit tests (pytest)
	uv run pytest -q

test-sql: build tools ## SQL tests through DuckDB: make test-sql TRANSPORT=stdio|launch|http
	WORKER=$(WORKER) HAYBARN_UNITTEST=$(HAYBARN_UNITTEST) TRANSPORT=$(TRANSPORT) ci/run-integration.sh

test-sql-all: ## SQL tests over every transport
	$(MAKE) test-sql TRANSPORT=stdio
	$(MAKE) test-sql TRANSPORT=launch
	$(MAKE) test-sql TRANSPORT=http

test: test-unit test-sql ## Unit + SQL tests

lint-explain: build ## Metadata quality report (vgi-lint, settings in vgi-lint.toml). LINT_ARGS="--format agent" for agents
	$(VGI_LINT) "$(WORKER)" $(LINT_ARGS)

lint-ai: ## Opt-in L3 check: an agent runs vgi-agent-tests.yaml and docs are reviewed (needs the claude CLI)
	@$(MAKE) --no-print-directory lint-explain LINT_ARGS="--ai $(LINT_ARGS)"

check: lint test-unit test-sql-all lint-explain verify-stock ## Everything CI runs. Done = this passes.

run: build ## Serve over stdio (what DuckDB launches)
	$(WORKER)

run-http: build ## Serve over HTTP on port 8000
	$(WORKER) --http --host 127.0.0.1 --port 8000

debug: build tools ## Run one query against the worker with debug logging on stderr
	@printf "LOAD vgi;\nATTACH 'trajectory' (TYPE vgi, LOCATION '$(WORKER) --debug');\nSELECT entity_id, episode_type, duration_s FROM trajectory.main.episodes((SELECT * FROM trajectory.main.sample_fixes));\n" \
	  | uvx --from haybarn-cli==$(HAYBARN_VERSION) haybarn -no-agent

template-diff: ## Show upstream template changes since this project was created
	uv run --no-project python scripts/vgi_template.py template-diff --stat

clean: ## Remove build outputs and tool caches
	rm -rf .venv .tools dist build .mypy_cache .ruff_cache .pytest_cache

.PHONY: demo verify-stock
demo: build ## Run the GIS SQL demonstrations in stock DuckDB
	uv run --with duckdb==2.0.0 python scripts/run_demo.py

verify-stock: build ## Assert the GIS contract in stock DuckDB
	uv run --with duckdb==2.0.0 python scripts/run_demo.py --verify --output validation/stock-duckdb.json

.PHONY: verify-package release-check
verify-package: build ## Build from sdist and verify a clean wheel installation
	uv run python scripts/verify_package.py

release-check: check verify-package ## All quality gates and isolated artifact verification

.PHONY: verify-container
verify-container: build ## Build a locked container and verify its HTTP SQL interface
	uv run --with duckdb==2.0.0 python scripts/verify_container.py
