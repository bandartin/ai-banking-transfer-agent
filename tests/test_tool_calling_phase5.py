"""Phase 5 regression tests for the LangChain tool-calling path."""

from __future__ import annotations

import os

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from config import Config
from src.agents.context import BankingContext
from src.agents.subagents.tool_agent import _handoff_if_transfer_prep_ready
from src.agents.tool_calling.runner import run_langchain_tool_agent
from src.agents.common.services import recipient_service


class ToolCallingFakeModel(FakeMessagesListChatModel):
    """Fake chat model that supports LangChain agent tool binding."""

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self


def _ctx(*, transfer_prep: bool = False) -> BankingContext:
    return BankingContext(
        user_id=1,
        session_id="tool-phase5",
        llm_provider="openai",
        openai_api_key="sk-test",
        tool_calling_enabled=True,
        tool_calling_transfer_prep_enabled=transfer_prep,
        openai_tool_model="gpt-test",
    )


def test_phase5_langchain_runner_calls_balance_tool_without_openai(app):
    model = ToolCallingFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{"name": "get_balance_summary", "args": {}, "id": "call-balance"}],
            ),
            AIMessage(content="잔액 요약입니다."),
        ]
    )
    state = {"user_id": 1, "session_id": "tool-phase5-balance", "current_message": "잔고 보여줘"}

    with app.app_context():
        update = run_langchain_tool_agent(_ctx(), state, llm=model)

    result = update["agent_results"][0]
    audit_events = result["data"]["tool_audit_events"]
    assert result["kind"] == "balance"
    assert result["text"] == "잔액 요약입니다."
    assert audit_events[0]["tool_name"] == "get_balance_summary"
    assert audit_events[0]["side_effect"] == "read"
    assert audit_events[0]["status"] == "completed"


def test_phase5_langchain_runner_prepares_transfer_and_handoff(app):
    state = {"user_id": 1, "session_id": "tool-phase5-transfer", "current_message": "엄마에게 5만원 보내줘"}
    with app.app_context():
        recipient = recipient_service.find_by_alias(1, "엄마")[0]
        model = ToolCallingFakeModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "resolve_transfer_recipient",
                            "args": {"recipient_alias": "엄마", "bank_hint": None},
                            "id": "call-resolve",
                        }
                    ],
                ),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "prepare_transfer_summary",
                            "args": {
                                "recipient_id": recipient["recipient_id"],
                                "favorite_id": recipient.get("favorite_id"),
                                "recipient_alias": "엄마",
                                "amount": 50_000,
                                "memo": None,
                                "source_account_hint": None,
                            },
                            "id": "call-prepare",
                        }
                    ],
                ),
                AIMessage(content="확인 단계로 넘길 준비가 되었습니다."),
            ]
        )
        update = run_langchain_tool_agent(_ctx(transfer_prep=True), state, allow_transfer_prep=True, llm=model)

    command = _handoff_if_transfer_prep_ready(update)
    assert command.goto == "transfer"
    assert command.update["sub_intent"] == "confirm_prepared_transfer"
    assert command.update["pending_transfer_data"]["amount"] == 50_000
    audit_events = update["agent_results"][0]["data"]["tool_audit_events"]
    assert [event["tool_name"] for event in audit_events] == [
        "resolve_transfer_recipient",
        "prepare_transfer_summary",
    ]
    assert all(event["execution_allowed"] is False for event in audit_events)


def test_phase5_validation_failed_transfer_prep_does_not_handoff(app):
    state = {"user_id": 1, "session_id": "tool-phase5-validation", "current_message": "엄마에게 큰 금액 보내줘"}
    with app.app_context():
        recipient = recipient_service.find_by_alias(1, "엄마")[0]
        model = ToolCallingFakeModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "prepare_transfer_summary",
                            "args": {
                                "recipient_id": recipient["recipient_id"],
                                "favorite_id": recipient.get("favorite_id"),
                                "recipient_alias": "엄마",
                                "amount": 999_999_999_999,
                                "memo": None,
                                "source_account_hint": None,
                            },
                            "id": "call-validation",
                        }
                    ],
                ),
                AIMessage(content="검증에 실패했습니다."),
            ]
        )
        update = run_langchain_tool_agent(_ctx(transfer_prep=True), state, allow_transfer_prep=True, llm=model)

    result = update["agent_results"][0]
    assert result["kind"] == "transfer_prep"
    assert result["data"]["status"] == "validation_failed"
    assert _handoff_if_transfer_prep_ready(update) is update


def test_phase5_otel_content_capture_defaults_to_disabled():
    assert Config.TRACELOOP_TRACE_CONTENT == "false"
    assert os.environ["TRACELOOP_TRACE_CONTENT"] == "false"
    assert Config.LANGCHAIN_OTEL_INSTRUMENTATION_ENABLED is True
