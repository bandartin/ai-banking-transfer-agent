"""ToolCallingAgent -- OpenAI read-only tool runner with deterministic fallback."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command

from src.agents.context import BankingContext
from src.agents.state import BankingState
from src.agents.common import parsing
from src.agents.common.tracing import activity, traced
from src.agents.supervisor.planner import rule_plan
from src.agents.tool_calling.awx_mcp import build_awx_mcp_external_tools
from src.agents.tool_calling.policy import enforce_tool_policy, tool_audit_event
from src.agents.tool_calling.registry import ToolResult, ToolRuntime, get_tool_map_for_mode
from src.agents.tool_calling.runner import (
    ToolCallingUnavailable,
    build_tool_agent_update,
    run_langchain_tool_agent,
)


@traced("tool_agent", "run")
def tool_agent_node(state: dict, runtime: Runtime[BankingContext]) -> dict | Command:
    ctx = runtime.context
    allow_transfer_prep = (
        state.get("sub_intent") == "transfer_prep_tools"
        and bool(getattr(ctx, "tool_calling_transfer_prep_enabled", False))
    )
    try:
        external_tools = build_awx_mcp_external_tools(ctx)
        update = run_langchain_tool_agent(
            ctx,
            state,
            allow_transfer_prep=allow_transfer_prep,
            external_tools=external_tools,
        )
    except ToolCallingUnavailable as exc:
        update = _fallback_to_rule_tools(ctx, state, reason=str(exc))
    except Exception as exc:
        update = _fallback_to_rule_tools(ctx, state, reason=f"tool_calling_error:{exc.__class__.__name__}")
    return _handoff_if_transfer_prep_ready(update)


def _fallback_to_rule_tools(ctx: BankingContext, state: dict, *, reason: str) -> dict:
    plan = rule_plan(ctx, state.get("current_message", ""))
    runtime = ToolRuntime(ctx=ctx, state=state)
    allow_transfer_prep = (
        state.get("sub_intent") == "transfer_prep_tools"
        and bool(getattr(ctx, "tool_calling_transfer_prep_enabled", False))
    )
    tool_map = get_tool_map_for_mode(allow_transfer_prep=allow_transfer_prep)
    tool_results: list[ToolResult] = []
    executed: list[dict] = []

    for step in plan.steps:
        if step.agent == "transfer" and allow_transfer_prep:
            for result in _deterministic_transfer_prep(runtime, tool_map):
                tool_results.append(result)
                tool = tool_map["prepare_transfer_summary"] if result.kind == "transfer_prep" else tool_map["resolve_transfer_recipient"]
                executed.append(
                    tool_audit_event(
                        tool_name=tool.name,
                        side_effect=tool.side_effect,
                        arguments={"message": state.get("current_message", "")},
                        status="completed",
                        result=result.to_output(),
                    )
                )
            continue
        resolved = _tool_for_step(step.agent, step.sub_intent, state.get("current_message", ""))
        if resolved is None:
            continue
        tool_name, arguments = resolved
        tool = tool_map[tool_name]
        enforce_tool_policy(tool, allow_transfer_prep=allow_transfer_prep)
        result = tool.handler(runtime, arguments)
        tool_results.append(result)
        executed.append(
            tool_audit_event(
                tool_name=tool_name,
                side_effect=tool.side_effect,
                arguments=arguments,
                status="completed",
                result=result.to_output(),
            )
        )

    if not tool_results:
        return {
            "agent_results": [
                {
                    "agent": "tool_agent",
                    "kind": "message",
                    "text": "요청에 사용할 수 있는 읽기 전용 도구를 찾지 못했습니다.",
                    "data": {"fallback_reason": reason},
                }
            ],
            "agent_activity": [activity("tool_agent", "fallback_empty", {"reason": reason})],
        }

    update = build_tool_agent_update(
        final_text="\n\n".join(result.text for result in tool_results if result.text),
        tool_results=tool_results,
        executed_tool_calls=executed,
        mode="deterministic_fallback",
    )
    update["agent_activity"] = list(update.get("agent_activity", [])) + [
        activity("tool_agent", "fallback", {"reason": reason})
    ]
    return update


def _handoff_if_transfer_prep_ready(update: dict[str, Any]) -> dict[str, Any] | Command:
    prep = _find_ready_transfer_prep(update)
    if not prep:
        return update

    summary = prep.get("summary") or {}
    risk = prep.get("risk_assessment") or {}
    return Command(
        graph=Command.PARENT,
        goto="transfer",
        update={
            "sub_intent": "confirm_prepared_transfer",
            "pending_transfer_data": summary,
            "risk_assessment": risk,
            "source_account_id": summary.get("source_account_id"),
            "resolved_recipient_id": prep.get("recipient_id"),
            "resolved_favorite_id": prep.get("favorite_id"),
            "recipient_alias": summary.get("recipient_alias") or summary.get("recipient_name"),
            "amount": summary.get("amount"),
            "memo": summary.get("memo"),
            "agent_activity": list(update.get("agent_activity", []))
            + [
                activity(
                    "tool_agent",
                    "handoff_to_transfer_confirmation",
                    {
                        "recipient_id": prep.get("recipient_id"),
                        "amount": summary.get("amount"),
                    },
                )
            ],
        },
    )


def _find_ready_transfer_prep(update: dict[str, Any]) -> dict[str, Any] | None:
    for result in reversed(update.get("agent_results") or []):
        if result.get("kind") == "transfer_prep":
            data = result.get("data") or {}
            if data.get("status") == "ready_for_confirmation":
                return data

        data = result.get("data") or {}
        for output in reversed(data.get("results") or []):
            if output.get("kind") != "transfer_prep":
                continue
            prep_data = output.get("data") or {}
            if prep_data.get("status") == "ready_for_confirmation":
                return prep_data
    return None


def _deterministic_transfer_prep(runtime: ToolRuntime, tool_map: dict) -> list[ToolResult]:
    slots = parsing.extract_slots(runtime.state.get("current_message", ""))
    if not slots.recipient_alias:
        return []

    resolve_result = tool_map["resolve_transfer_recipient"].handler(
        runtime,
        {
            "recipient_alias": slots.recipient_alias,
            "bank_hint": slots.bank_hint,
        },
    )
    results = [resolve_result]
    if resolve_result.data.get("status") != "resolved" or not slots.amount:
        return results

    prep_result = tool_map["prepare_transfer_summary"].handler(
        runtime,
        {
            "recipient_id": resolve_result.data.get("recipient_id"),
            "favorite_id": resolve_result.data.get("favorite_id"),
            "recipient_alias": resolve_result.data.get("alias") or slots.recipient_alias,
            "amount": slots.amount,
            "memo": slots.memo,
            "source_account_hint": slots.source_account_hint,
        },
    )
    results.append(prep_result)
    return results


def _tool_for_step(agent: str, sub_intent: str, message: str) -> tuple[str, dict] | None:
    if agent == "inquiry" and sub_intent == "balance":
        return "get_balance_summary", {}
    if agent == "inquiry" and sub_intent == "history":
        return "get_transfer_history", {}
    if agent == "inquiry" and sub_intent == "recurring":
        return "get_recurring_transfers", {}
    if agent == "recommend":
        return "get_recipient_recommendations", {}
    if agent == "menu_search":
        return "search_menu_catalog", {"query": message}
    if agent == "product_guide":
        return "search_product_guide", {"query": message}
    if agent == "financial_calculator":
        return "calculate_finance", {"question": message}
    return None


def build_tool_calling_subgraph():
    g = StateGraph(BankingState)
    g.add_node("run", tool_agent_node)
    g.add_edge(START, "run")
    g.add_edge("run", END)
    return g.compile()
