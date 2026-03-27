"""
recipient_resolver node — resolves recipient from favorites, history, or recurring.

Also handles:
  - "지난번처럼" → last transfer lookup
  - recurring hint → recurring template lookup
  - clarification response → selects from candidate list
"""

from __future__ import annotations

import re
from typing import Optional

from src.agents.transfer_agent.services import recipient_service


def resolve_recipient_node(state: dict) -> dict:
    """LangGraph node: resolve the intended recipient."""
    trace = list(state.get("graph_trace", []))
    trace.append("resolve_recipient")

    user_id: int = state["user_id"]
    message: str = state.get("current_message", "").strip()
    intent: str = state.get("intent", "")

    debug = dict(state.get("debug_info", {}))

    # ── Case 1: User is responding to an ambiguity clarification ─────────────
    if intent == "clarification_response" and state.get("pending_state") == "awaiting_clarification":
        return _handle_clarification(state, message, trace, debug)

    # ── Case 2: "지난번처럼" — infer from last transfer ──────────────────────
    if state.get("use_last_transfer"):
        last = recipient_service.find_last_transfer(user_id)
        if last:
            debug["resolution_source"] = "last_transfer"
            return {
                "resolved_recipient_id": last["recipient_id"],
                "resolved_favorite_id": last.get("favorite_id"),
                "recipient_alias": last.get("alias"),
                "amount": last.get("amount") if not state.get("amount") else state["amount"],
                "memo": last.get("memo") if not state.get("memo") else state["memo"],
                "is_ambiguous": False,
                "candidate_recipients": [],
                "debug_info": debug,
                "graph_trace": trace,
            }
        else:
            debug["resolution_source"] = "last_transfer_not_found"
            return {
                "resolved_recipient_id": None,
                "resolved_favorite_id": None,
                "is_ambiguous": False,
                "candidate_recipients": [],
                "response_type": "error",
                "response_text": "최근 이체 내역을 찾을 수 없습니다. 수신자와 금액을 직접 알려주세요.",
                "debug_info": debug,
                "graph_trace": trace,
            }

    # ── Case 3: Recurring transfer hint (월세, 관리비, …) ───────────────────
    recurring_hint = state.get("recurring_hint")
    if recurring_hint:
        rt = recipient_service.find_by_recurring_hint(user_id, recurring_hint)
        if rt and rt.get("recipient_id"):
            amount_to_use = state.get("amount") or rt.get("default_amount")
            debug["resolution_source"] = "recurring"
            return {
                "resolved_recipient_id": rt["recipient_id"],
                "resolved_favorite_id": rt.get("favorite_id"),
                "recipient_alias": rt.get("alias"),
                "amount": amount_to_use,
                "memo": state.get("memo") or rt.get("memo"),
                "is_ambiguous": False,
                "candidate_recipients": [],
                "debug_info": debug,
                "graph_trace": trace,
            }

    # ── Case 4: Alias lookup ─────────────────────────────────────────────────
    alias = state.get("recipient_alias")
    if alias:
        matches = recipient_service.find_by_alias(user_id, alias)
        debug["resolution_source"] = "alias_lookup"
        debug["alias_matches"] = len(matches)

        if len(matches) == 1:
            m = matches[0]
            return {
                "resolved_recipient_id": m["recipient_id"],
                "resolved_favorite_id": m.get("favorite_id"),
                "recipient_alias": m.get("alias") or alias,
                "is_ambiguous": False,
                "candidate_recipients": [],
                "debug_info": debug,
                "graph_trace": trace,
            }
        elif len(matches) > 1:
            candidates = [
                {**m, "index": i + 1} for i, m in enumerate(matches)
            ]
            return {
                "is_ambiguous": True,
                "candidate_recipients": candidates,
                "resolved_recipient_id": None,
                "resolved_favorite_id": None,
                "pending_state": "awaiting_clarification",
                "debug_info": debug,
                "graph_trace": trace,
            }

    # ── No recipient found ───────────────────────────────────────────────────
    return {
        "resolved_recipient_id": None,
        "resolved_favorite_id": None,
        "is_ambiguous": False,
        "candidate_recipients": [],
        "debug_info": debug,
        "graph_trace": trace,
    }


def _handle_clarification(state: dict, message: str, trace: list, debug: dict) -> dict:
    """
    The user has replied to an ambiguity question.
    Accept:
      - A digit ("1", "2", …)
      - A name substring matching one of the candidates
    """
    candidates = state.get("candidate_recipients", [])
    selected = None

    # Try digit selection
    m = re.search(r"^(\d+)", message)
    if m:
        idx = int(m.group(1))
        for c in candidates:
            if c.get("index") == idx:
                selected = c
                break

    # Try name match
    if not selected:
        for c in candidates:
            name = (c.get("alias") or c.get("name") or "").lower()
            if name and name in message.lower():
                selected = c
                break

    if not selected:
        debug["clarification_result"] = "unresolved"
        return {
            "is_ambiguous": True,
            "candidate_recipients": candidates,
            "pending_state": "awaiting_clarification",
            "response_type": "ambiguity",
            "response_text": (
                "선택을 이해하지 못했습니다. 번호(1, 2, …)로 선택해 주세요."
            ),
            "debug_info": debug,
            "graph_trace": trace,
        }

    debug["clarification_result"] = "resolved"
    return {
        "resolved_recipient_id": selected["recipient_id"],
        "resolved_favorite_id": selected.get("favorite_id"),
        "recipient_alias": selected.get("alias"),
        "is_ambiguous": False,
        "candidate_recipients": [],
        "pending_state": "none",
        "debug_info": debug,
        "graph_trace": trace,
    }
