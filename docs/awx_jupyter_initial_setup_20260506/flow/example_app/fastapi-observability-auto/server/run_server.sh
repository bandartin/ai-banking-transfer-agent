#!/bin/bash
HOST=${1:-0.0.0.0}
PORT=${2:-8001}
UV_BIN=${3:-uv}

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$SCRIPT_DIR"
. "$SCRIPT_DIR/../../_shared/bootstrap_local_awx_sdk.sh"

# ------------------------------------------------------------------
# Custom Package Install Path (Virtual Environment)
# ------------------------------------------------------------------
# Define CUSTOM_VENV_PATH environment variable to override location
# Example: export CUSTOM_VENV_PATH="/project/work/temp/venv"
# Default to /tmp/venv if not set
if [ -z "$CUSTOM_VENV_PATH" ]; then
    CUSTOM_VENV_PATH="/tmp/venv"
fi

export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"

if [ -n "$CUSTOM_VENV_PATH" ]; then
    echo "[Server] Using custom virtual environment at: $CUSTOM_VENV_PATH"
    export UV_PROJECT_ENVIRONMENT="$CUSTOM_VENV_PATH"

    # Initialize venv if missing
    if [ ! -d "$CUSTOM_VENV_PATH" ]; then
        echo "Creating new virtual environment..."
        $UV_BIN venv "$CUSTOM_VENV_PATH"
    fi
fi

prepend_awx_sdk_pythonpath "$SCRIPT_DIR"

echo "[Server] Starting MCP Server on $HOST:$PORT..."
$UV_BIN sync --no-install-project --inexact

if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    . "$SCRIPT_DIR/.env"
    set +a
fi

export OTEL_PYTHON_DISABLED_INSTRUMENTATIONS="${OTEL_PYTHON_DISABLED_INSTRUMENTATIONS:-fastapi,starlette}"

$UV_BIN run --no-sync opentelemetry-instrument \
    uvicorn server:app --host $HOST --port $PORT
