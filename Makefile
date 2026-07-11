UV ?= uv
PYTEST ?= $(UV) run pytest
ZENSICAL ?= $(UV) run zensical
TWINE ?= $(UV) run --no-project --with twine==6.2.0 twine
PYTEST_PARALLEL ?= -n auto --dist=loadfile
TEST_PLAYWRIGHT_BROWSERS_PATH ?= $(CURDIR)/.artifacts/playwright-browsers
DIST_DIR ?= $(CURDIR)/dist

.DEFAULT_GOAL := prepare

.PHONY: help
help: ## Show available make targets.
	@echo "Available make targets:"
	@awk 'BEGIN { FS = ":.*## " } /^[A-Za-z0-9_.-]+:.*## / { printf "  %-22s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

.PHONY: ensure-uv
ensure-uv: ## Ensure uv is available in PATH.
	@$(UV) --version >/dev/null 2>&1 || { \
		echo "Error: '$(UV)' is not available."; \
		echo "Install uv from https://docs.astral.sh/uv/ and ensure it is in PATH,"; \
		echo "or override UV, e.g. 'make UV=/path/to/uv test'."; \
		exit 1; \
	}

.PHONY: sync sync-all sync-build download-deps prepare-build
sync: sync-all ## Alias for sync-all.

sync-all: ensure-uv ## Sync all optional dependencies and dependency groups for development.
	@echo "==> Syncing all extras and dependency groups"
	@$(UV) sync --locked --all-extras --all-groups

sync-build: ensure-uv ## Sync dependencies for build/release usage without local sources.
	@echo "==> Syncing build dependencies"
	@$(UV) sync --locked --all-extras --all-groups --no-sources

download-deps: sync-all ## Deprecated alias for sync-all.

prepare-build: sync-build ## Deprecated alias for sync-build.

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

.PHONY: clean-dist build-artifacts
clean-dist: ## Remove local distribution artifacts.
	@echo "==> Removing distribution artifacts from $(DIST_DIR)"
	rm -rf $(DIST_DIR)

build-artifacts: prepare-build clean-dist ## Build manual release artifacts (wheel + sdist).
	@echo "==> Building wheel and sdist into $(DIST_DIR)"
	@$(UV) build --no-sources --wheel --sdist --out-dir $(DIST_DIR)
	@echo "==> Validating package metadata"
	@$(TWINE) check $(DIST_DIR)/*
	@echo "==> Artifacts generated:"
	@ls -la $(DIST_DIR)
	@echo "==> Artifact checksums:"
	@sh -c 'if command -v sha256sum >/dev/null 2>&1; then sha256sum $(DIST_DIR)/*; else shasum -a 256 $(DIST_DIR)/*; fi'

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
	mkdir -p $(TEST_PLAYWRIGHT_BROWSERS_PATH)
	PLAYWRIGHT_BROWSERS_PATH=$(TEST_PLAYWRIGHT_BROWSERS_PATH) $(UV) run playwright install --with-deps chromium

remote-smoke: ## Run remote browser smoke with cached image and dependencies.
	@echo "==> Running remote browser smoke"
	docker compose -f tests/infra/docker-compose.remote-test.yaml up --abort-on-container-exit --exit-code-from render

remote-smoke-build: ## Rebuild image, then run remote browser smoke.
	@echo "==> Rebuilding and running remote browser smoke"
	docker compose -f tests/infra/docker-compose.remote-test.yaml up --build --abort-on-container-exit --exit-code-from render

remote-smoke-down: ## Stop remote browser smoke services and remove named volumes.
	@echo "==> Tearing down remote browser smoke services"
	docker compose -f tests/infra/docker-compose.remote-test.yaml down -v

.PHONY: ruff-format ruff-format-check ruff-check lint basedpyright ty typecheck check
ruff-format: ensure-uv ## Format Python files with Ruff.
	@echo "==> Formatting Python files with Ruff"
	$(UV) run ruff format nonebot_plugin_htmlrender tests

ruff-format-check: ensure-uv ## Check Python formatting without modifying files.
	@echo "==> Checking Python formatting with Ruff"
	$(UV) run ruff format --check nonebot_plugin_htmlrender tests

ruff-check: ensure-uv ## Run Ruff lint checks.
	@echo "==> Running Ruff checks"
	$(UV) run ruff check nonebot_plugin_htmlrender tests pyproject.toml

lint: ruff-check ## Alias for ruff-check.

basedpyright: ensure-uv ## Run basedpyright type checking.
	@echo "==> Running basedpyright"
	$(UV) run basedpyright . --verbose

ty: ensure-uv ## Run ty type checking.
	@echo "==> Running ty"
	$(UV) run ty check

typecheck: basedpyright ## Alias for basedpyright.

check: ruff-format-check ruff-check basedpyright ty test ## Run format, lint, type checks, and tests without modifying files.

.PHONY: docs-serve docs-build docs-deploy docs-list
docs-serve: ensure-uv ## Serve docs site locally.
	@echo "==> Serving docs locally"
	$(ZENSICAL) serve

docs-build: ensure-uv ## Build docs site.
	@echo "==> Building docs site"
	$(ZENSICAL) build --strict

docs-deploy: ensure-uv ## Deploy versioned docs locally (e.g. make docs-deploy VERSION=0.7.0).
	@echo "==> Deploying docs version $(VERSION)"
	$(UV) run mike deploy --update-aliases $(VERSION) latest

docs-list: ensure-uv ## List all deployed doc versions.
	$(UV) run mike list
