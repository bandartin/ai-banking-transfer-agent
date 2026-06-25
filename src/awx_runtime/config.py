"""Configuration helpers for optional AWX runtime integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def config_get(config: Any, key: str, default: Any = None) -> Any:
    """Read a value from Flask config, dict-like objects, or simple classes."""
    getter = getattr(config, "get", None)
    if callable(getter):
        return getter(key, default)
    return getattr(config, key, default)


@dataclass(frozen=True)
class AwxCredentialSettings:
    """Credential lookup metadata used by `awx.resources.Credential`."""

    service_id: str = ""
    provider_alias: str = "OpenAI"
    service_type_name: str = "LLM"
    preferred_variable_name: str = "OPENAI_API_KEY"

    @classmethod
    def from_config(cls, config: Any) -> "AwxCredentialSettings":
        return cls(
            service_id=str(config_get(config, "AWX_CREDENTIAL_SERVICE_ID", "") or "").strip(),
            provider_alias=str(
                config_get(config, "AWX_CREDENTIAL_PROVIDER_ALIAS", "OpenAI") or "OpenAI"
            ).strip(),
            service_type_name=str(
                config_get(config, "AWX_CREDENTIAL_SERVICE_TYPE_NAME", "LLM") or "LLM"
            ).strip(),
            preferred_variable_name=str(
                config_get(config, "AWX_CREDENTIAL_VARIABLE_NAME", "OPENAI_API_KEY")
                or "OPENAI_API_KEY"
            ).strip(),
        )

    @property
    def enabled(self) -> bool:
        return bool(self.service_id and self.provider_alias and self.service_type_name)

    @property
    def service_id_value(self) -> int | str:
        return int(self.service_id) if self.service_id.isdigit() else self.service_id

