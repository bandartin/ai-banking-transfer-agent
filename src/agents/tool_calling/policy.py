"""Policy and audit helpers for model-selected tool calls."""

from __future__ import annotations

from typing import Any

from src.awx_runtime.redaction import redact_mapping, redact_text


class ToolPolicyViolation(RuntimeError):
    """Raised when a model-selected tool is outside the active policy gate."""


_EXECUTION_TOOL_NAMES = {"execute_transfer", "approve_transfer", "confirm_transfer"}
_SIDE_EFFECTS_BY_MODE = {
    False: {"read"},
    True: {"read", "prepare"},
}
_SENSITIVE_KEY_MARKERS = (
    "account",
    "recipient_id",
    "favorite_id",
    "source_account_id",
    "user_id",
    "api_key",
    "token",
    "secret",
    "password",
)


def enforce_tool_policy(tool: Any, *, allow_transfer_prep: bool) -> None:
    """Reject tools outside the currently enabled side-effect policy."""
    name = str(getattr(tool, "name", "") or "")
    side_effect = str(getattr(tool, "side_effect", "") or "read")
    if name in _EXECUTION_TOOL_NAMES or side_effect in {"confirm", "execute"}:
        raise ToolPolicyViolation(f"Tool '{name}' is not model-callable because it can move money.")

    allowed = _SIDE_EFFECTS_BY_MODE[bool(allow_transfer_prep)]
    if side_effect not in allowed:
        raise ToolPolicyViolation(
            f"Tool '{name}' has side_effect='{side_effect}', but active policy allows {sorted(allowed)}."
        )


def tool_audit_event(
    *,
    tool_name: str,
    side_effect: str,
    arguments: dict[str, Any],
    status: str,
    result: dict[str, Any] | None = None,
    error: str = "",
) -> dict[str, Any]:
    """Build an audit-safe tool-call record for state, UI, and run logs."""
    event = {
        "tool_name": tool_name,
        "side_effect": side_effect,
        "status": status,
        "arguments": redact_tool_payload(arguments),
        "execution_allowed": side_effect == "read",
    }
    if result is not None:
        event["result"] = _result_summary(result)
    if error:
        event["error"] = redact_text(error)
    return event


def redact_tool_payload(payload: Any) -> Any:
    """Recursively redact tool arguments/results while preserving debug shape."""
    if isinstance(payload, dict):
        redacted: dict[str, Any] = {}
        for key, value in payload.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in _SENSITIVE_KEY_MARKERS):
                redacted[key] = _mask_sensitive_value(value)
            else:
                redacted[key] = redact_tool_payload(value)
        return redact_mapping(redacted)
    if isinstance(payload, list):
        return [redact_tool_payload(item) for item in payload]
    if isinstance(payload, str):
        return redact_text(payload)
    return payload


def _mask_sensitive_value(value: Any) -> Any:
    if value in (None, "", [], {}):
        return value
    if isinstance(value, dict):
        return {key: _mask_sensitive_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_mask_sensitive_value(item) for item in value]
    if isinstance(value, str):
        redacted = redact_text(value)
        return redacted if redacted != value else "***"
    return "***"


def _result_summary(result: dict[str, Any]) -> dict[str, Any]:
    data = result.get("data") if isinstance(result, dict) else None
    return {
        "kind": result.get("kind") if isinstance(result, dict) else None,
        "source_agent": result.get("source_agent") if isinstance(result, dict) else None,
        "data": redact_tool_payload(data if isinstance(data, dict) else {}),
    }
