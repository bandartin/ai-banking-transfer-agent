from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Any

from awx.resources import Mcp, bootstrap_portal_runtime


logger = logging.getLogger("flow.awx-bootstrap")

ROOT_DIR = Path(__file__).resolve().parent
APP_DIR = ROOT_DIR / "example_app"
LIST_FIELDS = ("credentials", "external_resources", "prompts")
BOOL_FIELDS = ("prefetch_mcp", "mcp_env_fallback")
MCP_CACHE_FILE = ROOT_DIR / "mcp_info.json"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap AWX SDK cache artifacts for a flow example app.")
    parser.add_argument("--app-name", required=True)
    parser.add_argument("--mode", default="server")
    return parser.parse_args()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON manifest: {path}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError(f"Bootstrap manifest must be an object: {path}")
    return raw


def _manifest_paths(app_name: str, mode: str) -> list[Path]:
    app_root = APP_DIR / app_name
    paths = [app_root / "awx-bootstrap.json"]
    mode_dir = app_root / mode
    if mode_dir.is_dir():
        paths.append(mode_dir / "awx-bootstrap.json")
    return [path for path in paths if path.exists()]


def _resolve_project_id(request: dict[str, Any]) -> dict[str, Any]:
    if request.get("project_id"):
        return dict(request)
    project_id = os.getenv("MLDL_PROJ_ID", "").strip()
    if not project_id:
        return dict(request)
    return {**dict(request), "project_id": project_id}


def _load_manifest(app_name: str, mode: str) -> dict[str, Any]:
    merged: dict[str, Any] = {field: [] for field in LIST_FIELDS}
    for field in BOOL_FIELDS:
        merged[field] = False

    for path in _manifest_paths(app_name, mode):
        manifest = _load_json(path)
        for field in LIST_FIELDS:
            values = manifest.get(field, [])
            if isinstance(values, list):
                if field == "prompts":
                    merged[field].extend(_resolve_project_id(item) for item in values if isinstance(item, dict))
                else:
                    merged[field].extend(item for item in values if isinstance(item, dict))
        for field in BOOL_FIELDS:
            if field in manifest:
                merged[field] = bool(manifest[field])
    return merged


def _normalize_mcp_endpoint(endpoint: str) -> str:
    value = endpoint.strip()
    if not value:
        return ""
    if value.endswith("/mcp") or value.endswith("/mcp/"):
        return value.rstrip("/")
    if value.endswith("/mcp/sse") or value.endswith("/sse"):
        return value.rsplit("/", 1)[0]
    return value.rstrip("/") + "/mcp"


def _bootstrap_local_mcp_cache_from_env() -> list[dict[str, str]] | None:
    server_url = _normalize_mcp_endpoint(os.getenv("MCP_SERVER_URL", ""))
    if not server_url:
        return None

    server_name = (
        os.getenv("MCP_SERVER_NAME", "").strip()
        or os.getenv("MCP_SERVICE_ID", "").strip()
        or "local-mcp"
    )
    payload = [
        {
            "serviceId": server_name,
            "serviceName": server_name,
            "endpoint": server_url,
            "description": "Local MCP server cache bootstrapped by flow launcher",
        }
    ]
    cache_path_getter = getattr(Mcp(), "_get_cache_path", None)
    cache_path = cache_path_getter() if callable(cache_path_getter) else MCP_CACHE_FILE
    cache_path = Path(cache_path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def _mcp_getter(*, env_fallback: bool):
    try:
        return Mcp().get()
    except Exception:
        if env_fallback:
            payload = _bootstrap_local_mcp_cache_from_env()
            if payload is not None:
                return payload
        raise


def bootstrap_awx_sdk_artifacts(*, app_name: str, mode: str) -> bool:
    manifest = _load_manifest(app_name, mode)
    has_work = any(manifest[field] for field in LIST_FIELDS) or manifest["prefetch_mcp"]
    if not has_work:
        logger.info("No AWX bootstrap manifest for %s[%s]", app_name, mode)
        return False

    bootstrap_portal_runtime(
        credential_requests=manifest["credentials"],
        external_resource_requests=manifest["external_resources"],
        prompt_requests=manifest["prompts"],
        prefetch_mcp=manifest["prefetch_mcp"],
        mcp_getter=(lambda: _mcp_getter(env_fallback=manifest["mcp_env_fallback"]))
        if manifest["prefetch_mcp"]
        else None,
        raise_on_error=True,
    )
    return True


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[Flow] %(message)s")
    args = _parse_args()
    try:
        did_bootstrap = bootstrap_awx_sdk_artifacts(app_name=args.app_name, mode=args.mode)
    except Exception as exc:
        logger.warning(
            "AWX SDK artifact bootstrap failed for %s[%s]: %s",
            args.app_name,
            args.mode,
            exc,
        )
        return 1

    if did_bootstrap:
        logger.info("AWX SDK artifacts bootstrapped for %s[%s]", args.app_name, args.mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
