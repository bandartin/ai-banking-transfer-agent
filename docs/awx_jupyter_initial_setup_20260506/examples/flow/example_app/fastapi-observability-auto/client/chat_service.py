from __future__ import annotations

import json
import os
from time import time
from typing import Any, AsyncIterator
from uuid import uuid4

from awx.observability.session import get_session_id
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from fastmcp import Client as _FastMcpClient

from llm_service import (
    generate_agent_response,
    generate_agent_response_stream,
    generate_freeform_response,
    generate_freeform_response_stream,
)
from mcp_exec import _execute_plan, _mcp_sse_transport
from planner import _resolve_tool_plan as resolve_tool_plan
from schemas import ChatCompletionMessageParam, ChatCompletionRole, ChatRequest
from credential_defaults import (
    DEFAULT_CREDENTIAL_PROVIDER_ALIAS,
    DEFAULT_CREDENTIAL_SERVICE_TYPE_NAME,
)


def _message_role(message: ChatCompletionMessageParam) -> ChatCompletionRole | str:
    if not isinstance(message, dict):
        return ""
    role = message.get("role")
    if isinstance(role, str):
        return role
    return ""


def _message_content_to_text(message: ChatCompletionMessageParam) -> str:
    if not isinstance(message, dict):
        return ""
    content: Any = message.get("content", "")

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)

    return str(content)


def _chat_completion_response(
    *,
    completion_id: str,
    created: int,
    model: str,
    content: str,
) -> dict[str, Any]:
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }


def _sse_json(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _chat_completion_chunk_stream(
    text_stream: AsyncIterator[str],
    *,
    completion_id: str,
    created: int,
    model: str,
) -> AsyncIterator[str]:
    yield _sse_json(
        {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
        }
    )
    async for text in text_stream:
        if not text:
            continue
        yield _sse_json(
            {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
            }
        )
    yield _sse_json(
        {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
    )
    yield "data: [DONE]\n\n"


class ChatCompletionsService:
    """OpenAI-style service surface for chat completion orchestration."""

    def __init__(self, mcp_client_cls: Any | None = None):
        self._mcp_client_cls = mcp_client_cls

    async def create(
        self,
        request: ChatRequest,
    ) -> dict[str, Any] | StreamingResponse:
        model_name = request.model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        completion_id = f"chatcmpl-{uuid4().hex}"
        created = int(time())
        include_stream = bool(request.stream)
        user_input = ""
        if request.message and request.message.strip():
            user_input = request.message.strip()
        else:
            for message in reversed(request.messages):
                if _message_role(message) != "user":
                    continue
                content = _message_content_to_text(message).strip()
                if content:
                    user_input = content
                    break
            if not user_input:
                for message in reversed(request.messages):
                    content = _message_content_to_text(message).strip()
                    if content:
                        user_input = content
                        break
        if not user_input:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "MESSAGE_REQUIRED",
                    "message": "Provide `messages` with user content or `message`.",
                },
            )

        transport = _mcp_sse_transport()
        mcp_client_cls = self._mcp_client_cls or _FastMcpClient
        async with mcp_client_cls(transport) as mcp_client:
            _, plan_steps = await resolve_tool_plan(user_input, mcp_client)

            if include_stream:
                if plan_steps:
                    mcp_add_result, executed_steps = await _execute_plan(plan_steps, mcp_client)
                    text_stream = generate_agent_response_stream(
                        user_input,
                        executed_steps,
                        mcp_add_result,
                        provider_alias=DEFAULT_CREDENTIAL_PROVIDER_ALIAS,
                        service_type_name=DEFAULT_CREDENTIAL_SERVICE_TYPE_NAME,
                    )
                else:
                    text_stream = generate_freeform_response_stream(
                        user_input,
                        provider_alias=DEFAULT_CREDENTIAL_PROVIDER_ALIAS,
                        service_type_name=DEFAULT_CREDENTIAL_SERVICE_TYPE_NAME,
                    )
                session_id = get_session_id()
                return _build_streaming_response(
                    text_stream,
                    session_id=session_id,
                    completion_id=completion_id,
                    created=created,
                    model=str(model_name),
                )

            if plan_steps:
                mcp_add_result, executed_steps = await _execute_plan(plan_steps, mcp_client)
                agent_response = await generate_agent_response(
                    user_input,
                    executed_steps,
                    mcp_add_result,
                    provider_alias=DEFAULT_CREDENTIAL_PROVIDER_ALIAS,
                    service_type_name=DEFAULT_CREDENTIAL_SERVICE_TYPE_NAME,
                )
            else:
                agent_response = await generate_freeform_response(
                    user_input,
                    provider_alias=DEFAULT_CREDENTIAL_PROVIDER_ALIAS,
                    service_type_name=DEFAULT_CREDENTIAL_SERVICE_TYPE_NAME,
                )

            response_payload = _chat_completion_response(
                completion_id=completion_id,
                created=created,
                model=str(model_name),
                content=agent_response,
            )

        return response_payload

async def _execute_chat(
    request: ChatRequest,
) -> dict[str, Any] | StreamingResponse:
    service = ChatCompletionsService(mcp_client_cls=_FastMcpClient)
    return await service.create(request)


def _build_streaming_response(
    text_stream: AsyncIterator[str],
    *,
    session_id: str | None,
    completion_id: str,
    created: int,
    model: str,
) -> StreamingResponse:
    headers: dict[str, str] = {}
    if session_id:
        headers["X-AWX-Session-Id"] = str(session_id)
    return StreamingResponse(
        _chat_completion_chunk_stream(
            text_stream,
            completion_id=completion_id,
            created=created,
            model=model,
        ),
        media_type="text/event-stream; charset=utf-8",
        headers=headers,
    )
