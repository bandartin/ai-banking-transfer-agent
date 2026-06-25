"""Adapter factory functions.

The default is intentionally `mock` so local tests and demos keep working.  In
an IBK environment these values should be set by deployment configuration:

- BANKING_ADAPTER=ibk
- TRANSFER_EXECUTION_MODE=dry_run|live
- KNOWLEDGE_ADAPTER=awx
"""

from __future__ import annotations

from typing import Any

from .mock_adapter import MockBankingAdapter, MockKnowledgeAdapter


_banking_adapter_cache: dict[tuple[str, str], Any] = {}
_knowledge_adapter_cache: dict[str, Any] = {}


def _config_get(key: str, default: Any = None) -> Any:
    try:
        from flask import current_app

        if current_app:
            return current_app.config.get(key, default)
    except Exception:
        pass
    import os

    return os.getenv(key, default)


def get_banking_adapter() -> Any:
    """Return the configured banking adapter.

    `ibk` and `live` currently return a placeholder that raises clear errors at
    call time.  That is deliberate: live financial execution should not be
    silently simulated once the environment says it is live.
    """
    adapter_name = _normalized_config("BANKING_ADAPTER", "mock")
    execution_mode = _normalized_config("TRANSFER_EXECUTION_MODE", "mock")
    validate_runtime_configuration(adapter_name=adapter_name, execution_mode=execution_mode)
    key = (adapter_name, execution_mode)
    if key in _banking_adapter_cache:
        return _banking_adapter_cache[key]

    if adapter_name in {"mock", "sqlite", "demo"}:
        adapter = MockBankingAdapter(execution_mode=execution_mode)
    elif adapter_name in {"ibk", "live"}:
        adapter = _UnavailableIBKAdapter(execution_mode=execution_mode)
    else:
        raise RuntimeError(f"Unknown BANKING_ADAPTER={adapter_name!r}. Use mock or ibk.")

    _banking_adapter_cache[key] = adapter
    return adapter


def get_knowledge_adapter() -> Any:
    adapter_name = _normalized_config("KNOWLEDGE_ADAPTER", "mock")
    if adapter_name in _knowledge_adapter_cache:
        return _knowledge_adapter_cache[adapter_name]

    if adapter_name == "awx":
        from .awx_knowledge_adapter import AWXKnowledgeAdapter

        adapter = AWXKnowledgeAdapter()
    elif adapter_name == "mock":
        adapter = MockKnowledgeAdapter()
    else:
        raise RuntimeError(f"Unknown KNOWLEDGE_ADAPTER={adapter_name!r}. Use mock or awx.")
    _knowledge_adapter_cache[adapter_name] = adapter
    return adapter


def validate_runtime_configuration(*, adapter_name: str | None = None, execution_mode: str | None = None) -> None:
    """Fail fast for unsafe or contradictory runtime settings."""
    adapter = adapter_name or _normalized_config("BANKING_ADAPTER", "mock")
    mode = execution_mode or _normalized_config("TRANSFER_EXECUTION_MODE", "mock")

    if mode not in {"mock", "dry_run", "live"}:
        raise RuntimeError(f"Unknown TRANSFER_EXECUTION_MODE={mode!r}. Use mock, dry_run, or live.")
    if adapter in {"mock", "sqlite", "demo"} and mode == "live":
        raise RuntimeError(
            "Unsafe configuration: TRANSFER_EXECUTION_MODE=live cannot run with BANKING_ADAPTER=mock. "
            "Use dry_run for rehearsal or implement/select BANKING_ADAPTER=ibk for live execution."
        )


def reset_adapter_caches() -> None:
    """Test helper: clear adapter singletons after environment/config changes."""
    _banking_adapter_cache.clear()
    _knowledge_adapter_cache.clear()


def _normalized_config(key: str, default: str) -> str:
    return str(_config_get(key, default) or default).strip().lower()


class _UnavailableIBKAdapter:
    """Explicit placeholder until real IBK interface specs are available."""

    source_name = "ibk-unavailable"

    def __init__(self, execution_mode: str = "dry_run") -> None:
        self.execution_mode = execution_mode

    def __getattr__(self, name: str):
        raise RuntimeError(
            "IBKApiAdapter is selected but not configured yet. "
            "Set BANKING_ADAPTER=mock for local execution or implement the IBK interface contract first."
        )
