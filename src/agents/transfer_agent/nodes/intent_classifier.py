"""
intent_classifier node — determines the user's intent for this turn.

Also handles multi-turn state: if a confirmation or OTP response is expected,
the node routes accordingly without running the general classifier.
"""

from __future__ import annotations

from flask import current_app

from src.agents.transfer_agent.services.llm_service import (
    classify_intent_deterministic,
    classify_intent_llm,
    is_confirmation,
    is_cancellation,
)


def classify_intent_node(state: dict) -> dict:
    """LangGraph node: classify the current message intent."""
    trace = list(state.get("graph_trace", []))
    trace.append("classify_intent")

    message = state.get("current_message", "").strip()
    pending = state.get("pending_state", "none")

    # ── Multi-turn: confirmation expected ────────────────────────────────────
    if pending == "awaiting_confirmation":
        if is_confirmation(message):
            return {"intent": "confirm_transfer", "graph_trace": trace}
        if is_cancellation(message):
            return {"intent": "cancel_transfer", "graph_trace": trace}
        # Anything else while awaiting confirmation → treat as new intent
        # (user changed their mind or sent a new request)

    # ── Multi-turn: OTP expected ─────────────────────────────────────────────
    if pending == "awaiting_otp":
        # Any 6-digit sequence is treated as an OTP attempt
        import re
        if re.fullmatch(r"\d{6}", message):
            return {"intent": "otp_response", "otp_code": message, "graph_trace": trace}

    # ── Multi-turn: clarification expected ──────────────────────────────────
    if pending == "awaiting_clarification":
        # The response is handled in recipient_resolver; pass through
        return {"intent": "clarification_response", "graph_trace": trace}

    # ── Fresh classification ─────────────────────────────────────────────────
    provider = current_app.config.get("LLM_PROVIDER", "deterministic")
    if provider == "deterministic":
        intent = classify_intent_deterministic(message)
    else:
        intent = classify_intent_llm(message)

    return {
        "intent": intent,
        "graph_trace": trace,
        # Reset turn-scoped fields when a fresh request starts
        "validation_passed": False,
        "validation_errors": [],
        "validation_warnings": [],
        "transfer_executed": False,
        "transfer_id": None,
        "new_balance": None,
    }
