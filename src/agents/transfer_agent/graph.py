"""
LangGraph transfer agent graph.

Topology
────────
start
  └─ classify_intent
       ├─ [transfer / clarification_response]
       │    └─ extract_slots  ──►  resolve_recipient
       │                               ├─ [ambiguous]     ──► generate_response ──► END
       │                               └─ [resolved / missing fields]
       │                                    └─ validate
       │                                         ├─ [failed]  ──► generate_response ──► END
       │                                         └─ [passed]  ──► generate_response ──► END
       │                                                            (sets pending_state=awaiting_confirmation)
       ├─ [confirm_transfer]
       │    └─ [requires_otp?]
       │         ├─ [yes] verify_otp
       │         │            ├─ [fail] generate_response ──► END
       │         │            └─ [ok]   execute_transfer  ──► generate_response ──► END
       │         └─ [no]  execute_transfer  ──► generate_response ──► END
       ├─ [otp_response]
       │    └─ verify_otp (same as above)
       ├─ [cancel_transfer]  ──► generate_response ──► END
       ├─ [balance_inquiry / history_inquiry / recommendation / recurring_inquiry]
       │    └─ generate_response ──► END
       └─ [unknown]  ──► generate_response ──► END

State is persisted between turns via ``ChatSession.state_json``.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from langgraph.graph import END, START, StateGraph

from src.agents.transfer_agent.state import TransferState, initial_state, PERSISTENT_KEYS
from src.agents.transfer_agent.nodes.intent_classifier import classify_intent_node
from src.agents.transfer_agent.nodes.slot_extractor import extract_slots_node
from src.agents.transfer_agent.nodes.recipient_resolver import resolve_recipient_node
from src.agents.transfer_agent.nodes.validator import validate_node
from src.agents.transfer_agent.nodes.executor import execute_transfer_node, verify_otp_node
from src.agents.transfer_agent.nodes.response_generator import generate_response_node
from src.agents.transfer_agent.run_logger import wrap_node, begin_run, end_run


# ─────────────────────────────────────────────────────────────────────────────
# Routing functions (pure — no DB access)
# ─────────────────────────────────────────────────────────────────────────────


def _route_intent(state: dict) -> str:
    intent = state.get("intent", "unknown")

    if intent == "confirm_transfer":
        return "check_otp_required"
    if intent == "otp_response":
        return "verify_otp"
    if intent == "cancel_transfer":
        return "generate_response"
    if intent in ("transfer", "clarification_response"):
        return "extract_slots"
    if intent in (
        "balance_inquiry",
        "history_inquiry",
        "recommendation",
        "recurring_inquiry",
        "unknown",
    ):
        return "generate_response"

    return "generate_response"


def _route_after_resolution(state: dict) -> str:
    if state.get("response_type") == "error":
        return "generate_response"
    if state.get("is_ambiguous"):
        return "generate_response"
    return "validate"


def _route_after_validation(state: dict) -> str:
    if not state.get("validation_passed"):
        return "generate_response"
    return "generate_response"  # confirmation card built in generate_response


def _check_otp_required(state: dict) -> str:
    """Thin pass-through node that routes to OTP or direct execution."""
    pending = state.get("pending_transfer_data") or {}
    if pending.get("requires_otp"):
        return "verify_otp"
    return "execute_transfer"


def _route_after_otp(state: dict) -> str:
    pending = state.get("pending_state", "none")
    if pending == "awaiting_otp":
        return "generate_response"  # OTP failed
    return "execute_transfer"


# ─────────────────────────────────────────────────────────────────────────────
# Thin pass-through node for OTP routing
# ─────────────────────────────────────────────────────────────────────────────


def _check_otp_required_node(state: dict) -> dict:
    """No-op node — routing is handled by the conditional edge."""
    trace = list(state.get("graph_trace", []))
    trace.append("check_otp_required")
    return {"graph_trace": trace}


# ─────────────────────────────────────────────────────────────────────────────
# Graph construction
# ─────────────────────────────────────────────────────────────────────────────


def build_transfer_graph():
    """Build and compile the transfer agent LangGraph.

    Returns a compiled ``CompiledGraph`` that can be invoked with a
    ``TransferState`` dict.
    """
    g = StateGraph(TransferState)

    # Nodes — wrapped with run_logger for per-node input/output capture
    g.add_node("classify_intent",   wrap_node("classify_intent",   classify_intent_node))
    g.add_node("extract_slots",     wrap_node("extract_slots",     extract_slots_node))
    g.add_node("resolve_recipient", wrap_node("resolve_recipient", resolve_recipient_node))
    g.add_node("validate",          wrap_node("validate",          validate_node))
    g.add_node("check_otp_required",wrap_node("check_otp_required",_check_otp_required_node))
    g.add_node("verify_otp",        wrap_node("verify_otp",        verify_otp_node))
    g.add_node("execute_transfer",  wrap_node("execute_transfer",  execute_transfer_node))
    g.add_node("generate_response", wrap_node("generate_response", generate_response_node))

    # Entry edge
    g.add_edge(START, "classify_intent")

    # classify_intent → branch by intent
    g.add_conditional_edges(
        "classify_intent",
        _route_intent,
        {
            "extract_slots": "extract_slots",
            "check_otp_required": "check_otp_required",
            "verify_otp": "verify_otp",
            "generate_response": "generate_response",
        },
    )

    # extract_slots → resolve_recipient (always)
    g.add_edge("extract_slots", "resolve_recipient")

    # resolve_recipient → ambiguous/error → response; resolved → validate
    g.add_conditional_edges(
        "resolve_recipient",
        _route_after_resolution,
        {
            "generate_response": "generate_response",
            "validate": "validate",
        },
    )

    # validate → generate_response (confirmation card or error)
    g.add_conditional_edges(
        "validate",
        _route_after_validation,
        {"generate_response": "generate_response"},
    )

    # check_otp_required → verify_otp or execute_transfer
    g.add_conditional_edges(
        "check_otp_required",
        _check_otp_required,
        {
            "verify_otp": "verify_otp",
            "execute_transfer": "execute_transfer",
        },
    )

    # verify_otp → execute_transfer (success) or generate_response (failure)
    g.add_conditional_edges(
        "verify_otp",
        _route_after_otp,
        {
            "execute_transfer": "execute_transfer",
            "generate_response": "generate_response",
        },
    )

    # execute_transfer → generate_response
    g.add_edge("execute_transfer", "generate_response")

    # generate_response → END
    g.add_edge("generate_response", END)

    return g.compile()


# Singleton compiled graph (lazily initialised inside Flask app context)
_compiled_graph = None


def _get_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_transfer_graph()
    return _compiled_graph


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────


def run_transfer_agent(
    user_id: int,
    message: str,
    session_id: str | None = None,
) -> dict:
    """
    Run one conversational turn of the transfer agent.

    Args:
        user_id:    ID of the demo user (see seed data).
        message:    Raw Korean text from the user.
        session_id: Session identifier.  A new UUID is generated if omitted.

    Returns:
        A dict with keys:
          - response_text: str — Korean text for the chat UI
          - response_type: str — rendering hint for the UI
          - response_data: dict | None — extra payload (confirmation card, etc.)
          - intent: str
          - debug_info: dict
          - graph_trace: list[str]
    """
    from src.models.database import db, ChatSession, ChatMessage

    if session_id is None:
        session_id = str(uuid.uuid4())

    # ── Load or create session state ─────────────────────────────────────────
    session = (
        db.session.query(ChatSession)
        .filter(ChatSession.session_id == session_id, ChatSession.user_id == user_id)
        .first()
    )

    if session and session.state_json:
        try:
            saved = json.loads(session.state_json)
        except (json.JSONDecodeError, TypeError):
            saved = {}
    else:
        saved = {}

    base_state = initial_state(user_id, session_id)
    # Overlay saved persistent fields
    for k in PERSISTENT_KEYS:
        if k in saved:
            base_state[k] = saved[k]  # type: ignore[literal-required]

    # Inject current message and clear per-turn fields
    base_state["current_message"] = message
    base_state["graph_trace"] = []
    base_state["debug_info"] = {}

    # ── Run the graph ─────────────────────────────────────────────────────────
    graph = _get_graph()

    from flask import current_app
    import time as _time

    langsmith_url: str | None = None
    run_token, _entries = begin_run()
    t_start = _time.monotonic()

    try:
        if current_app.config.get("LANGSMITH_ENABLED"):
            from langchain_core.callbacks import collect_runs
            with collect_runs() as cb:
                result: dict = graph.invoke(base_state)
            if cb.traced_runs:
                run_id = str(cb.traced_runs[0].id)
                project = current_app.config.get("LANGSMITH_PROJECT", "banking-transfer-agent")
                langsmith_url = f"https://smith.langchain.com/o/0/projects/p/{project}/r/{run_id}"
        else:
            result: dict = graph.invoke(base_state)
    finally:
        node_logs = end_run(run_token)

    total_ms = max(1, int((_time.monotonic() - t_start) * 1000))

    # ── Persist new state ─────────────────────────────────────────────────────
    new_persistent = {k: result.get(k) for k in PERSISTENT_KEYS}
    state_json = json.dumps(new_persistent, ensure_ascii=False, default=str)

    if not session:
        session = ChatSession(
            user_id=user_id,
            session_id=session_id,
            state_json=state_json,
        )
        db.session.add(session)
        db.session.flush()
    else:
        session.state_json = state_json

    # Save chat messages
    user_msg = ChatMessage(
        session_id=session.id,
        role="user",
        content=message,
        intent=result.get("intent"),
        slots_json=json.dumps(
            {
                "recipient_alias": result.get("recipient_alias"),
                "amount": result.get("amount"),
                "memo": result.get("memo"),
            },
            ensure_ascii=False,
        ),
    )
    assistant_msg = ChatMessage(
        session_id=session.id,
        role="assistant",
        content=result.get("response_text", ""),
        intent=result.get("intent"),
    )
    db.session.add(user_msg)
    db.session.add(assistant_msg)

    # ── Persist agent run log ─────────────────────────────────────────────────
    from src.models.database import AgentRunLog
    run_log_record = AgentRunLog(
        user_id=user_id,
        session_id=session_id,
        user_message=message,
        intent=result.get("intent", ""),
        response_type=result.get("response_type", ""),
        response_text=result.get("response_text", "")[:500],
        pending_state=result.get("pending_state", "none"),
        graph_trace=",".join(result.get("graph_trace", [])),
        node_logs_json=json.dumps(node_logs, ensure_ascii=False, default=str),
        total_duration_ms=total_ms,
        langsmith_url=langsmith_url,
    )
    db.session.add(run_log_record)
    db.session.commit()

    return {
        "response_text": result.get("response_text", ""),
        "response_type": result.get("response_type", "message"),
        "response_data": result.get("response_data"),
        "intent": result.get("intent", ""),
        "debug_info": result.get("debug_info", {}),
        "graph_trace": result.get("graph_trace", []),
        "pending_state": result.get("pending_state", "none"),
        "session_id": session_id,
        "langsmith_url": langsmith_url,
        "run_log_id": run_log_record.id,
    }
