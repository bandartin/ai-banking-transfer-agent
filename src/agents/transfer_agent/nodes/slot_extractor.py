"""
slot_extractor node — extracts transfer slots from the current message.
"""

from __future__ import annotations

from flask import current_app

from src.agents.transfer_agent.services.llm_service import (
    extract_slots_deterministic,
    extract_slots_llm,
)


def extract_slots_node(state: dict) -> dict:
    """LangGraph node: extract transfer slots from the user message."""
    trace = list(state.get("graph_trace", []))
    trace.append("extract_slots")

    message = state.get("current_message", "")
    intent = state.get("intent", "")
    provider = current_app.config.get("LLM_PROVIDER", "deterministic")

    if provider == "deterministic":
        slots = extract_slots_deterministic(message)
    else:
        slots = extract_slots_llm(message)

    debug = dict(state.get("debug_info", {}))
    debug["extracted_slots"] = slots.model_dump()

    # When the user is responding to a clarification, don't overwrite previously
    # extracted slots with None — the amount/memo were set in the prior turn.
    if intent == "clarification_response":
        updates = {
            "use_last_transfer": slots.use_last_transfer,
            "recurring_hint": slots.recurring_hint,
            "debug_info": debug,
            "graph_trace": trace,
        }
        # Only update slot if newly extracted (not None)
        if slots.recipient_alias is not None:
            updates["recipient_alias"] = slots.recipient_alias
        if slots.amount is not None:
            updates["amount"] = slots.amount
        if slots.memo is not None:
            updates["memo"] = slots.memo
        return updates

    return {
        "recipient_alias": slots.recipient_alias,
        "amount": slots.amount,
        "memo": slots.memo,
        "use_last_transfer": slots.use_last_transfer,
        "recurring_hint": slots.recurring_hint,
        "debug_info": debug,
        "graph_trace": trace,
    }
