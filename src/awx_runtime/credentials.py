"""AWX credential resolution with local-development fallback."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.awx_runtime.config import AwxCredentialSettings, config_get


@dataclass(frozen=True)
class ResolvedCredential:
    """Resolved secret plus non-secret metadata about where it came from."""

    api_key: str
    source: str
    credential_id: str = ""
    service_id: str = ""
    provider_alias: str = ""
    service_type_name: str = ""


def resolve_openai_credential(config: Any) -> ResolvedCredential | None:
    """Resolve an OpenAI API key from AWX first, then local config.

    This function intentionally never raises for AWX lookup failures. The
    banking agent must keep its deterministic fallback path available when the
    platform credential is not configured or temporarily unreachable.
    """
    settings = AwxCredentialSettings.from_config(config)
    if settings.enabled:
        resolved = _resolve_from_awx(settings)
        if resolved:
            return resolved

    local_key = str(config_get(config, "OPENAI_API_KEY", "") or "").strip()
    if local_key:
        return ResolvedCredential(
            api_key=local_key,
            source="env",
            provider_alias=settings.provider_alias,
            service_type_name=settings.service_type_name,
        )
    return None


def _resolve_from_awx(settings: AwxCredentialSettings) -> ResolvedCredential | None:
    try:
        from awx.resources import Credential
    except Exception:
        return None

    try:
        client = Credential()
        credential = client.get(
            service_id=settings.service_id_value,
            provider_alias=settings.provider_alias,
            service_type_name=settings.service_type_name,
        )
    except Exception:
        return None

    secret = _extract_with_client_helper(client, credential, settings.preferred_variable_name)
    if not secret:
        secret = extract_secret_value(credential, settings.preferred_variable_name)
    if not secret:
        return None

    selected = _first_credential(credential)
    credential_id = ""
    if isinstance(selected, dict):
        credential_id = str(selected.get("credentialId") or selected.get("id") or "")

    return ResolvedCredential(
        api_key=secret,
        source="awx",
        credential_id=credential_id,
        service_id=settings.service_id,
        provider_alias=settings.provider_alias,
        service_type_name=settings.service_type_name,
    )


def _extract_with_client_helper(
    client: Any,
    credential: Any,
    preferred_variable_name: str,
) -> str | None:
    helper = getattr(client, "extract_secret_value", None)
    if not callable(helper):
        return None
    try:
        value = helper(credential, preferred_variable_name=preferred_variable_name)
    except Exception:
        return None
    return value.strip() if isinstance(value, str) and value.strip() else None


def extract_secret_value(credential: Any, preferred_variable_name: str = "OPENAI_API_KEY") -> str | None:
    """Extract a secret from common AWX credential payload shapes."""
    selected = _first_credential(credential)
    if not isinstance(selected, dict):
        return None

    direct_value = selected.get(preferred_variable_name)
    if isinstance(direct_value, str) and direct_value.strip():
        return direct_value.strip()

    for field in ("api_key", "token", "value", "secret"):
        value = selected.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()

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
        if not isinstance(value, str) or not value.strip():
            continue
        normalized = value.strip()
        if isinstance(name, str) and name.strip().upper() == preferred_upper:
            return normalized
        if fallback_value is None:
            fallback_value = normalized
    return fallback_value


def _first_credential(credential: Any) -> Any:
    if isinstance(credential, list):
        find_and_cache = getattr(credential, "find_and_cache", None)
        if callable(find_and_cache):
            try:
                return find_and_cache(lambda _item: True)
            except Exception:
                return credential[0] if credential else None
        return credential[0] if credential else None
    return credential

