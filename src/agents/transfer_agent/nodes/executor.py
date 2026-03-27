"""
executor node — executes the confirmed transfer or handles OTP verification.
"""

from __future__ import annotations

from flask import current_app

from src.agents.transfer_agent.schemas import TransferSummary
from src.agents.transfer_agent.services.transfer_service import execute_transfer


def execute_transfer_node(state: dict) -> dict:
    """LangGraph node: execute a confirmed transfer."""
    trace = list(state.get("graph_trace", []))
    trace.append("execute_transfer")

    user_id: int = state["user_id"]
    pending_data: dict | None = state.get("pending_transfer_data")
    favorite_id: int | None = state.get("resolved_favorite_id")
    debug = dict(state.get("debug_info", {}))

    if not pending_data:
        return {
            "transfer_executed": False,
            "response_type": "error",
            "response_text": "이체 정보가 없습니다. 처음부터 다시 시도해 주세요.",
            "pending_state": "none",
            "pending_transfer_data": None,
            "debug_info": debug,
            "graph_trace": trace,
        }

    summary = TransferSummary(**pending_data)
    result = execute_transfer(user_id, summary, favorite_id=favorite_id)
    debug["execution_result"] = result.model_dump()

    if result.success:
        return {
            "transfer_executed": True,
            "transfer_id": result.transfer_id,
            "new_balance": result.new_balance,
            "pending_state": "none",
            "pending_transfer_data": None,
            "response_type": "success",
            # Pass a snapshot so generate_response can build the success message
            "response_data": {
                **summary.model_dump(),
                "transfer_id": result.transfer_id,
                "new_balance": result.new_balance,
            },
            "debug_info": debug,
            "graph_trace": trace,
        }
    else:
        return {
            "transfer_executed": False,
            "pending_state": "none",
            "pending_transfer_data": None,
            "response_type": "error",
            "response_text": result.error_message or "이체 처리 중 오류가 발생했습니다.",
            "debug_info": debug,
            "graph_trace": trace,
        }


def verify_otp_node(state: dict) -> dict:
    """LangGraph node: verify mock OTP before execution."""
    trace = list(state.get("graph_trace", []))
    trace.append("verify_otp")

    otp_code: str = state.get("otp_code", "").strip()
    expected: str = current_app.config.get("DEMO_OTP_CODE", "123456")

    if otp_code == expected:
        return {
            "pending_state": "confirmed_after_otp",
            "graph_trace": trace,
        }
    else:
        return {
            "response_type": "otp_request",
            "response_text": "OTP 번호가 올바르지 않습니다. 다시 입력해 주세요.\n(데모 OTP: 123456)",
            "pending_state": "awaiting_otp",
            "graph_trace": trace,
        }
