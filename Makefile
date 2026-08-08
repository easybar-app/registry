WIDGETS_DIR ?= ../widgets
PYTHON ?= scripts/python.sh

.PHONY: check validate generate sync

check: validate
	@$(PYTHON) scripts/build_index.py --check

validate:
	@$(PYTHON) scripts/validate.py --widgets-dir "$(WIDGETS_DIR)"

generate:
	@$(PYTHON) scripts/build_index.py

sync:
	@$(PYTHON) scripts/sync_releases.py
	@$(PYTHON) scripts/build_index.py
