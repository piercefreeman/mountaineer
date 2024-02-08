#
# Main Makefile for project development and CI
#

# Default shell
SHELL := /bin/bash
# Fail on first error
.SHELLFLAGS := -ec

# Global variables
LIB_DIR := ./
LIB_NAME := filzl

CREATE_FILZL_APP_DIR := create_filzl_app
CREATE_FILZL_APP_NAME := create_filzl_app

MY_WEBSITE_DIR := my_website
MY_WEBSITE_NAME := my_website

# Phony targets for clean commands
.PHONY: lint lint-validation lint-common lint-validation-common

# Main lint target
lint: lint-lib lint-create-filzl-app lint-my-website

# Lint validation target
lint-validation: lint-validation-lib lint-validation-create-filzl-app lint-validation-my-website

# Testing target
test: test-lib test-create-filzl-app

# Integration testing target
test-integrations: test-create-filzl-app-integrations

# Install all sub-project dependencies with poetry
install-deps:
	@echo "Installing dependencies for $(LIB_DIR)..."
	@(cd $(LIB_DIR) && poetry install)
	@(poetry run maturin develop --release)

	@echo "Installing dependencies for $(CREATE_FILZL_APP_DIR)..."
	@(cd $(CREATE_FILZL_APP_DIR) && poetry install)

	@echo "Installing dependencies for $(MY_WEBSITE_DIR)..."
	@(cd $(MY_WEBSITE_DIR) && poetry install)

# Clean the current poetry.lock files, useful for remote CI machines
# where we're running on a different base architecture than when
# developing locally
clean-poetry-lock:
	@echo "Cleaning poetry.lock files..."
	@rm -f $(LIB_DIR)/poetry.lock
	@rm -f $(CREATE_FILZL_APP_DIR)/poetry.lock
	@rm -f $(MY_WEBSITE_DIR)/poetry.lock

# Standard linting - local development, with fixing enabled
lint-lib:
	$(call lint-common,$(LIB_DIR),$(LIB_NAME))
lint-create-filzl-app:
	$(call lint-common,$(CREATE_FILZL_APP_DIR),$(CREATE_FILZL_APP_NAME))
lint-my-website:
	$(call lint-common,$(MY_WEBSITE_DIR),$(MY_WEBSITE_NAME))

# Lint validation - CI to fail on any errors
lint-validation-lib:
	$(call lint-validation-common,$(LIB_DIR),$(LIB_NAME))
lint-validation-create-filzl-app:
	$(call lint-validation-common,$(CREATE_FILZL_APP_DIR),$(CREATE_FILZL_APP_NAME))
lint-validation-my-website:
	$(call lint-validation-common,$(MY_WEBSITE_DIR),$(MY_WEBSITE_NAME))

test-lib:
	$(call test-common,$(LIB_DIR),$(LIB_NAME))

test-create-filzl-app:
	$(call test-common,$(CREATE_FILZL_APP_DIR),$(CREATE_FILZL_APP_NAME))

test-create-filzl-app-integrations:
	$(call test-common-integrations,$(CREATE_FILZL_APP_DIR),$(CREATE_FILZL_APP_NAME))

#
# Common helper functions
#

define test-common
	echo "Running tests for $(2)..."
	@(cd $(1) && poetry run pytest -W error $(2))
endef

# Use `-n auto` to run tests in parallel
define test-common-integrations
	echo "Running tests for $(2)..."
	@(cd $(1) && poetry run pytest -s -m integration_tests -W error $(2))
endef

define lint-common
	echo "Running linting for $(2)..."
	@(cd $(1) && poetry run ruff format $(2))
	@(cd $(1) && poetry run ruff check --fix $(2))
	@(cd $(1) && poetry run mypy $(2))
endef

define lint-validation-common
	echo "Running lint validation for $(2)..."
	@(cd $(1) && poetry run ruff format --check $(2))
	@(cd $(1) && poetry run ruff check $(2))
	@(cd $(1) && poetry run mypy $(2))
endef
