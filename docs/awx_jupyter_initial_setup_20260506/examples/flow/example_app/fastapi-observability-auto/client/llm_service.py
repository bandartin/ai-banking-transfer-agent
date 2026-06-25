from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, AsyncIterator, Sequence

from awx.resources import Credential
from fastapi import HTTPException
from openai import AsyncOpenAI

from credential_defaults import DEFAULT_CREDENTIAL_SERVICE_ID


@dataclass(slots=True)
class _InvokeResult:
    content: str
    raw: Any | None = None


class OpenAIChatCompletionsAdapter:
    """Compatibility adapter with LangChain-like `ainvoke/astream` on top of OpenAI SDK."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        temperature: float = 0.0,
        streaming: bool = False,
        client: AsyncOpenAI | None = None,
    ):
        self.model = model
        self.temperature = temperature
        self.streaming = streaming
        if client is None and not api_key:
            raise ValueError("api_key is required when client is not provided")
        self._client = client or AsyncOpenAI(api_key=api_key)

    async def ainvoke(self, messages: Sequence[Any]) -> _InvokeResult:
        payload_messages = _to_openai_messages(messages)
        response = await self._client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            messages=payload_messages,
        )
        return _InvokeResult(content=_completion_to_text(response), raw=response)

    async def astream(self, messages: Sequence[Any]) -> AsyncIterator[str]:
        payload_messages = _to_openai_messages(messages)
        stream = await self._client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            messages=payload_messages,
            stream=True,
        )
        async for chunk in stream:
            text = _chunk_to_delta_text(chunk)
            if text:
                yield text


def _require_non_empty(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required.")
    return normalized


def _extract_openai_api_key_from_credential(
    credential: Any,
    *,
    preferred_variable_name: str = "OPENAI_API_KEY",
) -> str | None:
    selected = credential
    if isinstance(selected, list):
        find_and_cache = getattr(selected, "find_and_cache", None)
        if callable(find_and_cache):
            selected = find_and_cache(lambda _item: True)
        elif selected:
            selected = selected[0]

    if not isinstance(selected, dict):
        return None

    direct_value = selected.get(preferred_variable_name)
    if isinstance(direct_value, str) and direct_value.strip():
        return direct_value.strip()

    for field in ("api_key", "token", "value", "secret"):
        raw = selected.get(field)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()

    variables = selected.get("variables")
    if not isinstance(variables, list):
        return None

    preferred_upper = preferred_variable_name.upper()
    fallback_value: str | None = None
    for item in variables:
        if not isinstance(item, dict):
            continue
        name = item.get("attributeName") or item.get("name")
        value = item.get("attributeValue") or item.get("value") or item.get("secret")
        if isinstance(value, str) and value.strip():
            resolved = value.strip()
            if isinstance(name, str) and name.strip().upper() == preferred_upper:
                return resolved
            if fallback_value is None:
                fallback_value = resolved
    return fallback_value


def resolve_openai_api_key(
    *,
    provider_alias: str,
    service_type_name: str,
) -> str | None:
    provider_alias = _require_non_empty(provider_alias, "provider_alias")
    service_type_name = _require_non_empty(service_type_name, "service_type_name")

    try:
        credential_client = Credential()  # noqa: SLF001
    except Exception:
        return None

    try:
        credential = credential_client.get(
            service_id=DEFAULT_CREDENTIAL_SERVICE_ID,
            provider_alias=provider_alias,
            service_type_name=service_type_name,
        )
    except Exception:
        return None

    resolved: str | None = None
    if hasattr(credential_client, "extract_secret_value"):
        try:
            extracted = credential_client.extract_secret_value(
                credential,
                preferred_variable_name="OPENAI_API_KEY",
            )
            if isinstance(extracted, str) and extracted.strip():
                resolved = extracted.strip()
        except Exception:
            resolved = None

    if not resolved:
        resolved = _extract_openai_api_key_from_credential(
            credential,
            preferred_variable_name="OPENAI_API_KEY",
        )
    if isinstance(resolved, str) and resolved.strip():
        return resolved.strip()
    return None


def build_llm_client(
    temperature: float = 0.0,
    *,
    provider_alias: str,
    service_type_name: str,
    streaming: bool = False,
    api_key: str | None = None,
    client: AsyncOpenAI | None = None,
    model: str | None = None,
):
    resolved_client = client
    resolved_model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    resolved_api_key = api_key
    if resolved_api_key is None and resolved_client is None:
        resolved_api_key = resolve_openai_api_key(
            provider_alias=provider_alias,
            service_type_name=service_type_name,
        )
    if resolved_client is None and not resolved_api_key:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "OPENAI_API_KEY_MISSING",
                "message": "OpenAI API key is required via awx.resources.Credential.get().",
            },
        )

    return OpenAIChatCompletionsAdapter(
        model=resolved_model,
        temperature=temperature,
        api_key=resolved_api_key,
        client=resolved_client,
        streaming=streaming,
    )


def require_openai_api_key(
    *,
    provider_alias: str,
    service_type_name: str,
) -> str:
    api_key = resolve_openai_api_key(
        provider_alias=provider_alias,
        service_type_name=service_type_name,
    )
    if api_key:
        return api_key
    raise HTTPException(
        status_code=400,
        detail={
            "code": "OPENAI_API_KEY_MISSING",
            "message": "OpenAI API key is required via awx.resources.Credential.get().",
        },
    )


async def generate_agent_response(
    message: str,
    executed_steps: list[dict[str, Any]],
    final_result: Any,
    *,
    provider_alias: str,
    service_type_name: str,
    api_key: str | None = None,
) -> str:
    if api_key is None:
        llm = build_llm_client(
            temperature=0.0,
            provider_alias=provider_alias,
            service_type_name=service_type_name,
        )
    else:
        llm = build_llm_client(
            temperature=0.0,
            provider_alias=provider_alias,
            service_type_name=service_type_name,
            api_key=api_key,
        )
    if llm is None:
        if final_result is None:
            return "Operation is invalid."
        return f"Result: {final_result}"
    system_prompt = (
        "You are an agent. Provide the final answer to the user based on the tool results. "
        "If the final_result is null, explain that the operation is invalid (e.g., division by zero). "
        "Be concise."
    )
    user_payload = {
        "message": message,
        "tool_steps": executed_steps,
        "final_result": final_result,
    }

    response = await llm.ainvoke(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload)},
        ]
    )
    content = response.content if hasattr(response, "content") else str(response)
    return str(content)


async def generate_freeform_response(
    message: str,
    *,
    provider_alias: str,
    service_type_name: str,
    api_key: str | None = None,
) -> str:
    if api_key is None:
        llm = build_llm_client(
            temperature=0.0,
            provider_alias=provider_alias,
            service_type_name=service_type_name,
        )
    else:
        llm = build_llm_client(
            temperature=0.0,
            provider_alias=provider_alias,
            service_type_name=service_type_name,
            api_key=api_key,
        )
    if llm is None:
        return message
    system_prompt = "You are a helpful assistant. Reply concisely."

    response = await llm.ainvoke(
        [{"role": "system", "content": system_prompt}, {"role": "user", "content": message}]
    )
    content = response.content if hasattr(response, "content") else str(response)
    return str(content)


def _content_to_text(content: Any) -> str:
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
    return ""


def _chunk_to_text(chunk: Any) -> str:
    if isinstance(chunk, str):
        return chunk

    content = getattr(chunk, "content", None)
    content_text = _content_to_text(content)
    if content_text:
        return content_text

    message = getattr(chunk, "message", None)
    message_content = getattr(message, "content", None)
    message_text = _content_to_text(message_content)
    if message_text:
        return message_text

    if hasattr(chunk, "text"):
        text_value = getattr(chunk, "text")
        if isinstance(text_value, str) and text_value:
            return text_value

    if (
        hasattr(chunk, "content")
        or hasattr(chunk, "message")
        or hasattr(chunk, "text")
    ):
        return ""

    fallback = str(chunk)
    return "" if fallback in {"None", ""} else fallback


async def generate_agent_response_stream(
    message: str,
    executed_steps: list[dict[str, Any]],
    final_result: Any,
    *,
    provider_alias: str,
    service_type_name: str,
    api_key: str | None = None,
) -> AsyncIterator[str]:
    if api_key is None:
        llm = build_llm_client(
            temperature=0.0,
            provider_alias=provider_alias,
            service_type_name=service_type_name,
            streaming=True,
        )
    else:
        llm = build_llm_client(
            temperature=0.0,
            provider_alias=provider_alias,
            service_type_name=service_type_name,
            streaming=True,
            api_key=api_key,
        )
    if llm is None:
        if final_result is None:
            yield "Operation is invalid."
        else:
            yield f"Result: {final_result}"
        return

    system_prompt = (
        "You are an agent. Provide the final answer to the user based on the tool results. "
        "If the final_result is null, explain that the operation is invalid (e.g., division by zero). "
        "Be concise."
    )
    user_payload = {
        "message": message,
        "tool_steps": executed_steps,
        "final_result": final_result,
    }

    async for chunk in llm.astream(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload)},
        ]
    ):
        text = _chunk_to_text(chunk)
        if text:
            yield text


async def generate_freeform_response_stream(
    message: str,
    *,
    provider_alias: str,
    service_type_name: str,
    api_key: str | None = None,
) -> AsyncIterator[str]:
    if api_key is None:
        llm = build_llm_client(
            temperature=0.0,
            provider_alias=provider_alias,
            service_type_name=service_type_name,
            streaming=True,
        )
    else:
        llm = build_llm_client(
            temperature=0.0,
            provider_alias=provider_alias,
            service_type_name=service_type_name,
            streaming=True,
            api_key=api_key,
        )
    if llm is None:
        yield message
        return

    system_prompt = "You are a helpful assistant. Reply concisely."
    async for chunk in llm.astream(
        [{"role": "system", "content": system_prompt}, {"role": "user", "content": message}]
    ):
        text = _chunk_to_text(chunk)
        if text:
            yield text


def _completion_to_text(response: Any) -> str:
    choices = getattr(response, "choices", None)
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    if message is None:
        return ""
    return _content_to_text(getattr(message, "content", None))


def _chunk_to_delta_text(chunk: Any) -> str:
    choices = getattr(chunk, "choices", None)
    if not choices:
        return ""
    delta = getattr(choices[0], "delta", None)
    if delta is None:
        return ""
    return _content_to_text(getattr(delta, "content", None))


def _to_openai_messages(messages: Sequence[Any]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for message in messages:
        role = _message_role(message)
        content = _message_content(message)
        payload.append({"role": role, "content": content})
    return payload


def _message_role(message: Any) -> str:
    if isinstance(message, dict):
        role = message.get("role")
        if isinstance(role, str) and role:
            return role

    msg_type = getattr(message, "type", None)
    type_to_role = {
        "human": "user",
        "system": "system",
        "ai": "assistant",
        "tool": "tool",
    }
    if isinstance(msg_type, str) and msg_type in type_to_role:
        return type_to_role[msg_type]

    class_name = message.__class__.__name__
    if class_name == "SystemMessage":
        return "system"
    if class_name == "HumanMessage":
        return "user"

    role = getattr(message, "role", None)
    if isinstance(role, str) and role:
        return role

    return "user"


def _message_content(message: Any) -> Any:
    if isinstance(message, dict):
        content = message.get("content", "")
        return content if isinstance(content, (str, list)) else str(content)

    content = getattr(message, "content", "")
    if isinstance(content, (str, list)):
        return content
    return str(content)
