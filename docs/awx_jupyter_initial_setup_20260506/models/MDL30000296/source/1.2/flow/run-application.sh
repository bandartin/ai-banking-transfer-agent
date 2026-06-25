#!/bin/bash
export ENVIRONMENT=${ENVIRONMENT:-prod}

if [ "${FLOW_DEBUG:-0}" = "1" ]; then
    echo "[Flow] DEBUG pid=$$ ppid=$PPID argv: $0 $*"
    echo "[Flow] DEBUG pwd=$(pwd)"
    echo "[Flow] DEBUG PATH=$PATH"
    echo "[Flow] DEBUG which tree=$(command -v tree || echo 'NOT_FOUND')"
    ps -o pid,ppid,cmd -p "$PPID" 2>/dev/null | sed '1d' | sed 's/^/[Flow] DEBUG parent: /'
fi

# ------------------------------------------------------------------
# PATH CONFIGURATION
# ------------------------------------------------------------------

if [ -d "/infer-model" ]; then
    echo "INFERENCE...."
    export PATH_SOURCE=`tree -ifd /infer-model | grep flow | head -n 1`
    export PATH_TEMP="${PATH_INFER_ENV:-/tmp}/temp"
    export PATH_MODEL="$PATH_TEMP"
    echo $PATH_MODELS
else
    echo "DEV...."
    export PATH_SOURCE=${PATH_SOURCE:-"/project/work/flow"}
    export PATH_TEMP=${PATH_TEMP:-"/project/work/temp"}
    export PATH_MODEL="$PATH_TEMP"
fi

mkdir -p $PATH_TEMP

# ------------------------------------------------------------------
# APP RESOLUTION & DELEGATION
# ------------------------------------------------------------------

# Ensure we are in the source directory
if [ -d "$PATH_SOURCE" ]; then
    cd $PATH_SOURCE
fi

# APP RESOLUTION & DELEGATION
# ------------------------------------------------------------------

# Ensure we are in the source directory
if [ -d "$PATH_SOURCE" ]; then
    cd $PATH_SOURCE
fi

# Load APP_NAME from .app_env if present
APP_ENV_FILE=".app_env"
ENV_APP_NAME=""
ENV_APP_MODE=""
if [ -f "$APP_ENV_FILE" ]; then
    ENV_APP_NAME=$(grep APP_NAME "$APP_ENV_FILE" | cut -d= -f2)
    ENV_APP_MODE=$(grep APP_MODE "$APP_ENV_FILE" | cut -d= -f2)
fi

# If APP_NAME is passed via env (from Makefile), use it.
# Otherwise fall back to .app_env
if [ -n "$APP_NAME" ]; then
    # Overridden context
    # If overridden, we default MODE to server unless MODE arg provided
    # We ignore ENV_APP_MODE to prevents mode leakage (e.g. mcp.client -> mcp.server)
    CONTEXT_MODE_DEFAULT="server"
else
    # Configured context
    APP_NAME="$ENV_APP_NAME"
    CONTEXT_MODE_DEFAULT="${ENV_APP_MODE:-server}"
fi
export APP_NAME

if [ -z "$APP_NAME" ]; then
    echo "❌ Error: No application initialized."
    echo "💡 Please run initialization first:"
    echo "   make init <app_name>"
    echo ""
    echo "Available Apps:"
    ls example_app | sed 's/^/   - /'
    exit 1
fi

APP_DIR="example_app/$APP_NAME"

echo "[Flow] Target App: $APP_NAME ($APP_DIR)"

if [ ! -d "$APP_DIR" ]; then
    echo "Error: Directory '$APP_DIR' not found."
    exit 1
fi

# Prevent rapid re-launch loops (e.g., task runners or watchers)
LOCK_FILE="/tmp/flow-run-${APP_NAME}.lock"
if [ -f "$LOCK_FILE" ]; then
    LOCK_PID=$(cat "$LOCK_FILE" 2>/dev/null)
    if [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
        echo "[Flow] Already running (pid: $LOCK_PID). Skipping duplicate launch."
        exit 0
    fi
fi
echo $$ > "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

# Determine Mode / Host / Port (robust to positional misuse)
MODE_ARG=$1
HOST_ARG=$2
PORT_ARG=$3

# If first arg looks like host or port, treat it as host/port instead of mode
if [[ "$MODE_ARG" =~ ^[0-9]+$ ]] || [[ "$MODE_ARG" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    if [[ "$MODE_ARG" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        HOST_ARG="$MODE_ARG"
    else
        PORT_ARG="$MODE_ARG"
    fi
    MODE_ARG=""
fi

MODE=${MODE_ARG:-$CONTEXT_MODE_DEFAULT}
HOST=${HOST_ARG:-0.0.0.0}
PORT=${PORT_ARG:-8000}

RUN_SCRIPT="run_app.sh"

if [ "$MODE" = "client" ]; then
    RUN_SCRIPT="run_client.sh"
    PORT=${3:-8000} # Default client port often different
fi

echo "[Flow] Mode: $MODE (Script: $RUN_SCRIPT)"

if [ ! -f "$APP_DIR/$RUN_SCRIPT" ]; then
    echo "Error: '$APP_DIR/$RUN_SCRIPT' not found."
    exit 1
fi

if [ -z "$CUSTOM_VENV_PATH" ]; then
    # Default to app-specific venv to allow concurrent execution
    export CUSTOM_VENV_PATH="/tmp/venv_${APP_NAME}"
fi

# Auto-detect ROOT_PATH from VS Code / Jupyter Proxy env
if [ -z "$ROOT_PATH" ] && [ -n "$VSCODE_PROXY_URI" ]; then
    # VSCODE_PROXY_URI example: http://host:port/proxy/{{port}}/
    # 1. Strip protocol/host (everything up to 3rd slash)
    # 2. Replace {{port}} with actual PORT
    # 3. Strip trailing slash
    DETECTED_PATH=$(echo "$VSCODE_PROXY_URI" | sed -E 's|^https?://[^/]+||' | sed "s/{{port}}/$PORT/g" | sed 's|/$||')
    
    if [ -n "$DETECTED_PATH" ]; then
        export ROOT_PATH="$DETECTED_PATH"
        echo "[Flow] Auto-detected ROOT_PATH from VSCODE_PROXY_URI: $ROOT_PATH"
    fi

# Auto-detect ROOT_PATH from JupyterHub env (Fallback)
elif [ -z "$ROOT_PATH" ] && [ -n "$JUPYTERHUB_SERVICE_PREFIX" ]; then
    # JUPYTERHUB_SERVICE_PREFIX example: /user/test/
    # Target: /user/test/proxy/8001
    
    # Strip trailing slash from prefix just in case, then append proxy/$PORT
    PREFIX_CLEAN=$(echo "$JUPYTERHUB_SERVICE_PREFIX" | sed 's|/$||')
    DETECTED_PATH="$PREFIX_CLEAN/proxy/$PORT"
    
    if [ -n "$DETECTED_PATH" ]; then
        export ROOT_PATH="$DETECTED_PATH"
        echo "[Flow] Auto-detected ROOT_PATH from JUPYTERHUB_SERVICE_PREFIX: $ROOT_PATH"
    fi
fi

# Delegate
cd "$APP_DIR"
bash "$RUN_SCRIPT" "$HOST" "$PORT"
