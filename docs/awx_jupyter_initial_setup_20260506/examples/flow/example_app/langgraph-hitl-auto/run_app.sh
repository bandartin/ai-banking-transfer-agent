#!/bin/bash
HOST=${1:-0.0.0.0}
PORT=${2:-8001}
UV_BIN=${3:-uv}

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$SCRIPT_DIR"
. "$SCRIPT_DIR/../_shared/bootstrap_local_awx_sdk.sh"

if [ -z "$CUSTOM_VENV_PATH" ]; then
    CUSTOM_VENV_PATH="/tmp/venv_langgraph_hitl"
fi

if [ -n "$CUSTOM_VENV_PATH" ]; then
    echo "[Server] Using custom virtual environment at: $CUSTOM_VENV_PATH"
    export UV_PROJECT_ENVIRONMENT="$CUSTOM_VENV_PATH"
    if [ ! -d "$CUSTOM_VENV_PATH" ]; then
        echo "Creating new virtual environment..."
        $UV_BIN venv "$CUSTOM_VENV_PATH"
    fi
fi

prepend_awx_sdk_pythonpath "$SCRIPT_DIR"

echo "[Server] Starting App on $HOST:$PORT..."
$UV_BIN sync

if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    . "$SCRIPT_DIR/.env"
    set +a
fi

export CHAT_API_BASE_URL="${CHAT_API_BASE_URL:-http://127.0.0.1:$PORT}"

ARGS=(uvicorn main:app --host "$HOST" --port "$PORT")
if [ -n "$ROOT_PATH" ]; then
    ARGS+=(--root-path "$ROOT_PATH")
fi

$UV_BIN run opentelemetry-instrument "${ARGS[@]}"
