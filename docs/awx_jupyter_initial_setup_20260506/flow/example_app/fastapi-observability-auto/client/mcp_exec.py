from __future__ import annotations

import os
from typing import Any

from awx.observability.session import get_session_id
from opentelemetry.propagate import inject

_ARITHMETIC_TOOLS = {"add", "subtract", "multiply", "divide"}
_A_ALIASES = ("a", "left", "lhs", "x", "minuend", "augend", "multiplicand", "dividend", "numerator")
_B_ALIASES = ("b", "right", "rhs", "y", "subtrahend", "addend", "multiplier", "divisor", "denominator")


def _mcp_sse_transport():
    from fastmcp.client.transports import SSETransport

    sse_url = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8001/mcp/sse")
    session_id = get_session_id()
    headers: dict[str, str] = {}
    if session_id:
        headers["X-AWX-Session-Id"] = session_id
    inject(headers)
    return SSETransport(url=sse_url, headers=headers)


async def _call_mcp_tool(mcp_client: Any, tool_name: str, arguments: dict[str, Any]) -> Any:
    result = await mcp_client.call_tool(tool_name, arguments)
    return result.data


def _normalize_tool_arguments(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if tool_name not in _ARITHMETIC_TOOLS:
        return arguments
    if "a" in arguments and "b" in arguments:
        return arguments

    a_value = next((arguments[key] for key in _A_ALIASES if key in arguments), None)
    b_value = next((arguments[key] for key in _B_ALIASES if key in arguments), None)
    if a_value is None or b_value is None:
        return arguments
    return {"a": a_value, "b": b_value}


async def _execute_plan(
    steps: list[dict[str, Any]],
    mcp_client: Any,
) -> tuple[Any, list[dict[str, Any]]]:
    executed: list[dict[str, Any]] = []
    result: Any = None
    results: list[Any] = []

    def _resolve_reference(value: Any) -> Any:
        if not isinstance(value, str) or not value.startswith("$"):
            return value

        ref = value[1:]
        index_str, sep, key = ref.partition(".")
        index = int(index_str)
        resolved = results[index]
        if sep:
            if not isinstance(resolved, dict):
                raise ValueError("Reference key requires dict result")
            resolved = resolved.get(key)
        if resolved is None:
            raise ValueError("Reference resolved to null")
        return resolved

    for step in steps:
        tool_name = str(step["tool"])
        raw_arguments = step["arguments"]
        if not isinstance(raw_arguments, dict):
            raise ValueError("Invalid tool arguments")
        resolved_arguments = {k: _resolve_reference(v) for k, v in raw_arguments.items()}
        resolved_arguments = _normalize_tool_arguments(tool_name, resolved_arguments)
        result = await _call_mcp_tool(mcp_client, tool_name, resolved_arguments)
        results.append(result)
        executed.append(
            {
                "tool": tool_name,
                "arguments": raw_arguments,
                "resolved_arguments": resolved_arguments,
                "result": result,
            }
        )
    return result, executed
