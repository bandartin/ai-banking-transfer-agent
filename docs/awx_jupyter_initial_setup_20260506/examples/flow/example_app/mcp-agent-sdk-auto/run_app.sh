#!/bin/bash
HOST=${1:-0.0.0.0}
PORT=${2:-}
UV_BIN=${3:-uv}
MODE=${APP_MODE:-server}

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$SCRIPT_DIR"

if [ -f .env ]; then
    set -a
    . ./.env
    set +a
fi

TARGET_DIR=""
case "$MODE" in
    agent) TARGET_DIR="agent" ;;
    server) TARGET_DIR="server" ;;
    *)
        echo "[mcp-agent-sdk-auto] Unsupported mode: $MODE"
        echo "[mcp-agent-sdk-auto] Available modes: agent, server"
        exit 1
        ;;
esac

if [ -z "$PORT" ]; then
    case "$TARGET_DIR" in
        agent) PORT=8000 ;;
        server) PORT=8001 ;;
    esac
fi

cd "$TARGET_DIR"
if [ "$TARGET_DIR" = "agent" ]; then
    bash run_agent.sh "$HOST" "$PORT" "$UV_BIN"
else
    bash run_server.sh "$HOST" "$PORT" "$UV_BIN"
fi
