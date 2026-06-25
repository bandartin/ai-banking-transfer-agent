from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from opentelemetry import trace
import uvicorn
from awx.resources import bootstrap_portal_runtime

from awx.observability.instrumentation.fastapi import (
    instrument_app,
)
from chat_service import _execute_chat
from credential_defaults import DEFAULT_CREDENTIAL_PREFETCH_HINTS
from credential_defaults import DEFAULT_CREDENTIAL_SERVICE_ID
from schemas import ChatRequest

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("fastapi-observability-auto-client")
SERVICE_NAME = "fastapi-observability-auto-client"


def _resolve_solution_id() -> str:
    try:
        from awx.common import config as awx_config

        value = getattr(awx_config, "PLATFORM_CODE", "")
        if isinstance(value, str) and value.strip():
            return value.strip()
    except Exception:
        pass
    return "BUILDER"


def _env_flag(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_service_name() -> str:
    try:
        provider = trace.get_tracer_provider()
        resource = getattr(provider, "resource", None)
        if resource is not None:
            candidate = resource.attributes.get("service.name")
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    except Exception:
        pass
    return SERVICE_NAME

def _prefetch_credentials() -> None:
    if not _env_flag("AWX_CREDENTIAL_PREFETCH", default=True):
        logger.info("Credential prefetch disabled by AWX_CREDENTIAL_PREFETCH")
        return

    result = bootstrap_portal_runtime(
        external_resource_requests=[
            {
                "provider_alias": provider_alias,
                "solution_id": _resolve_solution_id(),
                "service_type_name": service_type_name,
            }
            for provider_alias, service_type_name in DEFAULT_CREDENTIAL_PREFETCH_HINTS
        ],
        credential_requests=[
            {
                "service_id": DEFAULT_CREDENTIAL_SERVICE_ID,
                "provider_alias": provider_alias,
                "service_type_name": service_type_name,
            }
            for provider_alias, service_type_name in DEFAULT_CREDENTIAL_PREFETCH_HINTS
        ],
    )
    logger.info("Portal bootstrap result: %s", result)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=== AWX Observability MCP Client Starting ===")
    logger.info("SERVICE_NAME: %s", _resolve_service_name())
    logger.info("MCP_SERVER_URL: %s", os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8001/mcp/sse"))
    try:
        provider = trace.get_tracer_provider()
        resource = getattr(provider, "resource", None)
        if resource is not None:
            logger.info("OTEL_PROVIDER_RESOURCE_ATTRS: %s", resource.attributes)
    except Exception as exc:  # pragma: no cover - diagnostic only
        logger.warning("Failed to read tracer provider resource attributes: %s", exc)
    yield
    logger.info("=== AWX Observability MCP Client Shutting Down ===")


app = FastAPI(
    title="AWX Observability MCP Client",
    description="AWX observability client with MCP call + OTEL response payload",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

instrument_app(app)

cors_origins = os.getenv("CORS_ALLOW_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in cors_origins if origin.strip()],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/chat", response_model=None)
async def chat(request: ChatRequest) -> dict[str, Any] | StreamingResponse:
    return await _execute_chat(request)


@app.get("/health")
async def health_check() -> dict[str, Any]:
    return {
        "status": "healthy",
        "service_name": _resolve_service_name(),
        "mcp_server_url": os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8001/mcp/sse"),
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
