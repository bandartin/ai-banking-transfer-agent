#!/bin/bash
set -eu

APP_NAME_INPUT="${1:-${APP_NAME:-}}"
VENV_ROOT="${VENV_ROOT:-/workspace/.venv}"

if [ -z "$APP_NAME_INPUT" ]; then
    echo "APP_NAME is required" >&2
    exit 1
fi

printf '%s/example_app/%s\n' "$VENV_ROOT" "$APP_NAME_INPUT"
