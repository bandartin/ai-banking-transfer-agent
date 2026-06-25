from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from awx.resources import Credential, Mcp, bootstrap_portal_runtime
from awx.observability.instrumentation.fastapi import instrument_app
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from openai import AsyncOpenAI
from opentelemetry import trace
from pydantic import BaseModel, Field

import mcp_runtime
import openai_runtime
import telemetry

DEFAULT_OPENAI_MODEL = openai_runtime.DEFAULT_OPENAI_MODEL


load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("mcp-agent-sdk-auto.agent")


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


def _trace_mcp_operation(*args, **kwargs):
    telemetry.trace = trace
    return telemetry._trace_mcp_operation(*args, **kwargs)


def _extract_openai_api_key_from_credential(credential: Any) -> str | None:
    return openai_runtime._extract_openai_api_key_from_credential(credential)


def _resolve_openai_api_key() -> tuple[str, str]:
    openai_runtime.Credential = Credential
    openai_runtime.HTTPException = HTTPException
    return openai_runtime._resolve_openai_api_key()


def _prefetch_credentials() -> None:
    openai_runtime.bootstrap_portal_runtime = bootstrap_portal_runtime
    openai_runtime.Credential = Credential
    openai_runtime.HTTPException = HTTPException
    return openai_runtime._prefetch_credentials()


def _resolve_service_name() -> str:
    telemetry.trace = trace
    return telemetry._resolve_service_name()


def _trace_id() -> str:
    telemetry.trace = trace
    return telemetry._trace_id()


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
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=== MCP Agent SDK Auto Starting ===")
    logger.info("SERVICE_NAME: %s", _resolve_service_name())
    yield
    logger.info("=== MCP Agent SDK Auto Shutting Down ===")


def _tool_schema_to_openai(tool: dict[str, Any]) -> dict[str, Any]:
    input_schema = tool.get("inputSchema") or {
        "type": "object",
        "properties": {},
    }
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": input_schema,
        },
    }


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return "" if content is None else str(content)


def _extract_tool_calls(message: Any) -> list[dict[str, Any]]:
    tool_calls = getattr(message, "tool_calls", None) or []
    parsed: list[dict[str, Any]] = []
    for item in tool_calls:
        function = getattr(item, "function", None)
        name = getattr(function, "name", "") or ""
        raw_arguments = getattr(function, "arguments", "{}") or "{}"
        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError:
            arguments = {}
        parsed.append(
            {
                "id": getattr(item, "id", name or "tool-call"),
                "name": name,
                "raw_arguments": raw_arguments,
                "arguments": arguments,
            }
        )
    return parsed


def _assistant_message_payload(content: str, tool_calls: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": content,
        "tool_calls": [
            {
                "id": item["id"],
                "type": "function",
                "function": {
                    "name": item["name"],
                    "arguments": item["raw_arguments"],
                },
            }
            for item in tool_calls
        ],
    }


async def run_agent_turn(message: str, *, model: str | None = None, max_steps: int = 4) -> dict[str, Any]:
    discovered_servers = await asyncio.to_thread(_discover_mcp_servers)
    selected_server = _select_server(discovered_servers)
    resolved_endpoint = _resolve_server_endpoint(selected_server)
    mcp_client = selected_server.get_client()
    _configure_mcp_client(mcp_client)

    tools = await asyncio.to_thread(
        _trace_mcp_operation,
        "tools.list",
        server_name=getattr(selected_server, "name", ""),
        endpoint=resolved_endpoint,
        func=mcp_client.list_tools,
    )

    openai_tools = [_tool_schema_to_openai(tool) for tool in tools if isinstance(tool, dict) and tool.get("name")]
    api_key, auth_source = _resolve_openai_api_key()
    openai_client = AsyncOpenAI(api_key=api_key)
    resolved_model = model or _env("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)

    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are a concise Korean tool-calling assistant. "
                "Use provided tools when arithmetic is needed. "
                "This is not a planner flow. Answer in Korean."
            ),
        },
        {"role": "user", "content": message},
    ]
    executed_tool_calls: list[dict[str, Any]] = []
    final_response = ""

    for _ in range(max_steps):
        llm_response = await openai_client.chat.completions.create(
            model=resolved_model,
            temperature=0.0,
            messages=messages,
            tools=openai_tools or None,
            tool_choice="auto" if openai_tools else None,
        )
        assistant_message = llm_response.choices[0].message
        assistant_content = _content_to_text(getattr(assistant_message, "content", ""))
        tool_calls = _extract_tool_calls(assistant_message)

        if not tool_calls:
            final_response = assistant_content
            break

        messages.append(_assistant_message_payload(assistant_content, tool_calls))

        for tool_call in tool_calls:
            result = await asyncio.to_thread(
                _trace_mcp_operation,
                "tools.call",
                server_name=getattr(selected_server, "name", ""),
                endpoint=resolved_endpoint,
                tool_name=tool_call["name"],
                func=lambda current_tool=tool_call: mcp_client.call_tool(
                    current_tool["name"],
                    current_tool["arguments"],
                ),
            )
            executed_tool_calls.append(
                {
                    "tool_name": tool_call["name"],
                    "arguments": tool_call["arguments"],
                    "result": result,
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

    if not final_response and executed_tool_calls:
        final_response = json.dumps(executed_tool_calls[-1]["result"], ensure_ascii=False)

    trace_id = _trace_id()
    print(f"trace_id={trace_id}", flush=True)

    return {
        "response": final_response,
        "trace_id": trace_id,
        "auth_source": auth_source,
        "selected_server": {
            "id": getattr(selected_server, "id", ""),
            "name": getattr(selected_server, "name", ""),
            "endpoint": resolved_endpoint,
        },
        "discovered_tools": [tool.get("name") for tool in tools if isinstance(tool, dict) and tool.get("name")],
        "tool_calls": executed_tool_calls,
    }


app = FastAPI(
    title="MCP Agent SDK Auto",
    description="AWX SDK MCP discovery + OpenAI tool-calling agent example",
    version="0.1.0",
    lifespan=lifespan,
)
instrument_app(app)


@app.get("/")
async def root() -> dict[str, Any]:
    return {
        "service_name": _resolve_service_name(),
        "message": "Use /chat to run the tool-calling Agent.",
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
