WIDGETS_DIR ?= ../widgets
PYTHON ?= scripts/python.sh
PRETTIER ?= npx --yes prettier@3.9.6
TAPLO ?= npx --yes @taplo/cli@0.7.0
PRETTIER_MD_SOURCES := README.md
PRETTIER_YAML_SOURCES := ".github/**/*.{yml,yaml}"
PRETTIER_JSON_SOURCES := ".github/**/*.json"
TAPLO_SOURCES := registry.toml "packages/**/*.toml"
PYTHON_SOURCES := scripts tests

.DEFAULT_GOAL := help

.PHONY: help test check validate check-index test-unit \
        fmt fmt-md fmt-yaml fmt-json fmt-toml \
        lint lint-py lint-md lint-yaml lint-json lint-toml \
        generate sync clean

help: ## Display this help.
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z\_0-9-]+:.*?##/ { printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(MAKEFILE_LIST)

##@ Build and test

check: test lint ## Run the complete repository verification suite.

test: validate check-index test-unit ## Validate registry data and run unit tests.

validate: ## Validate registry metadata against the widgets source tree.
	@$(PYTHON) scripts/validate.py --widgets-dir "$(WIDGETS_DIR)"

check-index: ## Verify the generated package index is current.
	@$(PYTHON) scripts/build_index.py --check

test-unit: ## Run registry Python unit tests.
	@$(PYTHON) -m unittest discover -s tests -p 'test_*.py'

##@ Formatting

fmt: fmt-md fmt-yaml fmt-json fmt-toml ## Format supported metadata and configuration files.

fmt-md: ## Format Markdown files with Prettier.
	@$(PRETTIER) --write $(PRETTIER_MD_SOURCES)

fmt-yaml: ## Format YAML files with Prettier.
	@$(PRETTIER) --write $(PRETTIER_YAML_SOURCES)

fmt-json: ## Format JSON configuration files with Prettier.
	@$(PRETTIER) --write $(PRETTIER_JSON_SOURCES)

fmt-toml: ## Format TOML files with Taplo.
	@$(TAPLO) fmt $(TAPLO_SOURCES)

lint: lint-py lint-md lint-yaml lint-json lint-toml ## Check source and metadata without changing files.

lint-py: ## Check Python syntax.
	@$(PYTHON) -m compileall -q $(PYTHON_SOURCES)

lint-md: ## Check Markdown formatting with Prettier.
	@$(PRETTIER) --check $(PRETTIER_MD_SOURCES)

lint-yaml: ## Check YAML formatting with Prettier.
	@$(PRETTIER) --check $(PRETTIER_YAML_SOURCES)

lint-json: ## Check JSON configuration files with Prettier.
	@$(PRETTIER) --check $(PRETTIER_JSON_SOURCES)

lint-toml: ## Check TOML formatting with Taplo.
	@$(TAPLO) fmt --check $(TAPLO_SOURCES)

##@ Registry

generate: ## Generate the package index.
	@$(PYTHON) scripts/build_index.py

sync: ## Synchronize published package versions and regenerate the index.
	@$(PYTHON) scripts/sync_releases.py --widgets-dir "$(WIDGETS_DIR)"
	@$(PYTHON) scripts/build_index.py

##@ Maintenance

clean: ## Remove local Python cache files.
	@find scripts tests -type d -name __pycache__ -prune -exec rm -rf {} +
