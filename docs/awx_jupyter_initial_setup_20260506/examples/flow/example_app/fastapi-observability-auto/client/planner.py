from __future__ import annotations

import ast
import re
from typing import Any

from awx.observability.utils import extract_json
from opentelemetry import trace

from credential_defaults import (
    DEFAULT_CREDENTIAL_PROVIDER_ALIAS,
    DEFAULT_CREDENTIAL_SERVICE_TYPE_NAME,
)
from llm_service import build_llm_client

_ARITH_EXPR_RE = re.compile(r"^[0-9+\-*/().\s]+$")
_ARITHMETIC_TOOL_SET = {"add", "subtract", "multiply", "divide"}
_TRACER = trace.get_tracer("awx.observability.client.planner")


def _plan_from_expression(expression: str) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []

    def _ref_for_step(index: int) -> str:
        return f"${index}"

    def build_node(node) -> float | str:
        if isinstance(node, ast.BinOp):
            left_val = build_node(node.left)
            right_val = build_node(node.right)
            if isinstance(node.op, ast.Add):
                tool = "add"
            elif isinstance(node.op, ast.Sub):
                tool = "subtract"
            elif isinstance(node.op, ast.Mult):
                tool = "multiply"
            elif isinstance(node.op, ast.Div):
                tool = "divide"
            else:
                raise ValueError("Unsupported operator")
            steps.append({"tool": tool, "arguments": {"a": left_val, "b": right_val}})
            return _ref_for_step(len(steps) - 1)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            operand_val = build_node(node.operand)
            if isinstance(node.op, ast.USub):
                steps.append({"tool": "subtract", "arguments": {"a": 0.0, "b": operand_val}})
                return _ref_for_step(len(steps) - 1)
            return operand_val
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        raise ValueError("Unsupported expression")

    parsed = ast.parse(expression, mode="eval")
    result = build_node(parsed.body)
    if not steps:
        raise ValueError("Expression must include at least one operation")
    if isinstance(result, (int, float)):
        raise ValueError("Expression must include at least one operation")
    return steps


def _extract_tool_names(raw_tools: Any) -> list[str]:
    names: list[str] = []
    if not isinstance(raw_tools, list):
        return names
    for item in raw_tools:
        name = None
        if isinstance(item, dict):
            name = item.get("name")
        else:
            name = getattr(item, "name", None)
        if isinstance(name, str) and name:
            names.append(name)
    return sorted(set(names))


def _normalize_plan(data: dict[str, Any], available_tools: list[str]) -> list[dict[str, Any]]:
    if "steps" in data:
        raw_steps = data["steps"]
    elif "tool" in data:
        raw_steps = [data]
    else:
        raise ValueError("Plan is missing tool steps")

    available_set = set(available_tools)
    steps: list[dict[str, Any]] = []
    for step in raw_steps:
        if not isinstance(step, dict):
            raise ValueError("Invalid step")
        tool_name = step.get("tool")
        if not isinstance(tool_name, str) or not tool_name:
            raise ValueError("Invalid tool name")
        if available_set and tool_name not in available_set:
            raise ValueError(f"Unsupported tool: {tool_name}")

        if "arguments" in step:
            raw_arguments = step["arguments"]
            if not isinstance(raw_arguments, dict):
                raise ValueError("Invalid arguments")
            arguments = dict(raw_arguments)
        else:
            arguments = {k: v for k, v in step.items() if k != "tool"}
            if not arguments:
                raise ValueError("Tool arguments are missing")
        steps.append({"tool": tool_name, "arguments": arguments})
    return steps


async def _list_mcp_tools(mcp_client: Any) -> list[str]:
    tools = await mcp_client.list_tools()
    return _extract_tool_names(tools)


async def _plan_from_llm(message: str, available_tools: list[str]) -> list[dict[str, Any]]:
    llm = build_llm_client(
        temperature=0.0,
        provider_alias=DEFAULT_CREDENTIAL_PROVIDER_ALIAS,
        service_type_name=DEFAULT_CREDENTIAL_SERVICE_TYPE_NAME,
    )
    if llm is None:
        raise ValueError("OpenAI credential is not available")

    if not available_tools:
        raise ValueError("No MCP tools available")

    tools_str = ", ".join(available_tools)
    system_prompt = (
        f"You are a planner. Available tools: [{tools_str}]. "
        "Return JSON only. "
        "JSON schema: "
        "{\"steps\":[{\"tool\":\"<tool name>\",\"arguments\":{...}}]} "
        "or single-step form: {\"tool\":\"<tool name>\",\"arguments\":{...}}."
    )

    with _TRACER.start_as_current_span("planner.resolve_by_llm"):
        response = await llm.ainvoke(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": message}]
        )
    content = response.content if hasattr(response, "content") else str(response)
    data = extract_json(str(content))  # type: ignore[misc]
    return _normalize_plan(data, available_tools)


async def _resolve_tool_plan(
    message: str, mcp_client: Any
) -> tuple[list[str], list[dict[str, Any]] | None]:
    try:
        available_tools = await _list_mcp_tools(mcp_client)
    except Exception:
        available_tools = []

    if _ARITH_EXPR_RE.match(message or "") and _ARITHMETIC_TOOL_SET.issubset(set(available_tools)):
        try:
            return available_tools, _plan_from_expression(message)
        except Exception:
            pass

    try:
        return available_tools, await _plan_from_llm(message, available_tools)
    except Exception:
        return available_tools, None
