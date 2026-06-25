#!/bin/bash
set -euo pipefail

CLI_HOST_ARG=${1:-}
CLI_PORT_ARG=${2:-}
HOST=${CLI_HOST_ARG:-${HOST:-0.0.0.0}}
PORT=${CLI_PORT_ARG:-${PORT:-8001}}
UV_BIN=${3:-uv}

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$SCRIPT_DIR"
. "$SCRIPT_DIR/../_shared/bootstrap_local_awx_sdk.sh"

if [ -z "${CUSTOM_VENV_PATH:-}" ]; then
    CUSTOM_VENV_PATH="/tmp/venv"
fi

echo "[Server] Starting fastapi-credential-sdk-auto on $HOST:$PORT"

export UV_PROJECT_ENVIRONMENT="$CUSTOM_VENV_PATH"
$UV_BIN venv --allow-existing "$CUSTOM_VENV_PATH"
prepend_awx_sdk_pythonpath "$SCRIPT_DIR"

if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    . "$SCRIPT_DIR/.env"
    set +a
fi

if [ -z "${OTEL_TRACES_EXPORTER:-}" ]; then
    export OTEL_TRACES_EXPORTER=otlp
fi
if [ -z "${OTEL_METRICS_EXPORTER:-}" ]; then
    export OTEL_METRICS_EXPORTER=otlp
fi
if [ -z "${OTEL_LOGS_EXPORTER:-}" ]; then
    export OTEL_LOGS_EXPORTER=otlp
fi

if [ -z "${PIP_INDEX_URL:-}" ] && [ -z "${PIP_EXTRA_INDEX_URL:-}" ] && [ -z "${UV_LOCAL_PACKAGES:-}" ]; then
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

if [ -z "${SKIP_UV_SYNC:-}" ]; then
    $UV_BIN sync
fi

ARGS="python main.py --host $HOST --port $PORT"
if [ -n "${ROOT_PATH:-}" ]; then
    ARGS="$ARGS --root-path $ROOT_PATH"
fi

if [ -n "${SKIP_UV_SYNC:-}" ]; then
    opentelemetry-instrument $ARGS
elif [ -f "$SCRIPT_DIR/.env" ]; then
    $UV_BIN run --env-file "$SCRIPT_DIR/.env" opentelemetry-instrument $ARGS
else
    $UV_BIN run opentelemetry-instrument $ARGS
fi
