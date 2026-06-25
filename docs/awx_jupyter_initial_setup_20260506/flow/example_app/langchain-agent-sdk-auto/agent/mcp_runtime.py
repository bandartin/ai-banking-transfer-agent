from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from awx.resources import Mcp, bootstrap_portal_runtime
from fastapi import HTTPException


logger = logging.getLogger("langchain-agent-sdk-auto.agent")
DEFAULT_CACHE_DESCRIPTION = "Local MCP server cache for langchain-agent-sdk-auto"
INFERENCE_RUN_MODES = {"INFERENCE", "INFER_ENV", "CONVERTING"}
TRAINING_RUN_MODES = {"TRAINING", "TRAIN", "LEARNING"}


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_flag(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _is_inference_mode() -> bool:
    return _env("DLP_RUN_MODE").upper() in INFERENCE_RUN_MODES


def _resolve_runtime_mode() -> str:
    run_mode = _env("DLP_RUN_MODE").upper()
    if run_mode in INFERENCE_RUN_MODES:
        return "inference"
    if run_mode in TRAINING_RUN_MODES or _env("TRAINING_JOB_ID") or _env("IS_TRAINING").lower() in {"1", "true", "yes", "on"}:
        return "training"
    if _env("MLDL_PROJ_ID") or _env("FLOW_ID") or _env("MLDL_BASE_URL"):
        return "development"
    return "local"


def _normalize_mcp_endpoint(endpoint: str) -> str:
    raw = endpoint.strip()
    if not raw:
        return ""

    parsed = urlsplit(raw)
    path = parsed.path or ""
    if path in {"", "/"}:
        normalized_path = "/mcp"
    elif path.rstrip("/") == "/mcp":
        normalized_path = "/mcp"
    else:
        normalized_path = path.rstrip("/") or path

    return urlunsplit(
        (parsed.scheme, parsed.netloc, normalized_path, parsed.query, parsed.fragment)
    )


def _resolve_server_endpoint(server: Any) -> str:
    raw_endpoint = getattr(server, "endpoint", "")
    normalized_endpoint = _normalize_mcp_endpoint(raw_endpoint)
    if not normalized_endpoint:
        return ""

    data = getattr(server, "_data", None)
    if isinstance(data, dict):
        data["endpoint"] = normalized_endpoint
    else:
        try:
            setattr(server, "endpoint", normalized_endpoint)
        except Exception:
            pass

    return normalized_endpoint


def _bootstrap_local_mcp_cache_from_env() -> Path | None:
    runtime_mode = _resolve_runtime_mode()
    logger.info("MCP local fallback environment mode: %s", runtime_mode)
    if runtime_mode == "inference":
        logger.info("Skipping MCP local cache bootstrap in inference mode (read-only)")
        return None

    server_url = _normalize_mcp_endpoint(_env("MCP_SERVER_URL"))
    if not server_url:
        return None

    server_name = _env("MCP_SERVER_NAME") or _env("MCP_SERVICE_ID") or "local-mcp"
    payload = [
        {
            "serviceId": server_name,
            "serviceName": server_name,
            "endpoint": server_url,
            "description": DEFAULT_CACHE_DESCRIPTION,
        }
    ]
    try:
        resolver = getattr(Mcp(), "_get_cache_path", None)
        resolved_path = resolver() if callable(resolver) else None
    except Exception:
        resolved_path = None

    if resolved_path is None:
        logger.warning("Skipping MCP local cache bootstrap: SDK cache path is unavailable")
        return None

    path = Path(resolved_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Bootstrapped local MCP cache: %s", path)
        return path
    except OSError as exc:
        logger.warning("Skipping MCP local cache bootstrap at SDK path %s: %s", path, exc)
        return None


def _set_mcp_accept_header(client: Any, accept_header: str) -> bool:
    session = getattr(client, "session", None)
    headers = getattr(session, "headers", None)
    if headers is None:
        return False
    headers["Accept"] = accept_header
    return True


def _configure_mcp_client(client: Any) -> None:
    _set_mcp_accept_header(client, "application/json")


def _discover_mcp_servers():
    cache_path = _bootstrap_local_mcp_cache_from_env()
    if cache_path is not None:
        return Mcp().get(force_refresh=True)

    try:
        servers = Mcp().get()
    except Exception as exc:
        logger.warning("MCP discovery from portal failed: %s", exc)
        servers = []

    if servers:
        return servers

    return servers


def _prefetch_mcp_servers() -> None:
    if not _env_flag("AWX_MCP_PREFETCH", default=True):
        logger.info("MCP prefetch disabled by AWX_MCP_PREFETCH")
        return

    result = bootstrap_portal_runtime(
        prefetch_mcp=True,
        mcp_getter=_discover_mcp_servers,
    )
    logger.info("Portal bootstrap result: %s", result)


def _select_server(servers):
    if not servers:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "MCP_SERVER_NOT_FOUND",
                "message": "No MCP server was discovered. Check portal flow binding or local MCP cache fallback env.",
            },
        )

    preferred_service_id = _env("MCP_SERVICE_ID")
    if preferred_service_id:
        finder = getattr(servers, "find", None)
        if callable(finder):
            matched = finder(lambda item: getattr(item, "id", "") == preferred_service_id)
            if matched is not None:
                return matched
        for item in servers:
            if getattr(item, "id", "") == preferred_service_id:
                return item
        raise HTTPException(
            status_code=400,
            detail={
                "code": "MCP_SERVER_NOT_FOUND",
                "message": "Configured MCP_SERVICE_ID was not found in SDK discovery results.",
            },
        )

    preferred_name = _env("MCP_SERVER_NAME")
    if preferred_name:
        finder = getattr(servers, "find", None)
        if callable(finder):
            matched = finder(
                lambda item: getattr(item, "name", "") == preferred_name
                or getattr(item, "id", "") == preferred_name
            )
            if matched is not None:
                return matched
        for item in servers:
            if getattr(item, "name", "") == preferred_name or getattr(item, "id", "") == preferred_name:
                return item

    return servers[0]
