"""Phase 1 OpenAI tool-calling guardrail tests."""

import pytest
from langgraph.types import Command

from src.agents.context import BankingContext
from src.agents.state import fresh_turn_state
from src.agents.subagents.tool_agent import _handoff_if_transfer_prep_ready
from src.agents.subagents.transfer import build_transfer_subgraph
from src.agents.supervisor import planner
from src.agents.tool_calling.policy import (
    ToolPolicyViolation,
    enforce_tool_policy,
    redact_tool_payload,
    tool_audit_event,
)
from src.agents.tool_calling.registry import AgentTool, ToolResult, ToolRuntime, get_readonly_tools, get_transfer_prep_tools
from src.agents.tool_calling.runner import _build_langchain_tools, build_tool_agent_update


def _openai_ctx(*, transfer_prep: bool = False) -> BankingContext:
    return BankingContext(
        user_id=1,
        session_id="tool-phase1",
        llm_provider="openai",
        openai_api_key="sk-test",
        tool_calling_enabled=True,
        tool_calling_transfer_prep_enabled=transfer_prep,
    )


def test_phase1_tool_schemas_are_strict_and_read_only():
    tools = get_readonly_tools()
    names = {tool.name for tool in tools}

    assert "execute_transfer" not in names
    assert "validate_transfer" not in names
    assert {"get_balance_summary", "get_recipient_recommendations", "calculate_finance"} <= names

    for tool in tools:
        schema = tool.to_openai_schema()
        assert schema["type"] == "function"
        assert schema["strict"] is True
        assert schema["parameters"]["additionalProperties"] is False
        assert tool.side_effect == "read"


def test_phase2_transfer_prep_tools_do_not_expose_execution():
    tools = get_transfer_prep_tools()
    names = {tool.name for tool in tools}

    assert names == {"resolve_transfer_recipient", "prepare_transfer_summary"}
    assert "execute_transfer" not in names
    assert "validate_transfer" not in names
    assert all(tool.side_effect == "prepare" for tool in tools)


def test_phase4_policy_blocks_prepare_tools_without_explicit_gate():
    tool = get_transfer_prep_tools()[0]

    with pytest.raises(ToolPolicyViolation):
        enforce_tool_policy(tool, allow_transfer_prep=False)

    enforce_tool_policy(tool, allow_transfer_prep=True)


def test_phase4_tool_audit_payload_is_redacted():
    payload = {
        "recipient_id": 7,
        "amount": 50_000,
        "recipient_account": "200-300-4000",
        "nested": {"source_account_id": 1, "api_key": "sk-test-very-secret"},
    }

    redacted = redact_tool_payload(payload)

    assert redacted["recipient_id"] == "***"
    assert redacted["amount"] == 50_000
    assert redacted["recipient_account"] == "****-4000"
    assert redacted["nested"]["source_account_id"] == "***"
    assert redacted["nested"]["api_key"] == "***"


def test_phase4_single_tool_result_includes_audit_events():
    result = ToolResult(
        kind="transfer_prep",
        text="ready",
        data={"status": "ready_for_confirmation", "summary": {"recipient_account": "200-300-4000"}},
        source_agent="tool_agent",
    )
    audit_event = tool_audit_event(
        tool_name="prepare_transfer_summary",
        side_effect="prepare",
        arguments={"recipient_id": 7, "recipient_account": "200-300-4000"},
        status="completed",
        result=result.to_output(),
    )

    update = build_tool_agent_update(
        final_text="ready",
        tool_results=[result],
        executed_tool_calls=[audit_event],
        mode="unit",
    )

    data = update["agent_results"][0]["data"]
    assert data["tool_audit_events"][0]["execution_allowed"] is False
    assert data["tool_audit_events"][0]["arguments"]["recipient_id"] == "***"
    assert data["tool_audit_events"][0]["result"]["data"]["summary"]["recipient_account"] == "****-4000"


def test_phase45_langchain_tool_wrapper_executes_with_policy_and_audit():
    runtime = ToolRuntime(ctx=_openai_ctx(), state={"current_message": "잔고"})
    tool_results = []
    executed = []
    agent_tool = AgentTool(
        name="sample_read_tool",
        description="Read-only sample tool.",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "query"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        handler=lambda _runtime, args: ToolResult(
            kind="sample",
            text="ok",
            data={"query": args["query"], "recipient_account": "200-300-4000"},
            source_agent="tool_agent",
        ),
        side_effect="read",
    )

    langchain_tools = _build_langchain_tools(
        [agent_tool],
        runtime=runtime,
        allow_transfer_prep=False,
        executed_tool_calls=executed,
        tool_results=tool_results,
    )
    output = langchain_tools[0].invoke({"query": "200-300-4000"})

    assert '"kind": "sample"' in output
    assert len(tool_results) == 1
    assert executed[0]["tool_name"] == "sample_read_tool"
    assert executed[0]["status"] == "completed"
    assert executed[0]["arguments"]["query"] == "****-4000"
    assert executed[0]["result"]["data"]["recipient_account"] == "****-4000"


