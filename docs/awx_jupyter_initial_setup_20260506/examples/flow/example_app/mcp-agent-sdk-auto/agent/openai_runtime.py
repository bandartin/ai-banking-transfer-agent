from __future__ import annotations

import logging
from typing import Any

from awx.resources import Credential, bootstrap_portal_runtime
from fastapi import HTTPException


logger = logging.getLogger("mcp-agent-sdk-auto.agent")
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
