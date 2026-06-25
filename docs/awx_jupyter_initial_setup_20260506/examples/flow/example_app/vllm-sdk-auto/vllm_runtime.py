from __future__ import annotations

import os
from typing import Any

from awx.resources import Credential, ExternalResource
from fastapi import HTTPException

try:
    from openai import AsyncOpenAI
except Exception:  # pragma: no cover
    AsyncOpenAI = None  # type: ignore[assignment]


DEFAULT_CREDENTIAL_SERVICE_ID = 30
DEFAULT_PROVIDER_ALIAS = "Custom"
DEFAULT_SERVICE_TYPE_NAME = "LLM"
DEFAULT_SOLUTION_ID = "BUILDER"
DEFAULT_TEMPERATURE = 0.0


def _select_first(payload: Any) -> dict[str, Any] | None:
    selected = payload
    if isinstance(selected, list):
        find_and_cache = getattr(selected, "find_and_cache", None)
        if callable(find_and_cache):
            selected = find_and_cache(lambda _item: True)
        elif selected:
            selected = selected[0]
    return selected if isinstance(selected, dict) else None


def _extract_secret_value(credential_client: Credential, credential: Any) -> str | None:
    if hasattr(credential_client, "extract_secret_value"):
        try:
            extracted = credential_client.extract_secret_value(
                credential,
                preferred_variable_name="OPENAI_API_KEY",
            )
            if isinstance(extracted, str) and extracted.strip():
                return extracted.strip()
        except Exception:
            pass

    selected = _select_first(credential)
    if selected is None:
        return None

    direct_value = selected.get("OPENAI_API_KEY")
    if isinstance(direct_value, str) and direct_value.strip():
        return direct_value.strip()

    variables = selected.get("variables")
    if not isinstance(variables, list):
        return None

    for item in variables:
        if not isinstance(item, dict):
            continue
        name = item.get("attributeName") or item.get("name")
        value = item.get("attributeValue") or item.get("value") or item.get("secret")
        if (
            isinstance(name, str)
            and name.strip().upper() == "OPENAI_API_KEY"
            and isinstance(value, str)
            and value.strip()
        ):
            return value.strip()
    return None


def _platform_code() -> str:
    try:
        from awx.common import config as awx_config

        candidate = getattr(awx_config, "PLATFORM_CODE", None)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    except Exception:
        pass
    return (
        os.getenv("MLDL_PLATFORM_CODE")
        or os.getenv("PLATFORM_CODE")
        or DEFAULT_SOLUTION_ID
    ).strip()


def _resolve_api_key() -> str:
    credential_client = Credential()
    try:
        credential = credential_client.get(
            service_id=DEFAULT_CREDENTIAL_SERVICE_ID,
            provider_alias=DEFAULT_PROVIDER_ALIAS,
            service_type_name=DEFAULT_SERVICE_TYPE_NAME,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "OPENAI_API_KEY_MISSING",
                "message": "OpenAI API key is required via awx.resources.Credential.get().",
                "error": str(exc),
            },
        ) from exc

    api_key = _extract_secret_value(credential_client, credential)
    if api_key:
        return api_key

    raise HTTPException(
        status_code=400,
        detail={
            "code": "OPENAI_API_KEY_MISSING",
            "message": "OpenAI API key is required via awx.resources.Credential.get().",
        },
    )


def _resolve_resource() -> dict[str, Any]:
    resource_client = ExternalResource()
    try:
        resources = resource_client.get(
            provider_alias=DEFAULT_PROVIDER_ALIAS,
            solution_id=_platform_code(),
            service_type_name=DEFAULT_SERVICE_TYPE_NAME,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "EXTERNAL_RESOURCE_MISSING",
                "message": "vLLM endpoint/model metadata is required via awx.resources.ExternalResource.get().",
                "error": str(exc),
            },
        ) from exc

    selected = _select_first(resources)
    if selected is None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "EXTERNAL_RESOURCE_MISSING",
                "message": "vLLM endpoint/model metadata is required via awx.resources.ExternalResource.get().",
            },
        )
    return selected


def _resolve_base_url(resource: dict[str, Any]) -> str:
    base_url = resource.get("endpoint") or resource.get("baseUrl")
    if isinstance(base_url, str) and base_url.strip():
        return base_url.strip()
    raise HTTPException(
        status_code=400,
        detail={
            "code": "EXTERNAL_RESOURCE_ENDPOINT_MISSING",
            "message": "External resource endpoint is required for the vLLM example.",
        },
    )


def _resolve_model_name(resource: dict[str, Any], requested_model: str | None) -> str:
    if isinstance(requested_model, str) and requested_model.strip():
        return requested_model.strip()
    for field_name in ("modelAlias", "actualModelName", "deploymentName", "model"):
        value = resource.get(field_name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise HTTPException(
        status_code=400,
        detail={
            "code": "EXTERNAL_RESOURCE_MODEL_MISSING",
            "message": "External resource model metadata is required for the vLLM example.",
        },
    )


def _messages(message: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": "You are a concise Korean assistant. Answer in Korean.",
        },
        {"role": "user", "content": message},
    ]


def _text_from_completion(response: Any) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    content = getattr(getattr(choices[0], "message", None), "content", "")
    return content if isinstance(content, str) else str(content or "")


def _openai_client(*, api_key: str, base_url: str) -> Any:
    if AsyncOpenAI is None:
        raise HTTPException(status_code=500, detail={"code": "OPENAI_SDK_MISSING"})
    return AsyncOpenAI(api_key=api_key, base_url=base_url)


async def _call_vllm(*, model: str, prompt: str, api_key: str, base_url: str) -> str:
    client = _openai_client(api_key=api_key, base_url=base_url)
    response = await client.chat.completions.create(
        model=model,
        messages=_messages(prompt),
        temperature=DEFAULT_TEMPERATURE,
    )
    return _text_from_completion(response)
