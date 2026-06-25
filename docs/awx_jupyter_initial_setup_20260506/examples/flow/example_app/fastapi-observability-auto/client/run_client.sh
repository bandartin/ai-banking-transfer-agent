#!/bin/bash
HOST=${1:-0.0.0.0}
PORT=${2:-8000}
UV_BIN=${3:-uv}

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$SCRIPT_DIR"
. "$SCRIPT_DIR/../../_shared/bootstrap_local_awx_sdk.sh"

if [ -z "$CUSTOM_VENV_PATH" ]; then
    CUSTOM_VENV_PATH="/tmp/venv"
fi

export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"

if [ -n "$CUSTOM_VENV_PATH" ]; then
    echo "[Client] Using custom virtual environment at: $CUSTOM_VENV_PATH"
    export UV_PROJECT_ENVIRONMENT="$CUSTOM_VENV_PATH"
    # The AWX SDK is expected to be installed in system site-packages in real deployments.
    # Keep venv linked to system packages so `import awx` works without per-app wheel install.
    $UV_BIN venv --allow-existing --system-site-packages "$CUSTOM_VENV_PATH"
fi

prepend_awx_sdk_pythonpath "$SCRIPT_DIR"

echo "[Client] Starting AWX Observability MCP Client on $HOST:$PORT..."
$UV_BIN sync --no-install-project --inexact

if [ "${AWX_SMOKE:-0}" != "1" ]; then
    if ! $UV_BIN run --no-sync python -c "import awx.observability" >/dev/null 2>&1; then
        echo "[Client] ERROR: observability SDK is not available in this environment."
        echo "[Client] Ensure the base image/system has awx SDK installed, then retry."
        exit 3
    fi
else
    echo "[Client] SMOKE: skipping observability import check"
fi

load_env_defaults() {
    local env_file="$1"
    while IFS= read -r line || [ -n "$line" ]; do
        line="${line#"${line%%[![:space:]]*}"}"
        case "$line" in
            ""|\#*) continue ;;
        esac
        if [[ ! "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; then
            continue
        fi
        local key="${line%%=*}"
        local value="${line#*=}"
        if [ -z "${!key+x}" ]; then
            export "$key=$value"
        fi
    done < "$env_file"
}

if [ -f .env ]; then
    # .env is treated as defaults. Runtime-injected env values must win.
    load_env_defaults ./.env
fi

export OTEL_PYTHON_DISABLED_INSTRUMENTATIONS="${OTEL_PYTHON_DISABLED_INSTRUMENTATIONS:-fastapi,starlette}"

$UV_BIN run --no-sync opentelemetry-instrument \
    uvicorn client:app --host $HOST --port $PORT
