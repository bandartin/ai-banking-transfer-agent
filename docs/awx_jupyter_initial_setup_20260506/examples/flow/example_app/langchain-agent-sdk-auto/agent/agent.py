from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from awx.resources import Credential, Mcp, bootstrap_portal_runtime
from awx.observability.instrumentation.fastapi import instrument_app
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from langchain_openai import ChatOpenAI
from opentelemetry import trace
from pydantic import BaseModel, Field

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

import langchain_runtime
import mcp_runtime

try:
    from langchain.agents import AgentExecutor, create_tool_calling_agent
except ImportError:
    AgentExecutor = None
    create_tool_calling_agent = None
    from langchain.agents import create_agent
else:
    create_agent = None

DEFAULT_OPENAI_MODEL = langchain_runtime.DEFAULT_OPENAI_MODEL
SERVICE_NAME = "langchain-agent-sdk-auto.agent"


load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("langchain-agent-sdk-auto.agent")


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    model: str | None = None
    max_steps: int = Field(default=4, ge=1, le=8)


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _normalize_mcp_endpoint(endpoint: str) -> str:
    return mcp_runtime._normalize_mcp_endpoint(endpoint)


def _bootstrap_local_mcp_cache_from_env():
    return mcp_runtime._bootstrap_local_mcp_cache_from_env()


def _extract_openai_api_key_from_credential(credential: Any) -> str | None:
    return langchain_runtime._extract_openai_api_key_from_credential(credential)


def _resolve_openai_api_key() -> tuple[str, str]:
    langchain_runtime.Credential = Credential
    langchain_runtime.HTTPException = HTTPException
    return langchain_runtime._resolve_openai_api_key()


def _prefetch_credentials() -> None:
    langchain_runtime.bootstrap_portal_runtime = bootstrap_portal_runtime
    langchain_runtime.Credential = Credential
    langchain_runtime.HTTPException = HTTPException
    return langchain_runtime._prefetch_credentials()


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


def _log_otel_endpoints() -> None:
    logger.info("OTEL traces endpoint: %s", _env("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"))
    logger.info("OTEL logs endpoint: %s", _env("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT"))
    logger.info("OTEL metrics endpoint: %s", _env("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT"))


def _trace_id() -> str:
    span = trace.get_current_span()
    context = span.get_span_context()
    return f"{context.trace_id:032x}" if context is not None and context.is_valid else ""


def _resolve_server_endpoint(server: Any) -> str:
    return mcp_runtime._resolve_server_endpoint(server)


def _configure_mcp_client(client: Any) -> None:
    return mcp_runtime._configure_mcp_client(client)


def _discover_mcp_servers():
    mcp_runtime.Mcp = Mcp
    return mcp_runtime._discover_mcp_servers()


def _prefetch_mcp_servers() -> None:
    mcp_runtime.Mcp = Mcp
    mcp_runtime.bootstrap_portal_runtime = bootstrap_portal_runtime
    return mcp_runtime._prefetch_mcp_servers()


def _select_server(servers):
    return mcp_runtime._select_server(servers)


async def _build_langchain_tools(*, mcp_client: Any, tool_schemas: list[dict[str, Any]]):
    return await langchain_runtime._build_langchain_tools(
        mcp_client=mcp_client,
        tool_schemas=tool_schemas,
    )


def _build_prompt():
    return langchain_runtime._build_prompt()


def _extract_response_text_from_agent_state(result: dict[str, Any]) -> str:
    messages = result.get("messages")
    if not isinstance(messages, list):
        return ""

    for item in reversed(messages):
        message_type = getattr(item, "type", "")
        message_content = getattr(item, "content", "")
        if message_type == "ai":
            return message_content if isinstance(message_content, str) else str(message_content)

        if isinstance(item, dict):
            role = item.get("role")
            content = item.get("content", "")
            if role == "assistant":
                return content if isinstance(content, str) else str(content)

    return ""


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=== LangChain Agent SDK Auto Starting ===")
    logger.info("SERVICE_NAME: %s", _resolve_service_name())
    _log_otel_endpoints()
    yield
    logger.info("=== LangChain Agent SDK Auto Shutting Down ===")


async def run_agent_turn(message: str, *, model: str | None = None, max_steps: int = 4) -> dict[str, Any]:
    discovered_servers = await asyncio.to_thread(_discover_mcp_servers)
    selected_server = _select_server(discovered_servers)
    resolved_endpoint = _resolve_server_endpoint(selected_server)
    mcp_client = selected_server.get_client()
    _configure_mcp_client(mcp_client)

    tool_schemas = await asyncio.to_thread(mcp_client.list_tools)
    langchain_tools = await _build_langchain_tools(
        mcp_client=mcp_client,
        tool_schemas=tool_schemas,
    )

    api_key, auth_source = _resolve_openai_api_key()
    resolved_model = model or _env("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
    llm = ChatOpenAI(api_key=api_key, model=resolved_model, temperature=0.0)
    if create_tool_calling_agent is not None and AgentExecutor is not None:
        prompt = _build_prompt()
        agent = create_tool_calling_agent(llm, langchain_tools, prompt)
        executor = AgentExecutor(
            agent=agent,
            tools=langchain_tools,
            verbose=False,
            max_iterations=max_steps,
        )
        result = await executor.ainvoke({"input": message})
        response_text = result.get("output", "")
    else:
        agent = create_agent(
            model=llm,
            tools=langchain_tools,
            system_prompt="You are a concise Korean tool-calling assistant. Use available MCP tools when needed. Answer in Korean.",
        )
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": message}]},
            config={"recursion_limit": max_steps * 2 + 1},
        )
        response_text = _extract_response_text_from_agent_state(result)

    trace_id = _trace_id()
    print(f"trace_id={trace_id}", flush=True)

    return {
        "response": response_text,
        "trace_id": trace_id,
        "auth_source": auth_source,
        "execution_mode": "langchain_tool_calling_agent",
        "configured_server": {
            "id": getattr(selected_server, "id", ""),
            "name": getattr(selected_server, "name", ""),
            "endpoint": resolved_endpoint,
        },
        "discovered_tools": [
            tool.get("name") for tool in tool_schemas if isinstance(tool, dict) and tool.get("name")
        ],
    }


app = FastAPI(
    title="LangChain Agent SDK Auto",
    description="AWX SDK MCP discovery + LangChain tool-calling agent example",
    version="0.1.0",
    lifespan=lifespan,
)
instrument_app(app)


@app.get("/")
async def root() -> dict[str, Any]:
    return {
        "service_name": _resolve_service_name(),
        "message": "Use /chat to run the LangChain tool-calling Agent.",
        "endpoints": {
            "chat": "/chat",
            "mcp_servers": "/mcp/servers",
            "health": "/health",
        },
    }


@app.get("/health")
async def health_check() -> dict[str, Any]:
    return {
        "status": "healthy",
        "service_name": _resolve_service_name(),
    }


@app.get("/mcp/servers")
async def list_mcp_servers() -> dict[str, Any]:
    servers = await asyncio.to_thread(_discover_mcp_servers)
    return {
        "count": len(servers),
        "items": [
            {
                "id": getattr(item, "id", ""),
                "name": getattr(item, "name", ""),
                "endpoint": getattr(item, "endpoint", ""),
            }
            for item in servers
        ],
    }


@app.post("/chat")
async def chat(request: ChatRequest) -> dict[str, Any]:
    return await run_agent_turn(
        request.message,
        model=request.model,
        max_steps=request.max_steps,
    )
