.PHONY: help init run sync test offline online check-uv clean
.DEFAULT_GOAL := help
SHELL := /bin/bash

help:
	@echo "================================================================="
	@echo " AWX Flow Makefile Help"
	@echo "================================================================="
	@echo " init    : Initialize an app. Usage: make init app=<name>[.<mode>]"
	@echo "           Example: make init app=guardrail-sdk-auto"
	@echo "           Example: make init app=fastapi-observability-auto.client"
	@echo "           Example: make init app=langchain-agent-sdk-auto.agent"
	@echo "           Example: make init app=mcp-agent-sdk-auto.server"
	@echo "           Example: make init app=mcp-agent-sdk-auto.agent"
	@echo " run     : Run the initialized app. Usage: make run [app=<name>] [port=<port>]"
	@echo " test    : Smoke-run init+run for each example app (process start check only)"
	@echo " pytest  : Run pytest suites under example_app"
	@echo " sync    : Install dependencies for the initialized app."
	@echo " test    : Run tests for the initialized app/mode."
	@echo " smoke   : Make-level boot smoke tests for apps (init+run sanity)."
	@echo " check-uv: Check if uv is installed."
	@echo " clean   : Clean up the environment config."
	@echo " online  : Enable online mode."
	@echo " offline : Enable offline mode."
	@echo "================================================================="

CUSTOM_VENV_PATH ?=
UV_SYNC_ARGS ?= --inexact --no-default-groups
MODE ?=
HOST ?= 0.0.0.0
PORT ?= 8000
APP_DIR_LIST_CMD = find example_app -mindepth 1 -maxdepth 1 -type d ! -name '_*' ! -name 'tests' -printf '%f\n' | sort

# Logic to handle positional arguments for init
# If the first goal is "init", checks the second goal.
ifeq (init,$(firstword $(MAKECMDGOALS)))
  # If app is not set, look for the second word
  ifndef app
    POS_APP := $(word 2,$(MAKECMDGOALS))
    ifneq ($(POS_APP),)
      app := $(POS_APP)
    endif
  endif
endif

check-uv:
	@which uv > /dev/null || (echo "Error: uv is not installed" && exit 1)

init:
	@if [ -z "$(app)" ]; then \
		echo "Usage: make init <app_name>[.<mode>]"; \
		echo "   or: make init app=<app_name>[.<mode>]"; \
		echo ""; \
		echo "Available Apps:"; \
		if [ -d "example_app" ]; then \
			$(APP_DIR_LIST_CMD) | sed 's/^/  - /'; \
		else \
			echo "  (no example_app directory found)"; \
		fi; \
		exit 1; \
	fi
	@RAW_APP=$(app); \
	APP_NAME=$$(echo $$RAW_APP | cut -d. -f1); \
	APP_MODE=$$(echo $$RAW_APP | cut -s -d. -f2); \
	if [ -z "$$APP_MODE" ]; then APP_MODE="server"; fi; \
	if [ ! -d "example_app/$$APP_NAME" ]; then \
		echo "Error: App '$$APP_NAME' not found in example_app/"; \
		echo "Available Apps:"; \
		if [ -d "example_app" ]; then \
			$(APP_DIR_LIST_CMD) | sed 's/^/  - /'; \
		else \
			echo "  (no example_app directory found)"; \
		fi; \
		exit 1; \
	fi; \
		echo "Switching to $$APP_NAME (Mode: $$APP_MODE)..."; \
		echo "APP_NAME=$$APP_NAME" > .app_env; \
		echo "APP_MODE=$$APP_MODE" >> .app_env; \
		if [ -f "example_app/_shared/bootstrap_local_awx_sdk.sh" ]; then \
			. "example_app/_shared/bootstrap_local_awx_sdk.sh"; \
			prepend_awx_sdk_pythonpath "$$(pwd)"; \
		fi; \
		python3 bootstrap_awx_sdk_artifacts.py --app-name "$$APP_NAME" --mode "$$APP_MODE" >/dev/null 2>&1 || true; \
		echo "App set to $$APP_NAME [$$APP_MODE]."; \
		true

which:
	@if [ -f .app_env ]; then \
		cat .app_env; \
	else \
		echo "No app initialized."; \
	fi

run:
	@RAW_RUN_APP="$(app)"; \
	APP_TARGET="$$RAW_RUN_APP"; \
	if [ -z "$$APP_TARGET" ] && [ -f .app_env ]; then \
		APP_TARGET=$$(grep '^APP_NAME=' .app_env | cut -d= -f2); \
	fi; \
	APP_BASE=$$(echo "$$APP_TARGET" | cut -d. -f1); \
	APP_NAME_ENV=""; \
	APP_MODE_ENV="$(mode)"; \
	if [ -n "$$RAW_RUN_APP" ]; then \
		APP_NAME_ENV=$$(echo "$$RAW_RUN_APP" | cut -d. -f1); \
		DOT_MODE=$$(echo "$$RAW_RUN_APP" | cut -s -d. -f2); \
		if [ -n "$$DOT_MODE" ] && [ -z "$$APP_MODE_ENV" ]; then \
			APP_MODE_ENV="$$DOT_MODE"; \
		fi; \
	fi; \
	if [ -n "$(MODE)" ]; then \
		MODE_ARG="$(MODE)"; \
	elif [ -n "$(mode)" ]; then \
		MODE_ARG="$(mode)"; \
	elif [ -n "$$APP_MODE_ENV" ]; then \
		MODE_ARG="$$APP_MODE_ENV"; \
	else \
		MODE_ARG=""; \
	fi; \
	APP_NAME="$$APP_NAME_ENV" APP_MODE="$$APP_MODE_ENV" bash run-application.sh "$$MODE_ARG" "$(HOST)" "$(PORT)"

