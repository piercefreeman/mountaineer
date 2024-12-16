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

# Install all sub-project dependencies with poetry
install-deps: install-deps-lib install-deps-create-mountaineer-app install-deps-scripts

install-deps-lib:
	@echo "Installing dependencies for $(LIB_DIR)..."
	@(cd $(LIB_DIR) && poetry install)
	@(cd $(LIB_DIR) && poetry run maturin develop --release)

install-deps-create-mountaineer-app:
	@echo "Installing dependencies for $(CREATE_MOUNTAINEER_APP_DIR)..."
	@(cd $(CREATE_MOUNTAINEER_APP_DIR) && poetry install)

install-deps-scripts:
	@echo "Installing dependencies for $(SCRIPTS_DIR)..."
	@(cd $(SCRIPTS_DIR) && poetry install)

# Clean the current poetry.lock files, useful for remote CI machines
# where we're running on a different base architecture than when
# developing locally
clean-poetry-lock:
	@echo "Cleaning poetry.lock files..."
	@rm -f $(LIB_DIR)/poetry.lock
	@rm -f $(CREATE_MOUNTAINEER_APP_DIR)/poetry.lock
	@rm -f $(DOCS_WEBSITE_DIR)/poetry.lock
	@rm -f $(SCRIPTS_DIR)/poetry.lock

# Standard linting - local development, with fixing enabled
lint-lib:
	$(call lint-common,$(LIB_DIR),$(LIB_NAME))
lint-create-mountaineer-app:
	$(call lint-common,$(CREATE_MOUNTAINEER_APP_DIR),$(CREATE_MOUNTAINEER_APP_NAME))
lint-scripts:
	$(call lint-common,$(SCRIPTS_DIR),$(SCRIPTS_NAME))

# Lint validation - CI to fail on any errors
lint-validation-lib:
	$(call lint-validation-common,$(LIB_DIR),$(LIB_NAME))
lint-validation-create-mountaineer-app:
	$(call lint-validation-common,$(CREATE_MOUNTAINEER_APP_DIR),$(CREATE_MOUNTAINEER_APP_NAME))
lint-validation-scripts:
	$(call lint-validation-common,$(SCRIPTS_DIR),$(SCRIPTS_NAME))

# Tests
test-lib:
	(cd $(LIB_DIR) && docker compose -f docker-compose.test.yml up -d)
	@$(call wait-for-postgres,30,5438)
	@set -e; \
	$(call test-common,$(LIB_DIR),$(LIB_NAME))
	(cd $(LIB_DIR) && docker compose -f docker-compose.test.yml down)
	$(call test-rust-common,$(LIB_DIR),$(LIB_NAME))
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

define test-common
	echo "Running tests for $(2)..."
	@(cd $(1) && poetry run pytest -vvv -W "error::Warning" -W "default::PendingDeprecationWarning" $(test-args) $(2))
endef

define test-rust-common
	echo "Running rust tests for $(2)..."
	@(cd $(1) && cargo test --all)
endef

# Use `-n auto` to run tests in parallel
define test-common-integrations
	echo "Running tests for $(2)..."
	@(cd $(1) && poetry run pytest -s -m integration_tests -vvv -W "error::Warning" -W "default::PendingDeprecationWarning" $(2))
endef

define lint-common
	echo "Running linting for $(2)..."
	@(cd $(1) && poetry run ruff format $(2))
	@(cd $(1) && poetry run ruff check --fix $(2))
	echo "Running mypy for $(2)..."
	@(cd $(1) && poetry run mypy $(2))
	echo "Running pyright for $(2)..."
	@(cd $(1) && poetry run pyright $(2))
endef

define lint-validation-common
	echo "Running lint validation for $(2)..."
	@(cd $(1) && poetry run ruff format --check $(2))
	@(cd $(1) && poetry run ruff check $(2))
	echo "Running mypy for $(2)..."
	@(cd $(1) && poetry run mypy $(2))
	echo "Running pyright for $(2)..."
	@(cd $(1) && poetry run pyright $(2))
endef

# Function to wait for PostgreSQL to be ready
define wait-for-postgres
	@echo "Waiting for PostgreSQL to be ready..."
	@timeout=$(1); \
	while ! nc -z localhost $(2) >/dev/null 2>&1; do \
		timeout=$$((timeout-1)); \
		if [ $$timeout -le 0 ]; then \
			echo "Timed out waiting for PostgreSQL to start on port $(2)"; \
			exit 1; \
		fi; \
		echo "Waiting for PostgreSQL to start..."; \
		sleep 1; \
	done; \
	echo "PostgreSQL is ready on port $(2)."
endef
