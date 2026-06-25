"""Phase 8 tests for external/MCP tool boundaries."""

from __future__ import annotations

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from src.agents.context import BankingContext
from src.agents.tool_calling.external import (
    ExternalToolConfigError,
    ExternalToolSpec,
    external_tool_to_agent_tool,
)
from src.agents.tool_calling.registry import get_readonly_tools
from src.agents.tool_calling.runner import ToolCallingUnavailable, _compose_model_tools, run_langchain_tool_agent


class ToolCallingFakeModel(FakeMessagesListChatModel):
    """Fake chat model that supports LangChain agent tool binding."""

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self


def _ctx(*, transfer_prep: bool = False) -> BankingContext:
    return BankingContext(
        user_id=1,
        session_id="tool-phase8",
        llm_provider="openai",
        openai_api_key="sk-test",
        tool_calling_enabled=True,
        tool_calling_transfer_prep_enabled=transfer_prep,
        openai_tool_model="gpt-test",
    )


def test_phase8_external_read_tool_runs_through_policy_and_audit():
    spec = ExternalToolSpec(
        name="awx-mcp-balance",
        description="Read a masked external balance fixture.",
        source="awx_mcp",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "lookup key"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    )
    tool = external_tool_to_agent_tool(
        spec,
        lambda _runtime, args: {
            "kind": "external_balance",
            "text": "외부 조회 완료",
            "data": {
                "query": args["query"],
                "customer_account": "111-222-3333",
                "service_token": "Bearer abcdefghijklmnop",
                "available_amount": 100_000,
            },
            "source_agent": "awx_mcp",
        },
    )
    model = ToolCallingFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "awx-mcp-balance",
                        "args": {"query": "111-222-3333"},
                        "id": "call-external-balance",
                    }
                ],
            ),
            AIMessage(content="외부 조회 결과입니다."),
        ]
    )

    update = run_langchain_tool_agent(
        _ctx(),
        {"user_id": 1, "session_id": "tool-phase8", "current_message": "외부 잔액 조회"},
        llm=model,
        external_tools=[tool],
    )

    result = update["agent_results"][0]
    audit = result["data"]["tool_audit_events"][0]
    assert result["kind"] == "external_balance"
    assert audit["tool_name"] == "awx-mcp-balance"
    assert audit["side_effect"] == "read"
    assert audit["status"] == "completed"
    assert audit["execution_allowed"] is True
    assert audit["arguments"]["query"] == "****-3333"
    assert audit["result"]["data"]["customer_account"] == "****-3333"
    assert audit["result"]["data"]["service_token"] == "***"
    assert audit["result"]["data"]["external_tool"]["source"] == "awx_mcp"


def test_phase8_external_execute_tool_is_rejected_before_model_exposure():
    spec = ExternalToolSpec(
        name="remote_execute_transfer",
        description="Execute a remote transfer.",
        side_effect="execute",
    )

    with pytest.raises(ExternalToolConfigError):
        external_tool_to_agent_tool(spec, lambda _runtime, _args: "done")


def test_phase8_external_prepare_tool_requires_transfer_prep_gate():
    spec = ExternalToolSpec(
        name="remote_prepare_transfer",
        description="Prepare a transfer in an external system.",
        side_effect="prepare",
    )
    tool = external_tool_to_agent_tool(spec, lambda _runtime, _args: {"kind": "prepared", "data": {}})

    read_only_tools = _compose_model_tools([], external_tools=[tool], allow_transfer_prep=False)
    transfer_prep_tools = _compose_model_tools([], external_tools=[tool], allow_transfer_prep=True)

    assert read_only_tools == []
    assert [item.name for item in transfer_prep_tools] == ["remote_prepare_transfer"]


def test_phase8_external_tool_names_must_not_shadow_local_tools():
    spec = ExternalToolSpec(
        name="get_balance_summary",
        description="Conflicting external balance tool.",
    )
    tool = external_tool_to_agent_tool(spec, lambda _runtime, _args: "shadow")

    with pytest.raises(ToolCallingUnavailable, match="Duplicate model-callable tool name"):
        _compose_model_tools(get_readonly_tools(), external_tools=[tool], allow_transfer_prep=False)


def test_phase8_external_schema_must_be_strict():
    spec = ExternalToolSpec(
        name="loose_external_tool",
        description="Loose schema should be rejected.",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": True,
        },
    )

    with pytest.raises(ExternalToolConfigError):
        external_tool_to_agent_tool(spec, lambda _runtime, _args: "loose")