sync: check-uv
	@if [ ! -f .app_env ]; then echo "Error: No app initialized. Run 'make init app=<name>'"; exit 1; fi
	@$(eval APP_NAME := $(shell grep APP_NAME .app_env | cut -d= -f2))
	@$(eval APP_MODE := $(shell grep APP_MODE .app_env | cut -d= -f2))
	@echo "Syncing dependencies for $(APP_NAME)..."
	@DEFAULT_VENV_PATH=$$(bash ./venv-path.sh "$(APP_NAME)"); \
	VENV_PATH="$(CUSTOM_VENV_PATH)"; \
	if [ -z "$$VENV_PATH" ]; then VENV_PATH="$$DEFAULT_VENV_PATH"; fi; \
	echo "Using virtual environment: $$VENV_PATH"; \
	uv venv --system-site-packages "$$VENV_PATH"; \
	TARGET_DIR="example_app/$(APP_NAME)"; \
	if [ -n "$(APP_MODE)" ] && [ -d "example_app/$(APP_NAME)/$(APP_MODE)" ]; then \
		TARGET_DIR="example_app/$(APP_NAME)/$(APP_MODE)"; \
	elif [ -d "example_app/$(APP_NAME)/server" ]; then \
		TARGET_DIR="example_app/$(APP_NAME)/server"; \
	fi; \
	echo "Detected target directory: $$TARGET_DIR"; \
	cd "$$TARGET_DIR" && UV_PROJECT_ENVIRONMENT="$$VENV_PATH" uv sync $(UV_SYNC_ARGS)

pytest: check-uv
	@RAW_APP="$(app)"; \
	APP_NAME_FILTER=""; \
	APP_MODE_FILTER=""; \
	if [ -n "$$RAW_APP" ]; then \
		APP_NAME_FILTER=$$(echo "$$RAW_APP" | cut -d. -f1); \
		APP_MODE_FILTER=$$(echo "$$RAW_APP" | cut -s -d. -f2); \
	fi; \
	if [ -z "$$APP_MODE_FILTER" ] && [ -n "$(MODE)" ]; then \
		APP_MODE_FILTER="$(MODE)"; \
	fi; \
	FAIL=0; \
	RAN=0; \
	APP_LIST=$$($(APP_DIR_LIST_CMD)); \
	for CUR_APP in $$APP_LIST; do \
		if [ -n "$$APP_NAME_FILTER" ] && [ "$$CUR_APP" != "$$APP_NAME_FILTER" ]; then \
			continue; \
		fi; \
		APP_DIR="example_app/$$CUR_APP"; \
		TARGETS=""; \
		if [ -n "$$APP_MODE_FILTER" ]; then \
			if [ -d "$$APP_DIR/$$APP_MODE_FILTER" ]; then \
				TARGETS="$$APP_MODE_FILTER"; \
			fi; \
		else \
			TARGETS=$$(find "$$APP_DIR" -mindepth 1 -maxdepth 1 -type d \( -name 'server*' -o -name 'client' -o -name 'agent' \) -printf '%f\n' | sort); \
		fi; \
		if [ -z "$$TARGETS" ]; then TARGETS="app"; fi; \
		for TARGET in $$TARGETS; do \
			if [ "$$TARGET" = "app" ]; then \
				TARGET_DIR="$$APP_DIR"; \
				LABEL="$$CUR_APP[app]"; \
			else \
				TARGET_DIR="$$APP_DIR/$$TARGET"; \
				LABEL="$$CUR_APP[$$TARGET]"; \
			fi; \
			HAS_TESTS=$$(cd "$$TARGET_DIR" && find . -maxdepth 3 -type f \( -name "test_*.py" -o -name "*_test.py" -o -name "tests_*.py" \) | head -n 1); \
			if [ -z "$$HAS_TESTS" ]; then \
				echo "[test] skip $$LABEL (no tests)"; \
				continue; \
			fi; \
			RAN=$$((RAN+1)); \
			VENV_PATH="/tmp/venv_test_$$(echo "$$CUR_APP-$$TARGET" | tr '/' '_' | tr '-' '_')"; \
			echo "[test] run $$LABEL"; \
			uv venv --system-site-packages "$$VENV_PATH" >/dev/null; \
			( \
				cd "$$TARGET_DIR" && \
				UV_PROJECT_ENVIRONMENT="$$VENV_PATH" uv sync $(UV_SYNC_ARGS) --no-install-project && \
				UV_PROJECT_ENVIRONMENT="$$VENV_PATH" uv run --no-sync pytest -q; \
				RC=$$?; \
				if [ "$$RC" -ne 0 ] && [ "$$RC" -ne 5 ]; then \
					exit "$$RC"; \
				fi \
			) || FAIL=1; \
		done; \
	done; \
	if [ "$$RAN" -eq 0 ]; then \
		echo "[test] No tests found under example_app (or filter matched none)."; \
	fi; \
	echo "[test] executed targets: $$RAN"; \
	exit $$FAIL

