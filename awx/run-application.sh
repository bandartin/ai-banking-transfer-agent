#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$SCRIPT_DIR"

export ENVIRONMENT="${ENVIRONMENT:-prod}"
export FLASK_ENV="${FLASK_ENV:-production}"
export FLASK_PORT="${FLASK_PORT:-8000}"
export AWX_CREDENTIAL_SERVICE_ID="${AWX_CREDENTIAL_SERVICE_ID:-30}"
export AWX_CREDENTIAL_PROVIDER_ALIAS="${AWX_CREDENTIAL_PROVIDER_ALIAS:-OpenAI}"
export AWX_CREDENTIAL_SERVICE_TYPE_NAME="${AWX_CREDENTIAL_SERVICE_TYPE_NAME:-LLM}"
export AWX_CREDENTIAL_VARIABLE_NAME="${AWX_CREDENTIAL_VARIABLE_NAME:-OPENAI_API_KEY}"
export AWX_EXTERNAL_RESOURCE_SOLUTION_ID="${AWX_EXTERNAL_RESOURCE_SOLUTION_ID:-BUILDER}"

PATH_TEMP_DEFAULT="${PATH_TEMP:-${PATH_INFER_ENV:-/tmp}}"
mkdir -p "$PATH_TEMP_DEFAULT"

export DATABASE_URL="${DATABASE_URL:-sqlite:///$PATH_TEMP_DEFAULT/banking_demo.db}"
export CHECKPOINT_DB_PATH="${CHECKPOINT_DB_PATH:-$PATH_TEMP_DEFAULT/banking_checkpoints.db}"

bootstrap_awx_resources() {
    if [ ! -f "$SCRIPT_DIR/awx-bootstrap.json" ]; then
        return 0
    fi

    python - <<'PY'
import json
from pathlib import Path

manifest_path = Path("awx-bootstrap.json")
try:
    from awx.resources import bootstrap_portal_runtime
except Exception as exc:
    print(f"[AWX] SDK bootstrap skipped: {exc}")
    raise SystemExit(0)

try:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    bootstrap_portal_runtime(
        credential_requests=manifest.get("credentials", []),
        external_resource_requests=manifest.get("external_resources", []),
        prompt_requests=manifest.get("prompts", []),
        prefetch_mcp=bool(manifest.get("prefetch_mcp", False)),
    )
    print("[AWX] Portal runtime resources bootstrapped.")
except Exception as exc:
    print(f"[AWX] Portal bootstrap failed; continuing with app fallback: {exc}")
PY
}

bootstrap_awx_resources

echo "[AWX] Starting Banking Transfer Agent on 0.0.0.0:${FLASK_PORT}"

UV_BIN="${UV_BIN:-uv}"
if command -v "$UV_BIN" >/dev/null 2>&1; then
    export UV_CACHE_DIR="${UV_CACHE_DIR:-$PATH_TEMP_DEFAULT/uv-cache}"
    export UV_PROJECT_ENVIRONMENT="${CUSTOM_VENV_PATH:-$PATH_TEMP_DEFAULT/venv-banking-transfer-agent}"
    "$UV_BIN" venv --allow-existing --system-site-packages "$UV_PROJECT_ENVIRONMENT" >/dev/null
    "$UV_BIN" sync --no-install-project --inexact

    if "$UV_BIN" run --no-sync opentelemetry-instrument --help >/dev/null 2>&1; then
        exec "$UV_BIN" run --no-sync opentelemetry-instrument python app.py
    fi

    exec "$UV_BIN" run --no-sync python app.py
fi

if command -v opentelemetry-instrument >/dev/null 2>&1; then
    exec opentelemetry-instrument python app.py
fi

exec python app.py
