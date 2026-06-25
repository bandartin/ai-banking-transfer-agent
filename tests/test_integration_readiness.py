"""Tests for AWX/IBK readiness guardrails and adapter contracts."""

import json

import pytest

from scripts.check_awx_readiness import (
    CheckResult,
    _check_awx_mcp_rollout,
    _build_readiness_report,
    _check_dependency_pin,
    _check_tool_calling_rollout,
    _check_trace_content_policy,
    _write_report,
)
from src.agents.context import BankingContext
from src.agents.common.schemas import TransferSummary
from src.agents.subagents.transfer import _execution_request
from src.agents.supervisor.planner import rule_plan
from src.integrations.awx_knowledge_adapter import normalize_awx_knowledge_response
from src.integrations.factory import validate_runtime_configuration
from src.integrations.knowledge_guard import assess_knowledge_query


def test_knowledge_guard_blocks_customer_authoritative_values():
    decision = assess_knowledge_query("내 잔액 얼마야?", collection="menu_catalog")

    assert decision.allowed is False
    assert "실시간 은행 연계" in decision.reason


def test_knowledge_guard_allows_menu_questions_about_limits():
    decision = assess_knowledge_query("이체한도 변경 메뉴 어디 있어?", collection="menu_catalog")

    assert decision.allowed is True


def test_awx_knowledge_normalizer_accepts_common_payload_shapes():
    raw = {
        "results": [
            {
                "chunkId": "c-1",
                "documentTitle": "이체한도 관리",
                "page_content": "전체메뉴 > 보안/인증 > 이체한도 관리",
                "relevanceScore": "0.91",
                "metadata": {
                    "source_uri": "awx://doc/limit",
                    "document_version": "2026.06",
                    "menu_path": "전체메뉴 > 보안/인증 > 이체한도 관리",
                },
            }
        ]
    }

    chunks = normalize_awx_knowledge_response(raw, collection="menu_catalog")

    assert len(chunks) == 1
    assert chunks[0].chunk_id == "c-1"
    assert chunks[0].title == "이체한도 관리"
    assert chunks[0].score == pytest.approx(0.91)
    assert chunks[0].metadata["menu_path"] == "전체메뉴 > 보안/인증 > 이체한도 관리"


def test_live_execution_cannot_use_mock_adapter():
    with pytest.raises(RuntimeError, match="live cannot run with BANKING_ADAPTER=mock"):
        validate_runtime_configuration(adapter_name="mock", execution_mode="live")


def test_financial_calculation_route_wins_over_product_words():
    plan = rule_plan(
        BankingContext(user_id=1, session_id="t"),
        "예금 1,000만원을 연 3.5%로 12개월 넣으면 이자 계산해줘",
    )

    assert [s.agent for s in plan.steps] == ["financial_calculator"]
    assert plan.primary_intent == "financial_calculator"


def test_transfer_execution_request_idempotency_key_is_snapshot_based():
    ctx = BankingContext(user_id=1, session_id="sid")
    state = {"session_id": "sid", "resolved_recipient_id": 10}
    summary = TransferSummary(
        source_account_id=1,
        source_account_name="주계좌",
        source_account_number="024-01-0123456",
        current_balance=1_000_000,
        recipient_name="이순자",
        recipient_bank="한빛은행",
        recipient_account="1002-123-456789",
        recipient_alias="엄마",
        amount=50_000,
        fee=500,
        total_deducted=50_500,
        remaining_balance=949_500,
    )

    first = _execution_request(ctx, state, summary)
    second = _execution_request(ctx, state, summary)
    changed = _execution_request(ctx, state, summary.model_copy(update={"amount": 60_000, "total_deducted": 60_500}))

    assert first.idempotency_key == second.idempotency_key
    assert first.idempotency_key != changed.idempotency_key


def test_readiness_trace_content_policy_blocks_payload_capture():
    result = _check_trace_content_policy(
        {
            "LANGCHAIN_OTEL_INSTRUMENTATION_ENABLED": "true",
            "TRACELOOP_TRACE_CONTENT": "true",
        }
    )

    assert result.status == "error"
    assert "TRACELOOP_TRACE_CONTENT=true" in result.detail


def test_readiness_tool_calling_rollout_warns_for_transfer_prep():
    result = _check_tool_calling_rollout(
        {
            "TOOL_CALLING_ENABLED": "true",
            "TOOL_CALLING_TRANSFER_PREP_ENABLED": "true",
            "TRANSFER_EXECUTION_MODE": "dry_run",
        }
    )

    assert result.status == "warning"
    assert "Transfer-prep tools are enabled" in result.detail


def test_readiness_langchain_instrumentation_dependency_is_pinned():
    result = _check_dependency_pin("opentelemetry-instrumentation-langchain")

    assert result.status == "ok"
    assert "==" in result.detail


def test_readiness_awx_mcp_rollout_warns_when_enabled_without_allowlist():
    result = _check_awx_mcp_rollout(
        {
            "TOOL_CALLING_ENABLED": "true",
            "TOOL_CALLING_AWX_MCP_ENABLED": "true",
            "TOOL_CALLING_AWX_MCP_ALLOWLIST": "",
        }
    )

    assert result.status == "warning"
    assert "ALLOWLIST is empty" in result.detail


def test_readiness_awx_mcp_rollout_rejects_execute_side_effect():
    result = _check_awx_mcp_rollout(
        {
            "TOOL_CALLING_ENABLED": "true",
            "TOOL_CALLING_AWX_MCP_ENABLED": "true",
            "TOOL_CALLING_AWX_MCP_ALLOWLIST": '{"awx_execute_transfer": "execute"}',
        }
    )

    assert result.status == "error"
    assert "only read and prepare are allowed" in result.detail


def test_readiness_report_sanitizes_local_and_credential_details(tmp_path):
    checks = [
        CheckResult("AWX credential metadata", "ok", "service_id=portal-secret-id"),
        CheckResult("Python runtime", "ok", r"C:\Users\83180\AppData\Local\uv\python.exe"),
        CheckResult("Trace content policy", "ok", "TRACELOOP_TRACE_CONTENT=false"),
    ]

    report = _build_readiness_report(
        checks,
        strict=False,
        env={
            "AWX_CREDENTIAL_SERVICE_ID": "portal-secret-id",
            "TRACELOOP_TRACE_CONTENT": "false",
            "TOOL_CALLING_ENABLED": "true",
        },
        exit_code=0,
    )
    path = _write_report(tmp_path / "readiness.json", report)
    text = path.read_text(encoding="utf-8")
    payload = json.loads(text)

    assert "portal-secret-id" not in text
    assert r"C:\Users\83180" not in text
    assert payload["schema_version"] == "tool_calling_readiness_report.v1"
    assert payload["checks"][0]["detail"] == "service_id=(present)"
    assert payload["checks"][1]["detail"] == "Python runtime path verified."
    assert payload["runtime_flags"]["TRACELOOP_TRACE_CONTENT"] == "false"
