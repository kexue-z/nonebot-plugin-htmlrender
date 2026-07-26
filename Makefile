.DEFAULT_GOAL := prepare

# Commands
UV ?= uv
UV_RUN ?= $(UV) run
PYTEST ?= $(UV_RUN) pytest
ZENSICAL ?= $(UV_RUN) zensical
TWINE ?= $(UV) run --no-project --with twine==6.2.0 twine
VERIFY_DISTRIBUTION ?= python3 scripts/verify_distribution.py
DOCKER_COMPOSE ?= docker compose

# Paths
PYTHON_PATHS := nonebot_plugin_htmlrender tests examples
RUFF_CHECK_PATHS := $(PYTHON_PATHS) pyproject.toml
TEST_PLAYWRIGHT_BROWSERS_PATH ?= $(CURDIR)/.artifacts/playwright-browsers
REMOTE_COMPOSE_FILE ?= $(CURDIR)/tests/infra/docker-compose.remote-test.yaml
DIST_DIR ?= $(CURDIR)/dist

# Options
DIST_SMOKE_PYTHON ?= 3.12
PYTEST_PARALLEL ?= -n auto --dist=loadfile
PLAYWRIGHT_VERSION ?= $(shell $(UV) tree --locked --package playwright --depth 0 2>/dev/null | awk '$$1 == "playwright" { sub(/^v/, "", $$2); print $$2 }')

##@ General

.PHONY: help
help: ## Show available make targets.
	@echo "Available make targets:"
	@awk 'BEGIN { FS = ":.*## " } \
		/^##@ / { printf "\n%s:\n", substr($$0, 5); next } \
		/^[A-Za-z0-9_.-]+:.*## / { printf "  %-22s %s\n", $$1, $$2 }' \
		$(MAKEFILE_LIST)

##@ Environment

.PHONY: ensure-uv
ensure-uv: ## Ensure uv is available in PATH.
	@$(UV) --version >/dev/null 2>&1 || { \
		echo "Error: '$(UV)' is not available."; \
		echo "Install uv from https://docs.astral.sh/uv/ and ensure it is in PATH,"; \
		echo "or override UV, e.g. 'make UV=/path/to/uv test'."; \
		exit 1; \
	}

.PHONY: sync sync-all sync-build
sync: sync-all ## Alias for sync-all.

sync-all: ensure-uv ## Sync all optional dependencies and dependency groups for development.
	@echo "==> Syncing all extras and dependency groups"
	@$(UV) sync --locked --all-extras --all-groups

sync-build: ensure-uv ## Sync dependencies for build/release usage without local sources.
	@echo "==> Syncing build dependencies"
	@$(UV) sync --locked --all-extras --all-groups --no-sources

.PHONY: install-prek
install-prek: ensure-uv ## Install prek and git hooks.
	@echo "==> Installing prek"
	@$(UV) tool install prek
	@echo "==> Installing git hooks with prek"
	@$(UV) tool run prek install
	@$(UV) tool run prek install --hook-type commit-msg

.PHONY: prepare
prepare: sync-all install-prek ## Prepare local dev environment.
	@echo "==> Environment prepared"

##@ Distribution

.PHONY: clean-dist verify-artifacts build-artifacts
clean-dist: ## Remove local distribution artifacts.
	@echo "==> Removing distribution artifacts from $(DIST_DIR)"
	rm -rf -- "$(DIST_DIR)"

verify-artifacts: ensure-uv ## Verify archive contents and isolated installs.
	@echo "==> Verifying built distributions"
	@$(VERIFY_DISTRIBUTION) "$(DIST_DIR)" \
		--expected-version "$$($(UV) version --short)" \
		--python "$(DIST_SMOKE_PYTHON)" \
		--uv "$(UV)"

