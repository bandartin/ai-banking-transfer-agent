"""
LangGraph state definition for the transfer agent.

The state is a TypedDict that flows through every graph node.  Between
conversational turns the relevant subset is persisted as JSON in ``chat_sessions``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class TransferState(TypedDict, total=False):
    # ── Session identification ────────────────────────────────────────────────
    user_id: int
    session_id: str

    # ── Current turn input ───────────────────────────────────────────────────
    current_message: str

    # ── Intent classification ────────────────────────────────────────────────
    # "transfer" | "balance_inquiry" | "history_inquiry"
    # | "recommendation" | "recurring_inquiry"
    # | "confirm_transfer" | "cancel_transfer" | "otp_response"
    # | "unknown"
    intent: str

    # ── Extracted slots ──────────────────────────────────────────────────────
    recipient_alias: Optional[str]   # e.g. "엄마", "민수"
    amount: Optional[int]            # KRW integer
    memo: Optional[str]
    use_last_transfer: bool
    recurring_hint: Optional[str]    # e.g. "월세", "관리비"
    otp_code: Optional[str]          # entered OTP code

    # ── Recipient resolution ─────────────────────────────────────────────────
    resolved_recipient_id: Optional[int]
    resolved_favorite_id: Optional[int]
    candidate_recipients: List[Dict[str, Any]]  # for ambiguity display
    is_ambiguous: bool

    # ── Multi-turn pending state ─────────────────────────────────────────────
    # "none" | "awaiting_clarification" | "awaiting_confirmation" | "awaiting_otp"
    pending_state: str
    pending_transfer_data: Optional[Dict[str, Any]]  # TransferSummary as dict

    # ── Validation ───────────────────────────────────────────────────────────
    validation_passed: bool
    validation_errors: List[str]
    validation_warnings: List[str]

    # ── Execution result ─────────────────────────────────────────────────────
    transfer_executed: bool
    transfer_id: Optional[int]
    new_balance: Optional[int]

    # ── Response ─────────────────────────────────────────────────────────────
    # "message" | "confirmation" | "ambiguity" | "success" | "error"
    # | "balance" | "history" | "recommendation" | "otp_request"
    response_type: str
    response_text: str
    response_data: Optional[Dict[str, Any]]  # extra payload for the UI

    # ── Debug / tracing ──────────────────────────────────────────────────────
    debug_info: Dict[str, Any]
    graph_trace: List[str]  # ordered list of node names executed this turn


def initial_state(user_id: int, session_id: str) -> TransferState:
    """Return a fresh agent state for a new session."""
    return TransferState(
        user_id=user_id,
        session_id=session_id,
        current_message="",
        intent="",
        recipient_alias=None,
        amount=None,
        memo=None,
        use_last_transfer=False,
        recurring_hint=None,
        otp_code=None,
        resolved_recipient_id=None,
        resolved_favorite_id=None,
        candidate_recipients=[],
        is_ambiguous=False,
        pending_state="none",
        pending_transfer_data=None,
        validation_passed=False,
        validation_errors=[],
        validation_warnings=[],
        transfer_executed=False,
        transfer_id=None,
        new_balance=None,
        response_type="message",
        response_text="",
        response_data=None,
        debug_info={},
        graph_trace=[],
    )


# Keys that should be persisted between conversational turns
PERSISTENT_KEYS = {
    "user_id",
    "session_id",
    "pending_state",
    "pending_transfer_data",
    "candidate_recipients",
    "resolved_recipient_id",
    "resolved_favorite_id",
    "recipient_alias",
    "amount",
    "memo",
    "is_ambiguous",
}
