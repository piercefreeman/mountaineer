#
# Main Makefile for project development and CI
#

# Default shell
SHELL := /bin/bash
# Fail on first error
.SHELLFLAGS := -ec

# Global variables
LIB_DIR := ./
LIB_NAME := mountaineer

CREATE_MOUNTAINEER_APP_DIR := create_mountaineer_app
CREATE_MOUNTAINEER_APP_NAME := create_mountaineer_app

DOCS_WEBSITE_DIR := docs_website
DOCS_WEBSITE_NAME := docs_website

SCRIPTS_DIR := .github
SCRIPTS_NAME := scripts

# Ignore these directories in the local filesystem if they exist
.PHONY: lint test

# Main lint target
lint: lint-lib lint-create-mountaineer-app lint-scripts

# Lint validation target
lint-validation: lint-validation-lib lint-validation-create-mountaineer-app lint-validation-scripts

# Testing target
test: test-lib test-create-mountaineer-app test-scripts

# Integration testing target
test-integrations: test-lib-integrations test-create-mountaineer-app-integrations

# Install all sub-project dependencies with uv
install-deps: install-deps-lib install-deps-create-mountaineer-app install-deps-scripts

install-deps-lib:
	@echo "Installing dependencies for $(LIB_DIR)..."
	@(cd $(LIB_DIR) && uv sync)
	@(cd $(LIB_DIR) && uv run maturin develop --uv)

install-deps-create-mountaineer-app:
	@echo "Installing dependencies for $(CREATE_MOUNTAINEER_APP_DIR)..."
	@(cd $(CREATE_MOUNTAINEER_APP_DIR) && uv sync)
	@(cd $(CREATE_MOUNTAINEER_APP_DIR) && uv pip install -e .)

install-deps-scripts:
	@echo "Installing dependencies for $(SCRIPTS_DIR)..."
	@(cd $(SCRIPTS_DIR) && uv sync)

# Standard linting - local development, with fixing enabled
lint-lib:
	$(call lint-common,$(LIB_DIR),$(LIB_NAME))
	$(call lint-rust,$(LIB_DIR))
lint-create-mountaineer-app:
	$(call lint-common,$(CREATE_MOUNTAINEER_APP_DIR),$(CREATE_MOUNTAINEER_APP_NAME))
lint-scripts:
	$(call lint-common,$(SCRIPTS_DIR),$(SCRIPTS_NAME))

# Lint validation - CI to fail on any errors
lint-validation-lib:
	$(call lint-validation-common,$(LIB_DIR),$(LIB_NAME))
	$(call lint-rust,$(LIB_DIR))
lint-validation-create-mountaineer-app:
	$(call lint-validation-common,$(CREATE_MOUNTAINEER_APP_DIR),$(CREATE_MOUNTAINEER_APP_NAME))
lint-validation-scripts:
	$(call lint-validation-common,$(SCRIPTS_DIR),$(SCRIPTS_NAME))

# Tests
test-lib:
	@(cd $(LIB_DIR) && docker compose -f docker-compose.test.yml up -d)
	@$(call wait-for-postgres,30,5438)
	@$(call test-common,$(LIB_DIR),$(LIB_NAME))
	@(cd $(LIB_DIR) && docker compose -f docker-compose.test.yml down)
	@$(call test-rust-common,$(LIB_DIR),$(LIB_NAME))
test-lib-integrations:
	$(call test-common-integrations,$(LIB_DIR),$(LIB_NAME))
test-create-mountaineer-app:
	$(call test-common,$(CREATE_MOUNTAINEER_APP_DIR),$(CREATE_MOUNTAINEER_APP_NAME))
test-create-mountaineer-app-integrations:
	$(call test-common-integrations,$(CREATE_MOUNTAINEER_APP_DIR),$(CREATE_MOUNTAINEER_APP_NAME))
test-scripts:
	$(call test-common,$(SCRIPTS_DIR),$(SCRIPTS_NAME))

#
# Common helper functions
#

# Python testing functions
define test-common
	echo "\n=== Running Python tests for $(2) ==="
	(cd $(1) && uv run pytest -vvv -W "error::Warning" -W "default::PendingDeprecationWarning" $(test-args) $(2))
	echo "=== Python tests completed successfully for $(2) ==="
endef

# Rust testing functions
define test-rust-common
	echo "\n=== Running Rust tests for $(2) ==="
	(cd $(1) && cargo test --all)
	echo "=== Rust tests completed successfully for $(2) ==="
endef

# Integration testing functions
define test-common-integrations
	echo "\n=== Running integration tests for $(2) ==="
	(cd $(1) && uv run pytest -s -m integration_tests -vvv -W "error::Warning" -W "default::PendingDeprecationWarning" $(2))
	echo "=== Integration tests completed successfully for $(2) ==="
endef

# Python linting functions - development mode with fixes
define lint-common
	@echo "\n=== Running Python linting for $(2) ==="
	@(cd $(1) && uv run ruff format $(2))
	@(cd $(1) && uv run ruff check --fix $(2))
	@echo "\n=== Running mypy for $(2) ==="
	@(cd $(1) && uv run mypy $(2))
	@echo "\n=== Running pyright for $(2) ==="
	@(cd $(1) && uv run pyright $(2))
	@echo "=== Python linting completed successfully for $(2) ==="
endef

# Python linting functions - CI validation mode
define lint-validation-common
	@echo "\n=== Running Python lint validation for $(2) ==="
	@(cd $(1) && uv run ruff format --check $(2))
	@(cd $(1) && uv run ruff check $(2))
	@echo "\n=== Running mypy validation for $(2) ==="
	@(cd $(1) && uv run mypy $(2))
	@echo "\n=== Running pyright validation for $(2) ==="
	@(cd $(1) && uv run pyright $(2))
	@echo "=== Python lint validation completed successfully for $(2) ==="
endef

# Rust linting functions
define run-rustfmt
	@echo "\n=== Running rustfmt on $(1) ==="
	@(cd $(1) && cargo fmt) || { echo "FAILED: rustfmt in $(1)"; exit 1; }
	@(cd $(1) && cargo fix --allow-dirty --allow-staged) || { echo "FAILED: rustfix in $(1)"; exit 1; }
	@echo "=== rustfmt completed successfully for $(1) ==="
endef

define run-clippy
	@echo "\n=== Running clippy on $(1) ==="
	@(cd $(1) && cargo clippy -- -D warnings) || { echo "FAILED: clippy in $(1)"; exit 1; }
	@echo "=== clippy completed successfully for $(1) ==="
endef

define lint-rust
	@echo "\n=== Running all Rust linters on $(1) ==="
	$(call run-rustfmt,$(1))
	$(call run-clippy,$(1))
	@echo "=== All Rust linters completed successfully for $(1) ==="
endef

# Database helper functions
define wait-for-postgres
	@echo "\n=== Waiting for PostgreSQL to be ready ==="
	@timeout=$(1); \
	while ! nc -z localhost $(2) >/dev/null 2>&1; do \
		timeout=$$((timeout-1)); \
		if [ $$timeout -le 0 ]; then \
			echo "FAILED: Timed out waiting for PostgreSQL to start on port $(2)"; \
			exit 1; \
		fi; \
		echo "Waiting for PostgreSQL to start..."; \
		sleep 1; \
	done; \
	echo "=== PostgreSQL is ready on port $(2) ==="
endef
