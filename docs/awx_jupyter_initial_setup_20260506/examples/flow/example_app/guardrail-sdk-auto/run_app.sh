#!/bin/bash
CLI_HOST_ARG=${1:-}
CLI_PORT_ARG=${2:-}
HOST=${CLI_HOST_ARG:-0.0.0.0}
PORT=${CLI_PORT_ARG:-8001}
UV_BIN=${3:-uv}

# Resolve script location once and run relative to it.
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$SCRIPT_DIR"
. "$SCRIPT_DIR/../_shared/bootstrap_local_awx_sdk.sh"

if [ -z "$CUSTOM_VENV_PATH" ]; then
    CUSTOM_VENV_PATH="/tmp/venv"
fi

if [ -n "$CUSTOM_VENV_PATH" ]; then
    echo "[Server] Using custom virtual environment at: $CUSTOM_VENV_PATH"
    export UV_PROJECT_ENVIRONMENT="$CUSTOM_VENV_PATH"
    $UV_BIN venv --allow-existing "$CUSTOM_VENV_PATH"
fi

prepend_awx_sdk_pythonpath "$SCRIPT_DIR"

echo "[Server] Starting guardrail-sdk-auto on $HOST:$PORT..."

if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    . "$SCRIPT_DIR/.env"
    set +a
fi

# This example does not use LangChain. Disable its auto-instrumentor by default
# so unrelated global/site packages do not break process startup.
if [ -z "${OTEL_PYTHON_DISABLED_INSTRUMENTATIONS:-}" ]; then
    export OTEL_PYTHON_DISABLED_INSTRUMENTATIONS="langchain"
elif [[ ",${OTEL_PYTHON_DISABLED_INSTRUMENTATIONS}," != *",langchain,"* ]]; then
    export OTEL_PYTHON_DISABLED_INSTRUMENTATIONS="${OTEL_PYTHON_DISABLED_INSTRUMENTATIONS},langchain"
fi

# CLI args must win over .env values.
if [ -n "$CLI_HOST_ARG" ]; then
    HOST="$CLI_HOST_ARG"
fi
if [ -n "$CLI_PORT_ARG" ]; then
    PORT="$CLI_PORT_ARG"
fi

if [ -z "$PIP_INDEX_URL" ] && [ -z "$PIP_EXTRA_INDEX_URL" ] && [ -z "$UV_LOCAL_PACKAGES" ]; then
    if python3 - <<'PY' >/dev/null 2>&1
import importlib
import sys

required = ("fastapi", "uvicorn", "awx.resources")
for name in required:
    try:
        importlib.import_module(name)
    except Exception:
        sys.exit(1)
sys.exit(0)
PY
    then
        echo "[Flow] Skipping uv sync (using system-installed packages)."
        SKIP_UV_SYNC=1
    fi
fi

if [ -z "$SKIP_UV_SYNC" ]; then
    $UV_BIN sync
fi

ARGS="python main.py --host $HOST --port $PORT"
if [ -n "$ROOT_PATH" ]; then
    ARGS="$ARGS --root-path $ROOT_PATH"
fi

if [ -n "$SKIP_UV_SYNC" ]; then
    if ! command -v opentelemetry-instrument >/dev/null 2>&1; then
        echo "[Flow] ERROR: opentelemetry-instrument not found."
        echo "[Flow] Install opentelemetry-distro in the runtime environment."
        exit 3
    fi
    opentelemetry-instrument $ARGS
elif [ -f "$SCRIPT_DIR/.env" ]; then
    $UV_BIN run --env-file "$SCRIPT_DIR/.env" opentelemetry-instrument $ARGS
else
    $UV_BIN run opentelemetry-instrument $ARGS
fi
