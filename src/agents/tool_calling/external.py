"""Adapters for external or MCP-provided tools.

External tools must be normalized into ``AgentTool`` objects before LangChain
sees them.  This keeps side-effect policy, audit events, and redaction on the
same path as local registry tools.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from src.agents.tool_calling.registry import AgentTool, ToolResult, ToolRuntime


ExternalToolCaller = Callable[[ToolRuntime, dict[str, Any]], Any]

_MODEL_TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_MODEL_CALLABLE_SIDE_EFFECTS = {"read", "prepare"}
_BLOCKED_SIDE_EFFECTS = {"confirm", "execute"}
_KNOWN_SIDE_EFFECTS = _MODEL_CALLABLE_SIDE_EFFECTS | _BLOCKED_SIDE_EFFECTS
_NO_ARGS_SCHEMA = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}


class ExternalToolConfigError(ValueError):
    """Raised when an external tool cannot be safely exposed to the model."""


@dataclass(frozen=True)
class ExternalToolSpec:
    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=lambda: copy.deepcopy(_NO_ARGS_SCHEMA))
    side_effect: str = "read"
    source: str = "external"


def external_tool_to_agent_tool(spec: ExternalToolSpec, caller: ExternalToolCaller) -> AgentTool:
    """Convert an external tool specification into the local AgentTool contract."""
    normalized = _normalize_external_tool_spec(spec)

    def _handler(runtime: ToolRuntime, arguments: dict[str, Any]) -> ToolResult:
        raw_result = caller(runtime, arguments)
        return normalize_external_tool_result(normalized, raw_result)

    return AgentTool(
        name=normalized.name,
        description=normalized.description,
        parameters=normalized.parameters,
        handler=_handler,
        side_effect=normalized.side_effect,
    )


def normalize_external_tool_result(spec: ExternalToolSpec, raw_result: Any) -> ToolResult:
    """Normalize common external tool result shapes into a ToolResult."""
    external_marker = {
        "source": spec.source,
        "tool_name": spec.name,
        "side_effect": spec.side_effect,
    }

    if isinstance(raw_result, ToolResult):
        data = dict(raw_result.data)
        data.setdefault("external_tool", external_marker)
        return ToolResult(
            kind=raw_result.kind,
            text=raw_result.text,
            data=data,
            source_agent=raw_result.source_agent or spec.source,
            memory=raw_result.memory,
        )

    if isinstance(raw_result, dict):
        kind = str(raw_result.get("kind") or "external_tool")
        text = str(raw_result.get("text") or "")
        data = raw_result.get("data")
        if not isinstance(data, dict):
            data = {
                key: value
                for key, value in raw_result.items()
                if key not in {"kind", "text", "source_agent", "memory"}
            }
        data = dict(data)
        data.setdefault("external_tool", external_marker)
        memory = raw_result.get("memory") if isinstance(raw_result.get("memory"), dict) else {}
        return ToolResult(
            kind=kind,
            text=text or _safe_text(data),
            data=data,
            source_agent=str(raw_result.get("source_agent") or spec.source),
            memory=memory,
        )

    if isinstance(raw_result, str):
        return ToolResult(
            kind="external_tool",
            text=raw_result,
            data={"content": raw_result, "external_tool": external_marker},
            source_agent=spec.source,
        )

    return ToolResult(
        kind="external_tool",
        text=_safe_text(raw_result),
        data={"value": raw_result, "external_tool": external_marker},
        source_agent=spec.source,
    )


def _normalize_external_tool_spec(spec: ExternalToolSpec) -> ExternalToolSpec:
    name = spec.name.strip()
    description = spec.description.strip()
    source = spec.source.strip() or "external"
    side_effect = spec.side_effect.strip().lower() or "read"

    if not _MODEL_TOOL_NAME_RE.fullmatch(name):
        raise ExternalToolConfigError(
            "External tool names must be 1-64 characters of letters, numbers, underscore, or hyphen."
        )
    if not description:
        raise ExternalToolConfigError(f"External tool '{name}' requires a description.")
    if side_effect not in _KNOWN_SIDE_EFFECTS:
        raise ExternalToolConfigError(
            f"External tool '{name}' has unsupported side_effect='{side_effect}'. "
            f"Allowed values: {sorted(_KNOWN_SIDE_EFFECTS)}"
        )
    if side_effect in _BLOCKED_SIDE_EFFECTS:
        raise ExternalToolConfigError(
            f"External tool '{name}' has side_effect='{side_effect}' and must not be model-callable."
        )

    return ExternalToolSpec(
        name=name,
        description=description,
        parameters=_normalize_parameters(name, spec.parameters),
        side_effect=side_effect,
        source=source,
    )


def _normalize_parameters(tool_name: str, parameters: dict[str, Any] | None) -> dict[str, Any]:
    schema = copy.deepcopy(parameters or _NO_ARGS_SCHEMA)
    if not isinstance(schema, dict):
        raise ExternalToolConfigError(f"External tool '{tool_name}' parameters must be a JSON schema object.")
    if schema.get("type", "object") != "object":
        raise ExternalToolConfigError(f"External tool '{tool_name}' parameters must use type='object'.")

    properties = schema.get("properties") or {}
    if not isinstance(properties, dict):
        raise ExternalToolConfigError(f"External tool '{tool_name}' properties must be an object.")

    required = schema.get("required") or []
    if not isinstance(required, list):
        raise ExternalToolConfigError(f"External tool '{tool_name}' required must be a list.")

    if "additionalProperties" in schema and schema["additionalProperties"] is not False:
        raise ExternalToolConfigError(
            f"External tool '{tool_name}' must set additionalProperties=false for strict tool calling."
        )

    schema["type"] = "object"
    schema["properties"] = properties
    schema["required"] = required
    schema["additionalProperties"] = False
    return schema


def _safe_text(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)