def test_phase45_langchain_tool_wrapper_blocks_prepare_without_gate():
    runtime = ToolRuntime(ctx=_openai_ctx(), state={"current_message": "이체"})
    tool_results = []
    executed = []
    agent_tool = AgentTool(
        name="sample_prepare_tool",
        description="Prepare sample tool.",
        parameters={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        handler=lambda _runtime, _args: ToolResult(
            kind="sample",
            text="blocked",
            data={},
            source_agent="tool_agent",
        ),
        side_effect="prepare",
    )

    langchain_tools = _build_langchain_tools(
        [agent_tool],
        runtime=runtime,
        allow_transfer_prep=False,
        executed_tool_calls=executed,
        tool_results=tool_results,
    )
    output = langchain_tools[0].invoke({})

    assert "policy_blocked" in output
    assert tool_results == []
    assert executed[0]["status"] == "blocked"
    assert executed[0]["execution_allowed"] is False


def test_make_plan_collapses_readonly_work_to_tool_agent(monkeypatch):
    monkeypatch.setattr(planner.llm_helper, "plan_with_llm", lambda *_args, **_kwargs: None)

    plan = planner.make_plan(_openai_ctx(), "잔고 보여주고 자주 보내는 사람도 추천해줘")

    assert [step.agent for step in plan.steps] == ["tool_agent"]
    assert plan.steps[0].sub_intent == "read_only_tools"
    assert plan.planner == "rule+tool_calling"


def test_make_plan_keeps_transfer_out_of_phase1_tool_agent(monkeypatch):
    monkeypatch.setattr(planner.llm_helper, "plan_with_llm", lambda *_args, **_kwargs: None)

    plan = planner.make_plan(_openai_ctx(), "엄마에게 5만원 보내줘")

    assert [step.agent for step in plan.steps] == ["transfer"]
    assert plan.planner == "rule"


def test_make_plan_can_route_transfer_prep_when_explicitly_enabled(monkeypatch):
    monkeypatch.setattr(planner.llm_helper, "plan_with_llm", lambda *_args, **_kwargs: None)

    plan = planner.make_plan(_openai_ctx(transfer_prep=True), "엄마에게 5만원 보내줘")

    assert [step.agent for step in plan.steps] == ["tool_agent"]
    assert plan.steps[0].sub_intent == "transfer_prep_tools"
    assert plan.planner == "rule+tool_calling_transfer_prep"


def test_phase3_ready_transfer_prep_hands_off_to_confirmation():
    update = {
        "agent_results": [
            {
                "agent": "tool_agent",
                "kind": "message",
                "text": "prepared",
                "data": {
                    "results": [
                        {
                            "kind": "transfer_prep",
                            "text": "ready",
                            "data": {
                                "status": "ready_for_confirmation",
                                "recipient_id": 7,
                                "favorite_id": 3,
                                "risk_assessment": {"level": "low", "risk_score": 0},
                                "summary": _prepared_summary(),
                            },
                            "source_agent": "tool_agent",
                        }
                    ]
                },
            }
        ],
        "agent_activity": [],
    }

    command = _handoff_if_transfer_prep_ready(update)

    assert isinstance(command, Command)
    assert command.graph == Command.PARENT
    assert command.goto == "transfer"
    assert command.update["sub_intent"] == "confirm_prepared_transfer"
    assert command.update["pending_transfer_data"]["amount"] == 50_000
    assert command.update["resolved_recipient_id"] == 7
    assert command.update["resolved_favorite_id"] == 3


def test_phase3_prepared_transfer_uses_existing_confirmation_interrupt():
    graph = build_transfer_subgraph()
    state = fresh_turn_state(1, "tool-phase3-confirm", "prepared")
    state.update(
        {
            "sub_intent": "confirm_prepared_transfer",
            "pending_transfer_data": _prepared_summary(),
            "risk_assessment": {"level": "low", "risk_score": 0, "warnings": []},
            "resolved_recipient_id": 7,
            "resolved_favorite_id": 3,
        }
    )

    result = graph.invoke(state, context=_openai_ctx(transfer_prep=True))
    interrupts = result.get("__interrupt__") or []
    payload = interrupts[0].value if hasattr(interrupts[0], "value") else interrupts[0]

    assert payload["kind"] == "confirmation"
    assert payload["response_type"] == "confirmation"
    assert payload["response_data"]["amount"] == 50_000


def _prepared_summary() -> dict:
    return {
        "source_account_id": 1,
        "source_account_name": "입출금통장",
        "source_account_number": "100-200-3000",
        "current_balance": 1_000_000,
        "recipient_name": "홍길동",
        "recipient_bank": "으뜸은행",
        "recipient_account": "200-300-4000",
        "recipient_alias": "길동",
        "amount": 50_000,
        "fee": 0,
        "total_deducted": 50_000,
        "remaining_balance": 950_000,
        "memo": None,
        "requires_otp": False,
        "warnings": [],
    }
