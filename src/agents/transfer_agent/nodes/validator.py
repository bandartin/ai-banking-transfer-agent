"""
validator node — builds the transfer summary and runs deterministic pre-checks.

If validation passes, the pending_transfer_data is populated for the
confirmation step.  On failure, an error response is prepared immediately.
"""

from __future__ import annotations

from src.models.database import db, Recipient
from src.agents.transfer_agent.services.transfer_service import (
    build_transfer_summary,
    validate_transfer,
)


def validate_node(state: dict) -> dict:
    """LangGraph node: validate the pending transfer."""
    trace = list(state.get("graph_trace", []))
    trace.append("validate")

    user_id = state["user_id"]
    recipient_id = state.get("resolved_recipient_id")
    amount = state.get("amount")
    memo = state.get("memo")

    debug = dict(state.get("debug_info", {}))

    # ── Guard: missing required fields ───────────────────────────────────────
    missing = []
    if not recipient_id:
        missing.append("수신자")
    if not amount:
        missing.append("이체 금액")

    if missing:
        return {
            "validation_passed": False,
            "validation_errors": [f"{', '.join(missing)}를 알려주세요."],
            "validation_warnings": [],
            "response_type": "error",
            "response_text": f"{', '.join(missing)}를 알려주세요.",
            "debug_info": debug,
            "graph_trace": trace,
        }

    # ── Build recipient dict ──────────────────────────────────────────────────
    recipient: Recipient | None = db.session.get(Recipient, recipient_id)
    if not recipient:
        return {
            "validation_passed": False,
            "validation_errors": ["수신자 정보를 찾을 수 없습니다."],
            "response_type": "error",
            "response_text": "수신자 정보를 찾을 수 없습니다.",
            "debug_info": debug,
            "graph_trace": trace,
        }

    recipient_data = {
        "name": recipient.name,
        "bank_name": recipient.bank_name,
        "account_number": recipient.account_number,
        "alias": state.get("recipient_alias"),
    }

    # ── Build summary ─────────────────────────────────────────────────────────
    summary = build_transfer_summary(user_id, recipient_data, amount, memo)
    if not summary:
        return {
            "validation_passed": False,
            "validation_errors": ["출금 계좌를 찾을 수 없습니다."],
            "response_type": "error",
            "response_text": "출금 계좌를 찾을 수 없습니다.",
            "debug_info": debug,
            "graph_trace": trace,
        }

    # ── Run validation ────────────────────────────────────────────────────────
    result = validate_transfer(user_id, summary)
    debug["validation_result"] = result.model_dump()

    if not result.passed:
        error_text = "\n".join(f"⚠️ {e}" for e in result.errors)
        return {
            "validation_passed": False,
            "validation_errors": result.errors,
            "validation_warnings": result.warnings,
            "pending_transfer_data": None,
            "pending_state": "none",
            "response_type": "error",
            "response_text": error_text,
            "debug_info": debug,
            "graph_trace": trace,
        }

    # ── Passed ────────────────────────────────────────────────────────────────
    return {
        "validation_passed": True,
        "validation_errors": [],
        "validation_warnings": result.warnings,
        "pending_transfer_data": summary.model_dump(),
        "debug_info": debug,
        "graph_trace": trace,
    }
