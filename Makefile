WIDGETS_DIR ?= ../widgets
PYTHON ?= scripts/python.sh
PRETTIER ?= npx --yes prettier@3.9.6
TAPLO ?= npx --yes @taplo/cli@0.7.0
PRETTIER_MD_SOURCES := README.md
PRETTIER_YAML_SOURCES := ".github/**/*.{yml,yaml}"
PRETTIER_JSON_SOURCES := ".github/**/*.json"
TAPLO_SOURCES := registry.toml "packages/**/*.toml"

.DEFAULT_GOAL := help

.PHONY: help fmt fmt-md fmt-yaml fmt-json fmt-toml check validate generate sync

help: ## Display this help.
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z\_0-9-]+:.*?##/ { printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(MAKEFILE_LIST)

##@ Formatting

fmt: fmt-md fmt-yaml fmt-json fmt-toml ## Format all supported metadata and configuration files.

fmt-md: ## Format Markdown files with Prettier.
	@$(PRETTIER) --write $(PRETTIER_MD_SOURCES)

fmt-yaml: ## Format YAML files with Prettier.
	@$(PRETTIER) --write $(PRETTIER_YAML_SOURCES)

fmt-json: ## Format JSON configuration files with Prettier.
	@$(PRETTIER) --write $(PRETTIER_JSON_SOURCES)

fmt-toml: ## Format TOML files with Taplo.
	@$(TAPLO) fmt $(TAPLO_SOURCES)

##@ Registry

check: validate ## Validate metadata and verify the generated index.
	@$(PYTHON) scripts/build_index.py --check

validate: ## Validate registry and package metadata.
	@$(PYTHON) scripts/validate.py --widgets-dir "$(WIDGETS_DIR)"

generate: ## Generate the package index.
	@$(PYTHON) scripts/build_index.py

sync: ## Synchronize released package versions and regenerate the index.
	@$(PYTHON) scripts/sync_releases.py
	@$(PYTHON) scripts/build_index.py