build-artifacts: sync-build clean-dist ## Build manual release artifacts (wheel + sdist).
	@echo "==> Building wheel and sdist into $(DIST_DIR)"
	@$(UV) build --no-sources --wheel --sdist --out-dir "$(DIST_DIR)"
	@echo "==> Validating package metadata"
	@$(TWINE) check "$(DIST_DIR)"/*
	@$(MAKE) verify-artifacts DIST_DIR="$(DIST_DIR)"
	@echo "==> Artifacts generated:"
	@ls -la "$(DIST_DIR)"
	@echo "==> Artifact checksums:"
	@sh -c 'if command -v sha256sum >/dev/null 2>&1; then sha256sum "$(DIST_DIR)"/*; else shasum -a 256 "$(DIST_DIR)"/*; fi'

##@ Testing

.PHONY: test test-ci check-browser-install test-local install-browser remote-smoke remote-smoke-build remote-smoke-down
test: test-ci ## Run CI profile tests in parallel.

test-ci: ensure-uv ## Run CI profile tests in parallel.
	@echo "==> Running CI test profile"
	HTMLRENDER_TEST_PROFILE=ci $(PYTEST) $(PYTEST_PARALLEL) tests

check-browser-install: ## Check local Playwright browser installation.
	@echo "==> Checking project-local Playwright browser installation"
	@if [ ! -d "$(TEST_PLAYWRIGHT_BROWSERS_PATH)" ] || ! find "$(TEST_PLAYWRIGHT_BROWSERS_PATH)" -maxdepth 1 -type d \( -name "chromium-*" -o -name "chromium_headless_shell-*" \) | grep -q .; then \
		echo "Project-local Playwright browser not found under $(TEST_PLAYWRIGHT_BROWSERS_PATH)."; \
		echo "Run \`make install-browser\` first."; \
		exit 1; \
	fi

test-local: ensure-uv check-browser-install ## Run local profile tests (serial).
	@echo "==> Running local browser test profile"
	HTMLRENDER_TEST_PROFILE=local PLAYWRIGHT_BROWSERS_PATH=$(TEST_PLAYWRIGHT_BROWSERS_PATH) $(PYTEST) tests

install-browser: ensure-uv ## Install Playwright Chromium with system deps.
	@echo "==> Installing Playwright Chromium into $(TEST_PLAYWRIGHT_BROWSERS_PATH)"
	mkdir -p "$(TEST_PLAYWRIGHT_BROWSERS_PATH)"
	PLAYWRIGHT_BROWSERS_PATH="$(TEST_PLAYWRIGHT_BROWSERS_PATH)" $(UV_RUN) playwright install --with-deps chromium

remote-smoke: ## Run remote browser smoke with cached image and dependencies.
	@echo "==> Running remote browser smoke"
	$(DOCKER_COMPOSE) -f "$(REMOTE_COMPOSE_FILE)" up --abort-on-container-exit --exit-code-from render

remote-smoke-build: ## Rebuild image, then run remote browser smoke.
	@echo "==> Rebuilding and running remote browser smoke"
	PLAYWRIGHT_VERSION="$(PLAYWRIGHT_VERSION)" $(DOCKER_COMPOSE) -f "$(REMOTE_COMPOSE_FILE)" up --build --abort-on-container-exit --exit-code-from render

remote-smoke-down: ## Stop remote browser smoke services and remove named volumes.
	@echo "==> Tearing down remote browser smoke services"
	$(DOCKER_COMPOSE) -f "$(REMOTE_COMPOSE_FILE)" down -v

##@ Code quality

.PHONY: ruff-format ruff-format-check ruff-check lint basedpyright type-completeness ty typecheck check
ruff-format: ensure-uv ## Format Python files with Ruff.
	@echo "==> Formatting Python files with Ruff"
	$(UV_RUN) ruff format $(PYTHON_PATHS)

ruff-format-check: ensure-uv ## Check Python formatting without modifying files.
	@echo "==> Checking Python formatting with Ruff"
	$(UV_RUN) ruff format --check $(PYTHON_PATHS)

ruff-check: ensure-uv ## Run Ruff lint checks.
	@echo "==> Running Ruff checks"
	$(UV_RUN) ruff check $(RUFF_CHECK_PATHS)

lint: ruff-check ## Alias for ruff-check.

basedpyright: ensure-uv ## Run basedpyright type checking.
	@echo "==> Running basedpyright"
	$(UV_RUN) basedpyright . --verbose

type-completeness: ensure-uv ## Verify the installed package's public type surface.
	@echo "==> Verifying package type completeness"
	$(UV_RUN) basedpyright --verifytypes nonebot_plugin_htmlrender --ignoreexternal

ty: ensure-uv ## Run ty type checking.
	@echo "==> Running ty"
	$(UV_RUN) ty check $(PYTHON_PATHS)

typecheck: basedpyright type-completeness ## Run source and public API type checks.

check: ruff-format-check ruff-check typecheck ty test ## Run format, lint, type checks, and tests without modifying files.

##@ Documentation

.PHONY: docs-serve docs-build docs-deploy docs-list
docs-serve: ensure-uv ## Serve docs site locally.
	@echo "==> Serving docs locally"
	$(ZENSICAL) serve

docs-build: ensure-uv ## Build docs site.
	@echo "==> Building docs site"
	$(ZENSICAL) build --strict

docs-deploy: ensure-uv ## Deploy versioned docs locally (e.g. make docs-deploy VERSION=0.7.0).
	@echo "==> Deploying docs version $(VERSION)"
	$(UV_RUN) mike deploy --update-aliases $(VERSION) latest

docs-list: ensure-uv ## List all deployed doc versions.
	$(UV_RUN) mike list

##@ Compatibility

.PHONY: download-deps prepare-build
download-deps: sync-all ## Deprecated alias for sync-all.

prepare-build: sync-build ## Deprecated alias for sync-build.
