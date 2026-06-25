#!/bin/bash
HOST=${1:-0.0.0.0}
PORT=${2:-8001}
UV_BIN=${3:-uv}

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$SCRIPT_DIR"
. "$SCRIPT_DIR/../../_shared/bootstrap_local_awx_sdk.sh"

if [ -z "$CUSTOM_VENV_PATH" ]; then
    CUSTOM_VENV_PATH="/tmp/venv"
fi

export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"

if [ -n "$CUSTOM_VENV_PATH" ]; then
    echo "[Server] Using custom virtual environment at: $CUSTOM_VENV_PATH"
    export UV_PROJECT_ENVIRONMENT="$CUSTOM_VENV_PATH"
    $UV_BIN venv --allow-existing --system-site-packages "$CUSTOM_VENV_PATH"
fi

prepend_awx_sdk_pythonpath "$SCRIPT_DIR"

echo "[Server] Starting MCP Server on $HOST:$PORT..."
$UV_BIN sync --no-install-project --inexact

if [ -f .env ]; then
    set -a
    . ./.env
    set +a
fi

export OTEL_PYTHON_DISABLED_INSTRUMENTATIONS="${OTEL_PYTHON_DISABLED_INSTRUMENTATIONS:-fastapi,starlette}"

$UV_BIN run --no-sync opentelemetry-instrument \
    uvicorn server:app --host $HOST --port $PORT
