"""LangChain tool-calling runner with a raw OpenAI adapter fallback."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import Field, create_model

from src.agents.context import BankingContext
from src.agents.common.tracing import activity
from src.agents.tool_calling.policy import ToolPolicyViolation, enforce_tool_policy, tool_audit_event
from src.agents.tool_calling.registry import AgentTool, ToolResult, ToolRuntime, get_tools


class ToolCallingUnavailable(RuntimeError):
    """Raised when OpenAI tool calling cannot run and the graph should fallback."""


@dataclass(frozen=True)
class ParsedToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str


def run_langchain_tool_agent(
    ctx: BankingContext,
    state: dict[str, Any],
    *,
    allow_transfer_prep: bool = False,
    external_tools: list[AgentTool] | None = None,
    agent: Any | None = None,
    llm: Any | None = None,
) -> dict[str, Any]:
    """Run one LangChain tool-calling turn and return a LangGraph state update."""
    if not ctx.tool_calling_enabled:
        raise ToolCallingUnavailable("OpenAI tool calling is disabled")
    if not ctx.llm_enabled:
        raise ToolCallingUnavailable("OpenAI credential is not available")

    tools = _compose_model_tools(
        get_tools(allow_transfer_prep=allow_transfer_prep),
        external_tools=external_tools,
        allow_transfer_prep=allow_transfer_prep,
    )
    runtime = ToolRuntime(ctx=ctx, state=state)
    executed: list[dict[str, Any]] = []
    tool_results: list[ToolResult] = []
    model = ctx.openai_tool_model or ctx.openai_model

    langchain_tools = _build_langchain_tools(
        tools,
        runtime=runtime,
        allow_transfer_prep=allow_transfer_prep,
        executed_tool_calls=executed,
        tool_results=tool_results,
    )
    lc_agent = agent or _build_langchain_agent(ctx, langchain_tools, allow_transfer_prep=allow_transfer_prep, llm=llm)
    result = lc_agent.invoke(
        {"messages": [{"role": "user", "content": state.get("current_message", "")}]},
        config={"recursion_limit": max(3, int(ctx.tool_calling_max_steps or 4) * 2 + 1)},
    )
    final_text = _extract_langchain_response_text(result)
    if not final_text:
        final_text = "\n\n".join(result.text for result in tool_results if result.text)

    return build_tool_agent_update(
        final_text=final_text,
        tool_results=tool_results,
        executed_tool_calls=executed,
        mode="langchain_tool_calling",
        model=model,
    )


def run_openai_tool_agent(
    ctx: BankingContext,
    state: dict[str, Any],
    *,
    allow_transfer_prep: bool = False,
    external_tools: list[AgentTool] | None = None,
) -> dict[str, Any]:
    """Backward-compatible alias for the LangChain-standard tool runner."""
    return run_langchain_tool_agent(
        ctx,
        state,
        allow_transfer_prep=allow_transfer_prep,
        external_tools=external_tools,
    )


def run_openai_responses_tool_agent(
    ctx: BankingContext,
    state: dict[str, Any],
    *,
    client: Any | None = None,
    allow_transfer_prep: bool = False,
    external_tools: list[AgentTool] | None = None,
) -> dict[str, Any]:
    """Raw OpenAI Responses API adapter. Use only for exceptional cases."""
    if not ctx.tool_calling_enabled:
        raise ToolCallingUnavailable("OpenAI tool calling is disabled")
    if not ctx.llm_enabled:
        raise ToolCallingUnavailable("OpenAI credential is not available")

    tools = _compose_model_tools(
        get_tools(allow_transfer_prep=allow_transfer_prep),
        external_tools=external_tools,
        allow_transfer_prep=allow_transfer_prep,
    )
    tool_map = {tool.name: tool for tool in tools}
    openai_tools = [tool.to_openai_schema() for tool in tools]
    runtime = ToolRuntime(ctx=ctx, state=state)
    openai_client = client or _build_openai_client(ctx)
    model = ctx.openai_tool_model or ctx.openai_model
    max_steps = max(1, int(ctx.tool_calling_max_steps or 4))

    response = openai_client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": _system_prompt(allow_transfer_prep=allow_transfer_prep)},
            {"role": "user", "content": state.get("current_message", "")},
        ],
        tools=openai_tools,
        tool_choice="auto",
    )

    executed: list[dict[str, Any]] = []
    tool_results: list[ToolResult] = []
    final_text = ""

    for _ in range(max_steps):
        calls = _extract_response_tool_calls(response)
        if not calls:
            final_text = _response_text(response)
            break

        outputs = []
        for call in calls:
            if call.name not in tool_map:
                result_payload = {"error": f"Unsupported tool: {call.name}"}
                audit_event = tool_audit_event(
                    tool_name=call.name,
                    side_effect="unknown",
                    arguments=call.arguments,
                    status="blocked",
                    result=result_payload,
                    error=result_payload["error"],
                )
            else:
                tool = tool_map[call.name]
                try:
                    enforce_tool_policy(tool, allow_transfer_prep=allow_transfer_prep)
                    result = tool.handler(runtime, call.arguments)
                    tool_results.append(result)
                    result_payload = result.to_output()
                    audit_event = tool_audit_event(
                        tool_name=call.name,
                        side_effect=tool.side_effect,
                        arguments=call.arguments,
                        status="completed",
                        result=result_payload,
                    )
                except Exception as exc:
                    result_payload = {"error": str(exc), "policy_blocked": isinstance(exc, ToolPolicyViolation)}
                    audit_event = tool_audit_event(
                        tool_name=call.name,
                        side_effect=tool.side_effect,
                        arguments=call.arguments,
                        status="blocked" if result_payload["policy_blocked"] else "failed",
                        result=result_payload,
                        error=str(exc),
                    )

            executed.append(audit_event)
            outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(result_payload, ensure_ascii=False, default=str),
                }
            )

        response = openai_client.responses.create(
            model=model,
            input=outputs,
            previous_response_id=_response_id(response),
            tools=openai_tools,
            tool_choice="auto",
        )

    if not final_text:
        final_text = _response_text(response) or "\n\n".join(result.text for result in tool_results if result.text)

    return build_tool_agent_update(
        final_text=final_text,
        tool_results=tool_results,
        executed_tool_calls=executed,
        mode="openai_responses",
        model=model,
    )


def _compose_model_tools(
    base_tools: list[AgentTool],
    *,
    external_tools: list[AgentTool] | None = None,
    allow_transfer_prep: bool,
) -> list[AgentTool]:
    combined: list[AgentTool] = []
    seen: set[str] = set()

    for tool in [*base_tools, *(external_tools or [])]:
        name = str(getattr(tool, "name", "") or "")
        side_effect = str(getattr(tool, "side_effect", "") or "read")
        if not name:
            raise ToolCallingUnavailable("A model-callable tool is missing its name.")
        if name in seen:
            raise ToolCallingUnavailable(f"Duplicate model-callable tool name: {name}")
        if side_effect in {"confirm", "execute"}:
            raise ToolCallingUnavailable(f"Tool '{name}' is not model-callable because it can move money.")
        if side_effect == "prepare" and not allow_transfer_prep:
            continue
        if side_effect not in {"read", "prepare"}:
            raise ToolCallingUnavailable(f"Tool '{name}' has unsupported side_effect='{side_effect}'.")
        combined.append(tool)
        seen.add(name)

    return combined


def _build_langchain_agent(
    ctx: BankingContext,
    tools: list[Any],
    *,
    allow_transfer_prep: bool,
    llm: Any | None = None,
) -> Any:
    try:
        from langchain.agents import create_agent
        from langchain_openai import ChatOpenAI
    except Exception as exc:
        raise ToolCallingUnavailable(f"LangChain tool calling is unavailable: {exc}") from exc

    chat_model = llm or ChatOpenAI(
        model=ctx.openai_tool_model or ctx.openai_model,
        api_key=ctx.openai_api_key,
        temperature=0.0,
    )
    return create_agent(
        model=chat_model,
        tools=tools,
        system_prompt=_system_prompt(allow_transfer_prep=allow_transfer_prep),
    )


def _build_langchain_tools(
    tools: list[AgentTool],
    *,
    runtime: ToolRuntime,
    allow_transfer_prep: bool,
    executed_tool_calls: list[dict[str, Any]],
    tool_results: list[ToolResult],
) -> list[Any]:
    try:
        from langchain_core.tools import StructuredTool
    except Exception as exc:
        raise ToolCallingUnavailable(f"LangChain StructuredTool is unavailable: {exc}") from exc

    langchain_tools = []
    for tool in tools:
        args_schema = _args_model_from_json_schema(tool.name, tool.parameters)

        def _run_tool(_tool: AgentTool = tool, **kwargs: Any) -> str:
            arguments = _normalize_langchain_tool_args(kwargs)
            try:
                enforce_tool_policy(_tool, allow_transfer_prep=allow_transfer_prep)
                result = _tool.handler(runtime, arguments)
                tool_results.append(result)
                result_payload = result.to_output()
                audit_event = tool_audit_event(
                    tool_name=_tool.name,
                    side_effect=_tool.side_effect,
                    arguments=arguments,
                    status="completed",
                    result=result_payload,
                )
            except Exception as exc:
                result_payload = {"error": str(exc), "policy_blocked": isinstance(exc, ToolPolicyViolation)}
                audit_event = tool_audit_event(
                    tool_name=_tool.name,
                    side_effect=_tool.side_effect,
                    arguments=arguments,
                    status="blocked" if result_payload["policy_blocked"] else "failed",
                    result=result_payload,
                    error=str(exc),
                )
            executed_tool_calls.append(audit_event)
            return json.dumps(result_payload, ensure_ascii=False, default=str)

        langchain_tools.append(
            StructuredTool.from_function(
                name=tool.name,
                description=tool.description,
                args_schema=args_schema,
                func=_run_tool,
            )
        )
    return langchain_tools


def _args_model_from_json_schema(tool_name: str, schema: dict[str, Any]) -> type:
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    fields: dict[str, tuple[Any, Any]] = {}
    for field_name, spec in properties.items():
        if not isinstance(spec, dict):
            spec = {}
        field_type = _json_schema_type_to_python(spec.get("type"))
        description = str(spec.get("description") or "")
        default = ... if field_name in required else None
        fields[field_name] = (field_type, Field(default=default, description=description))
    model_name = "".join(ch for ch in tool_name.title() if ch.isalnum()) or "Tool"
    return create_model(f"{model_name}Args", **fields)


def _json_schema_type_to_python(schema_type: Any) -> Any:
    if isinstance(schema_type, list):
        non_null = [item for item in schema_type if item != "null"]
        if len(non_null) == 1:
            return _json_schema_type_to_python(non_null[0]) | None
        return Any
    return {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }.get(schema_type or "string", str)


def _normalize_langchain_tool_args(arguments: dict[str, Any]) -> dict[str, Any]:
    if set(arguments) == {"payload"} and isinstance(arguments.get("payload"), dict):
        return dict(arguments["payload"])
    return dict(arguments)


def _extract_langchain_response_text(result: Any) -> str:
    if isinstance(result, dict):
        output = result.get("output")
        if isinstance(output, str) and output.strip():
            return output.strip()
        messages = result.get("messages")
        if isinstance(messages, list) and messages:
            content = getattr(messages[-1], "content", None)
            if isinstance(content, str):
                return content.strip()
            if isinstance(messages[-1], dict):
                dict_content = messages[-1].get("content")
                if isinstance(dict_content, str):
                    return dict_content.strip()
    return str(result or "").strip()


def build_tool_agent_update(
    *,
    final_text: str,
    tool_results: list[ToolResult],
    executed_tool_calls: list[dict[str, Any]],
    mode: str,
    model: str = "",
) -> dict[str, Any]:
    memory: dict[str, Any] = {}
    for result in tool_results:
        memory.update(result.memory)

    if len(tool_results) == 1:
        first = tool_results[0]
        kind = first.kind
        data = {**first.data, "tool_audit_events": executed_tool_calls}
        text = final_text or first.text
    else:
        kind = "message"
        data = {
            "tool_calls": executed_tool_calls,
            "tool_audit_events": executed_tool_calls,
            "results": [result.to_output() for result in tool_results],
        }
        text = final_text or "\n\n".join(result.text for result in tool_results if result.text)

    return {
        "agent_results": [
            {
                "agent": "tool_agent",
                "kind": kind,
                "text": text,
                "data": data,
            }
        ],
        **memory,
        "agent_activity": [
            activity(
                "tool_agent",
                "done",
                {
                    "mode": mode,
                    "model": model,
                    "tool_calls": [item["tool_name"] for item in executed_tool_calls],
                    "audit_event_count": len(executed_tool_calls),
                },
            )
        ],
    }


def _build_openai_client(ctx: BankingContext) -> Any:
    try:
        from openai import OpenAI
    except Exception as exc:
        raise ToolCallingUnavailable(f"OpenAI SDK is unavailable: {exc}") from exc
    return OpenAI(api_key=ctx.openai_api_key)


def _system_prompt(*, allow_transfer_prep: bool = False) -> str:
    prompt = (
        "You are EumBank's Korean banking assistant running a read-only tool-calling phase. "
        "Use tools for balances, transfer history, recurring transfers, recipient recommendations, "
        "menu or product knowledge, and deterministic financial calculations. "
        "Never ask the user for user_id, account ownership, or credentials; server context supplies identity. "
        "Return a concise Korean answer grounded only in tool results."
    )
    if allow_transfer_prep:
        return (
            prompt
            + " You may resolve recipients and prepare a transfer summary for human confirmation, "
            "but you must not claim the transfer is approved or executed. "
            "If the recipient is ambiguous or missing, ask the user to choose."
        )
    return prompt + " Do not prepare, validate, approve, or execute transfers."


def _extract_response_tool_calls(response: Any) -> list[ParsedToolCall]:
    calls: list[ParsedToolCall] = []
    for item in _response_output(response):
        item_type = _get(item, "type")
        if item_type != "function_call":
            continue
        name = str(_get(item, "name") or "")
        raw_arguments = str(_get(item, "arguments") or "{}")
        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError:
            arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}
        call_id = str(_get(item, "call_id") or _get(item, "id") or name or "tool-call")
        calls.append(
            ParsedToolCall(
                call_id=call_id,
                name=name,
                arguments=arguments,
                raw_arguments=raw_arguments,
            )
        )
    return calls


def _response_output(response: Any) -> list[Any]:
    output = _get(response, "output") or []
    return list(output) if isinstance(output, list) else []


def _response_text(response: Any) -> str:
    text = _get(response, "output_text")
    if isinstance(text, str):
        return text.strip()
    chunks: list[str] = []
    for item in _response_output(response):
        if _get(item, "type") == "message":
            for part in _get(item, "content") or []:
                part_text = _get(part, "text")
                if isinstance(part_text, str):
                    chunks.append(part_text)
    return "\n".join(chunks).strip()


def _response_id(response: Any) -> str:
    response_id = _get(response, "id")
    if not response_id:
        raise ToolCallingUnavailable("OpenAI response id is missing")
    return str(response_id)


def _get(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
