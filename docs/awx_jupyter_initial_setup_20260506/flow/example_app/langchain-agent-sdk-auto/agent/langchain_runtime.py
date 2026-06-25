from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from awx.resources import Credential, bootstrap_portal_runtime
from fastapi import HTTPException
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, create_model


logger = logging.getLogger("langchain-agent-sdk-auto.agent")
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_CREDENTIAL_SERVICE_ID = 30
DEFAULT_CREDENTIAL_PROVIDER_ALIAS = "OpenAI"
DEFAULT_CREDENTIAL_SERVICE_TYPE = "LLM"


def _extract_openai_api_key_from_credential(credential: Any) -> str | None:
    selected = credential
    if isinstance(selected, list):
        find_and_cache = getattr(selected, "find_and_cache", None)
        if callable(find_and_cache):
            selected = find_and_cache(lambda _item: True)
        elif selected:
            selected = selected[0]

    if not isinstance(selected, dict):
        return None

    direct_value = selected.get("OPENAI_API_KEY")
    if isinstance(direct_value, str) and direct_value.strip():
        return direct_value.strip()

    variables = selected.get("variables")
    if not isinstance(variables, list):
        return None

    fallback: str | None = None
    for item in variables:
        if not isinstance(item, dict):
            continue
        name = item.get("attributeName") or item.get("name")
        value = item.get("attributeValue") or item.get("value") or item.get("secret")
        if not isinstance(value, str) or not value.strip():
            continue
        resolved = value.strip()
        if isinstance(name, str) and name.strip().upper() == "OPENAI_API_KEY":
            return resolved
        if fallback is None:
            fallback = resolved
    return fallback


def _resolve_openai_api_key() -> tuple[str, str]:
    try:
        credential = Credential().get(
            service_id=DEFAULT_CREDENTIAL_SERVICE_ID,
            provider_alias=DEFAULT_CREDENTIAL_PROVIDER_ALIAS,
            service_type_name=DEFAULT_CREDENTIAL_SERVICE_TYPE,
        )
        resolved = _extract_openai_api_key_from_credential(credential)
        if resolved:
            return resolved, "credential"
    except Exception as exc:
        logger.warning("Credential lookup failed: %s", exc)

    raise HTTPException(
        status_code=400,
        detail={
            "code": "OPENAI_API_KEY_MISSING",
            "message": "OpenAI key was not resolved from Credential.get().",
        },
    )


def _prefetch_credentials() -> None:
    result = bootstrap_portal_runtime(
        credential_requests=[
            {
                "service_id": DEFAULT_CREDENTIAL_SERVICE_ID,
                "provider_alias": DEFAULT_CREDENTIAL_PROVIDER_ALIAS,
                "service_type_name": DEFAULT_CREDENTIAL_SERVICE_TYPE,
            }
        ]
    )
    logger.info("Portal bootstrap result: %s", result)


def _schema_type_to_python(schema_type: str | None):
    return {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }.get(schema_type or "string", str)


def _build_args_model(tool_name: str, input_schema: dict[str, Any]) -> type[BaseModel]:
    properties = input_schema.get("properties") or {}
    required = set(input_schema.get("required") or [])
    fields: dict[str, tuple[Any, Any]] = {}

    for field_name, spec in properties.items():
        if not isinstance(spec, dict):
            spec = {}
        field_type = _schema_type_to_python(spec.get("type"))
        description = spec.get("description", "")
        default = ... if field_name in required else None
        fields[field_name] = (field_type, Field(default=default, description=description))

    if not fields:
        fields["payload"] = (dict[str, Any], Field(default_factory=dict, description="Tool payload"))

    model_name = f"{tool_name.title().replace('_', '')}Args"
    return create_model(model_name, **fields)


async def _build_langchain_tools(
    *,
    mcp_client: Any,
    tool_schemas: list[dict[str, Any]],
) -> list[StructuredTool]:
    tools: list[StructuredTool] = []

    for tool_schema in tool_schemas:
        if not isinstance(tool_schema, dict):
            continue
        tool_name = tool_schema.get("name")
        if not tool_name:
            continue

        description = tool_schema.get("description", "")
        input_schema = tool_schema.get("inputSchema") or {"type": "object", "properties": {}}
        args_model = _build_args_model(tool_name, input_schema)

        async def _run_tool(_tool_name=tool_name, **kwargs):
            result = await asyncio.to_thread(mcp_client.call_tool, _tool_name, kwargs)
            return json.dumps(result, ensure_ascii=False, default=str)

        tools.append(
            StructuredTool.from_function(
                name=tool_name,
                description=description,
                args_schema=args_model,
                coroutine=_run_tool,
                func=None,
            )
        )

    return tools


def _build_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are a concise Korean tool-calling assistant. Use available MCP tools when needed. Answer in Korean.",
            ),
            ("human", "{input}"),
            MessagesPlaceholder("agent_scratchpad"),
        ]
    )