test: check-uv
	@echo "[test] smoke-run init+run for each example_app"
	@FAIL=0; \
	ORIG_ENV_BACKUP=""; \
	if [ -f .app_env ]; then \
		ORIG_ENV_BACKUP=$$(mktemp /tmp/app_env.backup.XXXXXX); \
		cp .app_env "$$ORIG_ENV_BACKUP"; \
	fi; \
	APP_LIST=$$($(APP_DIR_LIST_CMD)); \
	PORT_BASE=$${PORT_BASE:-$$(expr 20000 + $$RANDOM % 10000)}; \
	PORT_IDX=0; \
	for CUR_APP in $$APP_LIST; do \
		APP_DIR="example_app/$$CUR_APP"; \
		TARGETS=$$(find "$$APP_DIR" -mindepth 1 -maxdepth 1 -type d \( -name 'server*' -o -name 'client' -o -name 'agent' \) -printf '%f\n' | sort); \
		if [ -z "$$TARGETS" ]; then TARGETS="app"; fi; \
		for TARGET in $$TARGETS; do \
			PORT=$$((PORT_BASE + PORT_IDX)); \
			PORT_IDX=$$((PORT_IDX + 1)); \
			APP_MODE="$$TARGET"; \
			if [ "$$TARGET" = "app" ]; then APP_MODE="server"; fi; \
			echo "[test] $$CUR_APP.$${APP_MODE} -> port $$PORT"; \
			$(MAKE) init app=$${CUR_APP}.$${APP_MODE} >/dev/null; \
			if [ "$$CUR_APP" = "fastapi-observability-auto" ] && [ "$$APP_MODE" = "client" ]; then \
				SDK_PATH="/home/user/idea-project/python-user-sdk/awx_observability/src"; \
				if [ -d "$$SDK_PATH" ]; then export PYTHONPATH="$$SDK_PATH"; fi; \
			else \
				unset PYTHONPATH; \
			fi; \
			SMOKE_VENV="/tmp/flow_smoke_venv_$${CUR_APP}_$${APP_MODE}"; \
			AWX_SMOKE=1 OPENAI_API_KEY=dummy \
			CUSTOM_VENV_PATH="$$SMOKE_VENV" \
			UV_CACHE_DIR="/tmp/uv-cache" \
			OTEL_TRACES_EXPORTER=none \
			OTEL_LOGS_EXPORTER=none \
			OTEL_METRICS_EXPORTER=none \
				timeout 20s $(MAKE) run PORT=$$PORT HOST=127.0.0.1 >/tmp/flow_smoke_$$CUR_APP.$${APP_MODE}.log 2>&1; \
			RC=$$?; \
			rm -f /tmp/flow-run-$${CUR_APP}-*.lock; \
			if [ "$$RC" -ne 0 ] && [ "$$RC" -ne 124 ]; then \
				echo "[test] FAIL $$CUR_APP.$${APP_MODE} (exit $$RC)"; \
				tail -n 50 /tmp/flow_smoke_$$CUR_APP.$${APP_MODE}.log; \
				FAIL=1; \
			else \
				echo "[test] OK $$CUR_APP.$${APP_MODE}"; \
			fi; \
		done; \
	done; \
	if [ -n "$$ORIG_ENV_BACKUP" ]; then \
		cp "$$ORIG_ENV_BACKUP" .app_env; \
		rm -f "$$ORIG_ENV_BACKUP"; \
	else \
		rm -f .app_env; \
	fi; \
	exit $$FAIL

offline:
	@echo "Setting Offline Mode..."
	@grep -q "export UV_OFFLINE=1" .app_env || echo "export UV_OFFLINE=1" >> .app_env
	@echo "Offline mode enabled."

online:
	@echo "Setting Online Mode..."
	@sed -i '/export UV_OFFLINE=1/d' .app_env
	@echo "Online mode enabled."

clean:
	@echo "Clearing app configuration..."
	@rm -f .app_env
	@echo "Cleaning up workspace..."
	@find . -maxdepth 1 ! -name 'Makefile' ! -name 'run-application.sh' ! -name 'example_app' ! -name 'example_sdk' ! -name '.venv' ! -name '.' ! -name '..' ! -name 'README.md' ! -name 'VERSION' ! -name '.gitignore' -exec rm -rf {} +
	@echo "Cleaned."

# Catch-all target to prevent errors for positional params
%:
	@:
