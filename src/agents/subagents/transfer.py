"""
TransferAgent — 자연어 이체 Sub-Agent.

[최신 기능 적용]
  · interrupt() / Command(resume=)  : 되묻기·확인·OTP 를 정식 Human-in-the-Loop 로 구현
  · Command(goto=)                  : 노드가 다음 노드를 동적으로 지목 (그래프 내 핸드오프)
  · Command(graph=Command.PARENT)   : 확인 대기 중 새 요청이 오면 Supervisor 의
                                      plan 노드로 제어를 반납 (계층 간 핸드오프)
  · A2A 협업                        : 확인 카드 직전에 SecurityAgent 서브그래프를
                                      직접 invoke 해 리스크 평가를 의뢰

[되묻기 + 호칭 학습]
  · 별칭이 여러 명과 일치("민수")        → 후보 제시 → 선택 결과를 AliasMemory 에 학습
  · 별칭을 모름("여친")                  → 후보 제시/이름 되묻기 → 선택 결과 학습
  · 다음 세션부터 "여친한테 5만원" 즉시 해석 (learned alias)
  · 같은 호칭이 다른 사람으로 재지정되면 매핑 자동 갱신

흐름:
  extract → resolve ─┬→ clarify(되묻기 interrupt) ↺ resolve
                     ├→ ask_amount(금액 interrupt)
                     └→ validate_and_secure → confirm(확인 interrupt)
                            └ SecurityAgent 협업      ├→ otp(OTP interrupt) → execute
                                                      ├→ execute → compose
                                                      └→ [새 요청] PARENT.plan 핸드오프
"""

from __future__ import annotations

import hashlib
import re
from typing import Literal, Optional

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt

from src.agents.context import BankingContext
from src.agents.state import BankingState
from src.agents.common import parsing
from src.agents.common import llm as llm_helper
from src.agents.common.schemas import TransferSummary
from src.agents.common.tracing import traced, activity
from src.agents.common.services import alias_service, recipient_service
from src.agents.common.services.transfer_service import (
    build_transfer_summary,
    execute_transfer,
    resolve_source_account,
    validate_transfer,
)
from src.integrations.dtos import TransferExecutionRequest
from src.agents.supervisor.prompts import build_slot_prompt


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _mask(account_number: str) -> str:
    if not account_number:
        return "****"
    clean = account_number.replace("-", "")
    return f"****{clean[-4:]}" if len(clean) > 4 else account_number


def _cancelled_update() -> dict:
    return {
        "response_type": "cancelled",
        "response_text": "이체를 취소했습니다. 다른 도움이 필요하시면 말씀해 주세요.",
        "pending_transfer_data": None,
        "agent_activity": [activity("transfer", "cancelled")],
    }


def _candidates_payload(candidates: list[dict]) -> list[dict]:
    return [
        {
            "index": i + 1,
            "favorite_id": c.get("favorite_id"),
            "recipient_id": c["recipient_id"],
            "alias": c.get("alias"),
            "name": c.get("name"),
            "bank_name": c.get("bank_name"),
            "account_number": c.get("account_number"),
        }
        for i, c in enumerate(candidates)
    ]


def _select_candidate(reply: str, candidates: list[dict]) -> Optional[dict]:
    """번호 또는 이름으로 후보를 고른다."""
    m = re.search(r"^(\d+)", reply.strip())
    if m:
        idx = int(m.group(1))
        for c in candidates:
            if c.get("index") == idx:
                return c
    reply_l = reply.lower()
    for c in candidates:
        for key in (c.get("alias"), c.get("name")):
            if key and key.lower() in reply_l:
                return c
    return None


def _ordinal_from_text(text: str) -> Optional[int]:
    text = text.strip()
    m = re.search(r"(\d+)\s*(?:번|번째)", text)
    if m:
        return int(m.group(1))

    ordinal_patterns = [
        (r"첫\s*(?:번|번째|째)", 1),
        (r"(?:두|둘)\s*(?:번|번째|째)", 2),
        (r"(?:세|셋)\s*(?:번|번째|째)", 3),
        (r"(?:네|넷)\s*(?:번|번째|째)", 4),
        (r"다섯\s*(?:번|번째|째)", 5),
    ]
    for pattern, idx in ordinal_patterns:
        if re.search(pattern, text):
            return idx

    if re.search(r"그\s*사람|그분|방금|추천한\s*사람|내역대로|그대로", text):
        return 1
    return None


def _select_followup_item(state: dict) -> tuple[Optional[dict], str]:
    """Resolve short follow-up references like '1번' against recent read results."""
    message = state.get("current_message", "")
    alias = state.get("recipient_alias") or ""
    idx = _ordinal_from_text(f"{message} {alias}")
    if not idx:
        return None, ""

    recommendations = state.get("last_recommendations") or []
    history_items = state.get("last_history_items") or []
    source = state.get("last_followup_source") or ""

    if re.search(r"추천|보낼\s*만한", message):
        source = "recommendations"
    elif re.search(r"내역|거래|기록|다시|그대로|내역대로", message):
        source = "history"

    if source == "history" and idx <= len(history_items):
        return history_items[idx - 1], "history"
    if source == "recommendations" and idx <= len(recommendations):
        return recommendations[idx - 1], "recommendations"
    if idx <= len(recommendations):
        return recommendations[idx - 1], "recommendations"
    if idx <= len(history_items):
        return history_items[idx - 1], "history"
    return None, ""


def _filter_by_bank_hint(candidates: list[dict], bank_hint: Optional[str]) -> list[dict]:
    if not bank_hint:
        return candidates
    hint = bank_hint.strip().lower()
    matched = [c for c in candidates if hint in (c.get("bank_name") or "").lower()]
    return matched or candidates


def _amount_from_balance_reference(message: str, summary: Optional[dict]) -> Optional[int]:
    if not summary or not re.search(r"가능한\s*만큼|남은\s*한도|최대한|최대\s*금액", message):
        return None

    candidates = [
        summary.get("daily_remaining"),
        summary.get("single_transfer_limit"),
    ]
    accounts = summary.get("accounts") or []
    primary = next((a for a in accounts if a.get("is_primary")), accounts[0] if accounts else None)
    if primary:
        candidates.append(primary.get("balance"))

    positive = [int(v) for v in candidates if isinstance(v, int) and v > 0]
    return min(positive) if positive else None


# ─────────────────────────────────────────────────────────────────────────────
# Node 1 — extract: 슬롯 추출 (LLM 이해, 결정론 폴백)
# ─────────────────────────────────────────────────────────────────────────────


@traced("transfer", "entry")
def entry_node(state: dict, runtime: Runtime[BankingContext]) -> Command[Literal["confirm", "extract"]]:
    if state.get("sub_intent") == "confirm_prepared_transfer" and state.get("pending_transfer_data"):
        data = state.get("pending_transfer_data") or {}
        return Command(
            goto="confirm",
            update={
                "agent_activity": [
                    activity(
                        "transfer",
                        "prepared_confirmation",
                        {
                            "source": "tool_agent",
                            "amount": data.get("amount"),
                            "recipient": data.get("recipient_name"),
                        },
                    )
                ]
            },
        )
    return Command(goto="extract")


@traced("transfer", "extract")
def extract_node(state: dict, runtime: Runtime[BankingContext]) -> dict:
    ctx = runtime.context
    message = state.get("current_message", "")

    known = [m["alias"] for m in alias_service.list_for_user(ctx.user_id)]
    followup_memory = {
        "last_recommendations": state.get("last_recommendations", []),
        "last_history_items": state.get("last_history_items", []),
        "last_balance_summary": state.get("last_balance_summary"),
    }
    slots = llm_helper.extract_slots(ctx, message, build_slot_prompt(ctx, known, followup_memory))
    amount = slots.amount or _amount_from_balance_reference(message, state.get("last_balance_summary"))
    slot_debug = slots.model_dump()
    if amount and amount != slots.amount:
        slot_debug["amount"] = amount
        slot_debug["amount_source"] = "last_balance_summary"

    return {
        "recipient_alias": slots.recipient_alias,
        "amount": amount,
        "memo": slots.memo,
        "use_last_transfer": slots.use_last_transfer,
        "recurring_hint": slots.recurring_hint,
        "bank_hint": slots.bank_hint,
        "source_account_hint": slots.source_account_hint,
        "debug_info": {**state.get("debug_info", {}), "extracted_slots": slot_debug},
        "agent_activity": [activity("transfer", "start", {"slots": {k: v for k, v in slot_debug.items() if v is not None}})],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Node 2 — resolve: 수신자 해석 (즐겨찾기 → 호칭 메모리 → 되묻기)
# ─────────────────────────────────────────────────────────────────────────────


@traced("transfer", "resolve")
def resolve_node(state: dict, runtime: Runtime[BankingContext]) -> Command[Literal["clarify", "ask_amount", "validate_and_secure", "compose"]]:
    ctx = runtime.context
    user_id = state["user_id"]

    followup_item, followup_source = _select_followup_item(state)
    if followup_item and followup_item.get("recipient_id"):
        amount = state.get("amount")
        if not amount and followup_source == "history":
            amount = followup_item.get("amount")
        if not amount and followup_source == "recommendations":
            amount = followup_item.get("suggested_amount")

        updates = {
            "resolved_recipient_id": followup_item["recipient_id"],
            "resolved_favorite_id": followup_item.get("favorite_id"),
            "recipient_alias": followup_item.get("alias") or followup_item.get("name"),
            "amount": amount,
            "memo": state.get("memo") or (followup_item.get("memo") if followup_source == "history" else None),
            "agent_activity": [activity("transfer", "resolved", {
                "source": f"last_{followup_source}",
                "name": followup_item.get("name") or followup_item.get("alias"),
            })],
        }
        next_state = {**state, **updates}
        return Command(goto=_next_after_resolution(next_state), update=updates)

    # ── "지난번처럼" ─────────────────────────────────────────────────────────
    if state.get("use_last_transfer"):
        last = recipient_service.find_last_transfer(user_id)
        if last:
            return Command(goto="ask_amount" if not (state.get("amount") or last.get("amount")) else "validate_and_secure", update={
                "resolved_recipient_id": last["recipient_id"],
                "resolved_favorite_id": last.get("favorite_id"),
                "recipient_alias": last.get("alias"),
                "amount": state.get("amount") or last.get("amount"),
                "memo": state.get("memo") or last.get("memo"),
                "agent_activity": [activity("transfer", "resolved", {"source": "last_transfer", "name": last.get("name")})],
            })
        return Command(goto="compose", update={
            "response_type": "error",
            "response_text": "최근 이체 내역을 찾을 수 없습니다. 수신자와 금액을 직접 알려주세요.",
        })

    # ── 정기이체 힌트 (월세, 관리비 …) ──────────────────────────────────────
    recurring_hint = state.get("recurring_hint")
    if recurring_hint:
        rt = recipient_service.find_by_recurring_hint(user_id, recurring_hint)
        if rt and rt.get("recipient_id"):
            return Command(goto="validate_and_secure", update={
                "resolved_recipient_id": rt["recipient_id"],
                "resolved_favorite_id": rt.get("favorite_id"),
                "recipient_alias": rt.get("alias"),
                "amount": state.get("amount") or rt.get("default_amount"),
                "memo": state.get("memo") or rt.get("memo"),
                "agent_activity": [activity("transfer", "resolved", {"source": "recurring", "alias": rt.get("alias")})],
            })

    # ── 별칭/호칭 해석 ───────────────────────────────────────────────────────
    alias = state.get("recipient_alias")
    if alias:
        matches = recipient_service.find_by_alias(user_id, alias)
        matches = _filter_by_bank_hint(matches, state.get("bank_hint"))

        if len(matches) == 1:
            m = matches[0]
            return Command(goto=_next_after_resolution(state), update={
                "resolved_recipient_id": m["recipient_id"],
                "resolved_favorite_id": m.get("favorite_id"),
                "recipient_alias": m.get("alias") or alias,
                "agent_activity": [activity("transfer", "resolved", {"source": "favorite", "name": m.get("name")})],
            })

        if len(matches) > 1:
            # 동일 별칭 다수 — 이전 학습(호칭 메모리)이 후보 중 하나를 가리키면 그대로 사용
            mem = alias_service.lookup(user_id, alias)
            if mem and any(c["recipient_id"] == mem["recipient_id"] for c in matches):
                return Command(goto=_next_after_resolution(state), update={
                    "resolved_recipient_id": mem["recipient_id"],
                    "resolved_favorite_id": mem.get("favorite_id"),
                    "recipient_alias": alias,
                    "alias_learned_from": alias,
                    "agent_activity": [activity("transfer", "resolved", {
                        "source": "alias_memory", "name": mem["name"],
                        "note": f"지난번 선택 기억 (사용 {mem['hit_count']}회)",
                    })],
                })
            return Command(goto="clarify", update={
                "clarify_mode": "ambiguity",
                "candidate_recipients": _candidates_payload(matches),
            })

        # 즐겨찾기에 없음 → 호칭 학습 메모리 조회 ("여친" → 김서연)
        mem = alias_service.lookup(user_id, alias)
        if mem:
            return Command(goto=_next_after_resolution(state), update={
                "resolved_recipient_id": mem["recipient_id"],
                "resolved_favorite_id": mem.get("favorite_id"),
                "recipient_alias": alias,
                "alias_learned_from": alias,
                "agent_activity": [activity("transfer", "resolved", {
                    "source": "alias_memory", "name": mem["name"],
                    "note": f"학습된 호칭 '{alias}' → {mem['name']} (사용 {mem['hit_count']}회)",
                })],
            })

        # 모르는 호칭 → 되묻기 + 학습 대상으로 표시
        suggestions = recipient_service.get_top_recipients(user_id, limit=5)
        return Command(goto="clarify", update={
            "clarify_mode": "unknown_alias",
            "candidate_recipients": _candidates_payload(suggestions),
        })

    # ── 수신자 자체가 없음 → 되묻기 ─────────────────────────────────────────
    suggestions = recipient_service.get_top_recipients(user_id, limit=5)
    return Command(goto="clarify", update={
        "clarify_mode": "ask_recipient",
        "candidate_recipients": _candidates_payload(suggestions),
    })


def _next_after_resolution(state: dict) -> str:
    return "validate_and_secure" if state.get("amount") else "ask_amount"


# ─────────────────────────────────────────────────────────────────────────────
# Node 3 — clarify: 되묻기 (interrupt) + 호칭 학습
# ─────────────────────────────────────────────────────────────────────────────


@traced("transfer", "clarify")
def clarify_node(state: dict, runtime: Runtime[BankingContext]) -> Command[Literal["resolve", "clarify", "ask_amount", "validate_and_secure", "compose"]]:
    ctx = runtime.context
    user_id = state["user_id"]
    mode = state.get("clarify_mode", "ambiguity")
    alias = state.get("recipient_alias")
    candidates = state.get("candidate_recipients", [])

    if mode == "ambiguity":
        question = f"'{alias}'에 해당하는 수신자가 여러 명입니다. 어느 분께 보내시겠어요?"
    elif mode == "unknown_alias":
        question = (
            f"'{alias}'이(가) 누구신지 아직 몰라요. 아래에서 선택하시거나 이름을 알려주세요.\n"
            f"한 번 알려주시면 다음부터는 '{alias}'(으)로 기억해 둘게요."
        )
    else:  # ask_recipient
        question = "누구에게 보내드릴까요? 아래에서 선택하시거나 이름을 알려주세요."

    lines = [question, ""]
    for c in candidates:
        label_alias = c.get("alias") or c.get("name")
        name_part = f" ({c.get('name')})" if c.get("alias") and c.get("alias") != c.get("name") else ""
        lines.append(f"{c['index']}. {label_alias}{name_part} — {c['bank_name']} {_mask(c['account_number'])}")

    # ★ interrupt: 그래프 실행이 여기서 멈추고, 다음 사용자 메시지가
    #   Command(resume=...) 으로 이 지점에 되돌아온다.
    reply = interrupt({
        "kind": "clarification",
        "response_type": "ambiguity",
        "response_text": "\n".join(lines),
        "response_data": {"candidates": candidates, "mode": mode, "alias": alias},
    })
    reply = str(reply).strip()

    if parsing.is_cancellation(reply):
        return Command(goto="compose", update=_cancelled_update())

    # ── 후보 선택 (번호/이름) ────────────────────────────────────────────────
    selected = _select_candidate(reply, candidates)

    # ── 자유 텍스트: 이름으로 직접 알려준 경우 ("김서연이야") ────────────────
    if not selected:
        name_match = re.sub(r"(이야|이에요|예요|입니다|이요|요|야)$", "", reply).strip()
        found = recipient_service.find_by_alias(user_id, name_match) if name_match else []
        if len(found) == 1:
            selected = _candidates_payload(found)[0]

    if selected:
        updates = {
            "resolved_recipient_id": selected["recipient_id"],
            "resolved_favorite_id": selected.get("favorite_id"),
            "candidate_recipients": [],
            "clarify_mode": "",
        }
        events = [activity("transfer", "clarified", {"selected": selected.get("alias") or selected.get("name")})]

        # ★ 호칭 학습: 모르는 호칭('여친')이나 동명이인('민수') 선택 결과를 기억
        if alias and mode in ("unknown_alias", "ambiguity"):
            alias_service.learn(user_id, alias, selected["recipient_id"])
            updates["alias_learned_from"] = alias
            events.append(activity("transfer", "alias_learned", {
                "alias": alias,
                "name": selected.get("name"),
                "note": f"다음부터 '{alias}'은(는) {selected.get('name')}님으로 기억합니다",
            }))
            updates["recipient_alias"] = alias
        else:
            updates["recipient_alias"] = selected.get("alias") or selected.get("name")

        updates["agent_activity"] = events
        return Command(goto=_next_after_resolution(state), update=updates)

    # ── 새 슬롯이 담긴 답변 → 재해석 루프 ───────────────────────────────────
    slots = parsing.extract_slots(reply)
    if slots.recipient_alias or slots.amount:
        return Command(goto="resolve", update={
            "recipient_alias": slots.recipient_alias or state.get("recipient_alias"),
            "amount": slots.amount or state.get("amount"),
            "memo": slots.memo or state.get("memo"),
            "agent_activity": [activity("transfer", "reinterpret", {"reply": reply[:40]})],
        })

    # 이해 실패 → 같은 질문 반복 (interrupt 루프)
    return Command(goto="clarify")


# ─────────────────────────────────────────────────────────────────────────────
# Node 4 — ask_amount: 금액 되묻기 (interrupt)
# ─────────────────────────────────────────────────────────────────────────────


@traced("transfer", "ask_amount")
def ask_amount_node(state: dict, runtime: Runtime[BankingContext]) -> Command[Literal["ask_amount", "validate_and_secure", "compose"]]:
    alias = state.get("recipient_alias") or "수신자"

    reply = interrupt({
        "kind": "ask_amount",
        "response_type": "message",
        "response_text": f"{alias}님께 얼마를 보내드릴까요? (예: 5만원)",
        "response_data": None,
    })
    reply = str(reply).strip()

    if parsing.is_cancellation(reply):
        return Command(goto="compose", update=_cancelled_update())

    amount = parsing.parse_amount(reply)
    if amount:
        return Command(goto="validate_and_secure", update={"amount": amount})

    # 금액이 아닌 답 → 한 번 더 묻되, 새 요청이면 Supervisor 로 반납
    if parsing.classify_intent(reply) not in ("unknown", "transfer"):
        return _handoff_to_supervisor(reply, "금액 입력 대기 중 새 요청 감지")
    return Command(goto="ask_amount")


# ─────────────────────────────────────────────────────────────────────────────
# Node 5 — validate_and_secure: 결정론 검증 + SecurityAgent 협업 (A2A)
# ─────────────────────────────────────────────────────────────────────────────


@traced("transfer", "validate_and_secure")
def validate_and_secure_node(state: dict, runtime: Runtime[BankingContext]) -> Command[Literal["confirm", "compose"]]:
    from src.models.database import db, Recipient
    from src.agents.subagents.security import get_security_graph

    ctx = runtime.context
    user_id = state["user_id"]
    recipient_id = state.get("resolved_recipient_id")
    amount = state.get("amount")

    recipient = db.session.get(Recipient, recipient_id) if recipient_id else None
    if not recipient or not amount:
        return Command(goto="compose", update={
            "response_type": "error",
            "response_text": "이체 정보가 불완전합니다. 처음부터 다시 말씀해 주세요.",
        })

    source_account_id = state.get("source_account_id")
    source_account_note = None
    if not source_account_id and state.get("source_account_hint"):
        source_account_id, source_account_error = resolve_source_account(user_id, state.get("source_account_hint"))
        if source_account_error:
            return Command(goto="compose", update={
                "response_type": "error",
                "response_text": source_account_error,
                "agent_activity": [activity("transfer", "validation_failed", {"errors": [source_account_error]})],
            })
        source_account_note = state.get("source_account_hint")

    summary = build_transfer_summary(
        ctx, user_id,
        {
            "name": recipient.name,
            "bank_name": recipient.bank_name,
            "account_number": recipient.account_number,
            "alias": state.get("recipient_alias"),
        },
        amount,
        state.get("memo"),
        source_account_id=source_account_id,
    )
    if not summary:
        return Command(goto="compose", update={
            "response_type": "error", "response_text": "출금 계좌를 찾을 수 없습니다.",
        })

    result = validate_transfer(user_id, summary)
    if not result.passed:
        return Command(goto="compose", update={
            "response_type": "error",
            "response_text": "\n".join(f"⚠️ {e}" for e in result.errors),
            "validation_errors": result.errors,
            "agent_activity": [activity("transfer", "validation_failed", {"errors": result.errors})],
        })

    # ── ★ A2A 협업: SecurityAgent 서브그래프에 리스크 평가 의뢰 ─────────────
    sec_input = {
        "user_id": user_id,
        "session_id": state.get("session_id", ""),
        "pending_transfer_data": summary.model_dump(),
    }
    sec_out = get_security_graph().invoke(sec_input, context=ctx)
    assessment = sec_out.get("risk_assessment") or {}

    requires_otp = summary.requires_otp or bool(assessment.get("force_otp"))
    warnings = result.warnings + list(assessment.get("warnings", []))

    summary_dict = summary.model_dump()
    summary_dict["requires_otp"] = requires_otp
    summary_dict["warnings"] = warnings

    return Command(goto="confirm", update={
        "pending_transfer_data": summary_dict,
        "risk_assessment": assessment,
        "source_account_id": source_account_id,
        "agent_activity": (
            [activity("transfer", "security_consult", {"note": "SecurityAgent 에 리스크 평가 의뢰"})]
            + list(sec_out.get("agent_activity", []))
            + [activity("transfer", "validated", {
                "requires_otp": requires_otp,
                "source_account_hint": source_account_note,
            })]
        ),
        "node_logs": list(sec_out.get("node_logs", [])),
        "graph_trace": list(sec_out.get("graph_trace", [])),
    })


# ─────────────────────────────────────────────────────────────────────────────
# Node 6 — confirm: 이체 확인 (interrupt) — 수정/새요청까지 처리
# ─────────────────────────────────────────────────────────────────────────────


@traced("transfer", "confirm")
def confirm_node(state: dict, runtime: Runtime[BankingContext]) -> Command[Literal["otp", "execute", "validate_and_secure", "compose"]]:
    data = state.get("pending_transfer_data") or {}
    risk = state.get("risk_assessment") or {}
    requires_otp = data.get("requires_otp", False)

    alias = data.get("recipient_alias") or data.get("recipient_name", "")
    real_name = data.get("recipient_name", "")
    display_name = alias if alias == real_name else f"{alias} ({real_name})"
    fee = data.get("fee", 0)
    fee_text = f"{fee:,}원" if fee > 0 else "없음 (동일 은행)"

    text = (
        f"📋 이체 확인\n\n"
        f"출금 계좌: {data.get('source_account_name')} ({_mask(data.get('source_account_number', ''))})\n"
        f"현재 잔액: {data.get('current_balance', 0):,}원\n"
        f"────────────────\n"
        f"수신자: {display_name} · {data.get('recipient_bank')}\n"
        f"수신 계좌: {_mask(data.get('recipient_account', ''))}\n"
        f"이체 금액: {data.get('amount', 0):,}원\n"
        f"수수료: {fee_text}\n"
        f"이체 후 잔액: {data.get('remaining_balance', 0):,}원\n"
    )
    if data.get("memo"):
        text += f"메모: {data.get('memo')}\n"

    warnings = data.get("warnings") or []
    if warnings:
        text += "\n" + "\n".join(f"⚠️ {w}" for w in warnings)
    if risk.get("level") == "high":
        text += f"\n\n🚨 보안 위험도 높음 (점수 {risk.get('risk_score')}점) — 신중히 확인해 주세요."
    if requires_otp:
        text += "\n\n🔒 OTP 확인이 필요한 이체입니다. '확인'을 누르시면 OTP를 요청합니다."
    text += "\n\n이체하시겠습니까? (확인/취소)"

    reply = interrupt({
        "kind": "confirmation",
        "response_type": "confirmation",
        "response_text": text,
        "response_data": {**data, "risk": risk},
        "debug_info": state.get("debug_info", {}),
    })
    reply = str(reply).strip()

    if parsing.is_confirmation(reply):
        return Command(goto="otp" if requires_otp else "execute")

    if parsing.is_cancellation(reply):
        return Command(goto="compose", update=_cancelled_update())

    # ── 금액만 바꾸는 수정 요청 ("아니 3만원으로") ──────────────────────────
    slots = parsing.extract_slots(reply)
    if slots.amount and not slots.recipient_alias:
        return Command(goto="validate_and_secure", update={
            "amount": slots.amount,
            "agent_activity": [activity("transfer", "amount_changed", {"new_amount": slots.amount})],
        })

    # ── 그 외 = 새 요청 → ★ Supervisor(plan) 로 계층 간 핸드오프 ────────────
    return _handoff_to_supervisor(reply, "확인 대기 중 새 요청 감지 — 기존 이체 취소 후 재계획")


def _handoff_to_supervisor(message: str, note: str) -> Command:
    return Command(
        graph=Command.PARENT,
        goto="plan",
        update={
            "current_message": message,
            "pending_transfer_data": None,
            "candidate_recipients": [],
            "clarify_mode": "",
            "recipient_alias": None,
            "amount": None,
            "memo": None,
            "use_last_transfer": False,
            "recurring_hint": None,
            "bank_hint": None,
            "source_account_hint": None,
            "source_account_id": None,
            "resolved_recipient_id": None,
            "resolved_favorite_id": None,
            "agent_results": [],
            "agent_activity": [activity("transfer", "handoff_to_supervisor", {"note": note})],
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Node 7 — otp: OTP 검증 (interrupt 루프, 최대 3회)
# ─────────────────────────────────────────────────────────────────────────────


@traced("transfer", "otp")
def otp_node(state: dict, runtime: Runtime[BankingContext]) -> Command[Literal["execute", "compose"]]:
    ctx = runtime.context

    for attempt in range(1, 4):
        prefix = "" if attempt == 1 else f"OTP 번호가 올바르지 않습니다. 다시 입력해 주세요. ({attempt}/3회)\n"
        reply = interrupt({
            "kind": "otp",
            "response_type": "otp_request",
            "response_text": f"{prefix}🔒 6자리 OTP 번호를 입력해 주세요.\n(데모 OTP: {ctx.demo_otp_code})",
            "response_data": {"attempt": attempt},
        })
        reply = str(reply).strip()

        if parsing.is_cancellation(reply):
            return Command(goto="compose", update=_cancelled_update())

        if reply == ctx.demo_otp_code:
            return Command(goto="execute", update={
                "agent_activity": [activity("transfer", "otp_verified", {"attempt": attempt})],
            })

    return Command(goto="compose", update={
        "response_type": "error",
        "response_text": "OTP 인증에 3회 실패했습니다. 보안을 위해 이체를 중단합니다.",
        "pending_transfer_data": None,
        "agent_activity": [activity("transfer", "otp_failed")],
    })


# ─────────────────────────────────────────────────────────────────────────────
# Node 8 — execute: 결정론적 이체 실행
# ─────────────────────────────────────────────────────────────────────────────


@traced("transfer", "execute")
def execute_node(state: dict, runtime: Runtime[BankingContext]) -> Command[Literal["compose"]]:
    ctx = runtime.context
    user_id = state["user_id"]
    pending = state.get("pending_transfer_data")

    if not pending:
        return Command(goto="compose", update={
            "response_type": "error",
            "response_text": "이체 정보가 없습니다. 처음부터 다시 시도해 주세요.",
        })

    summary = TransferSummary(**pending)
    execution_request = _execution_request(ctx, state, summary)
    result = execute_transfer(
        user_id,
        summary,
        favorite_id=state.get("resolved_favorite_id"),
        execution_request=execution_request,
    )

    if not result.success:
        return Command(goto="compose", update={
            "response_type": "error",
            "response_text": result.error_message or "이체 처리 중 오류가 발생했습니다.",
            "pending_transfer_data": None,
        })

    # 학습된 호칭 사용 시 신뢰도 누적
    if state.get("alias_learned_from"):
        alias_service.bump(user_id, state["alias_learned_from"])

    alias = summary.recipient_alias or summary.recipient_name
    fee_text = f" (수수료 {summary.fee:,}원 포함)" if summary.fee > 0 else ""
    memo_text = f"\n메모: {summary.memo}" if summary.memo else ""
    text = (
        f"✅ 이체가 완료되었습니다!\n\n"
        f"수신자: {alias}\n"
        f"이체 금액: {summary.amount:,}원{fee_text}\n"
        f"이체 후 잔액: {result.new_balance:,}원"
        f"{memo_text}"
    )

    return Command(goto="compose", update={
        "transfer_executed": True,
        "transfer_id": result.transfer_id,
        "new_balance": result.new_balance,
        "pending_transfer_data": None,
        "response_type": "success",
        "response_text": text,
        "response_data": {
            **summary.model_dump(),
            "transfer_id": result.transfer_id,
            "new_balance": result.new_balance,
        },
        "agent_activity": [activity("transfer", "executed", {
            "transfer_id": result.transfer_id, "amount": summary.amount,
        })],
    })


def _execution_request(ctx: BankingContext, state: dict, summary: TransferSummary) -> TransferExecutionRequest:
    """Build a deterministic idempotency key for the confirmed transfer.

    The key is based on the exact data the user confirmed.  If the same resume
    message is replayed by the browser/network, the adapter can identify it as
    the same transfer request instead of executing another ledger movement.
    """
    raw = "|".join([
        str(ctx.user_id),
        state.get("session_id", ctx.session_id),
        str(summary.source_account_id),
        summary.recipient_bank,
        summary.recipient_account,
        str(summary.amount),
        str(summary.fee),
        summary.memo or "",
    ])
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return TransferExecutionRequest(
        user_id=ctx.user_id,
        session_id=state.get("session_id", ctx.session_id),
        idempotency_key=f"transfer:{digest}",
        source_account_id=summary.source_account_id,
        recipient_id=state.get("resolved_recipient_id"),
        amount=summary.amount,
        fee=summary.fee,
        memo=summary.memo,
        confirmation_snapshot=summary.model_dump(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Node 9 — compose: TransferAgent 결과를 Supervisor 에 전달
# ─────────────────────────────────────────────────────────────────────────────


@traced("transfer", "compose")
def compose_node(state: dict, runtime: Runtime[BankingContext]) -> dict:
    return {
        "agent_results": [{
            "agent": "transfer",
            "kind": state.get("response_type", "message"),
            "text": state.get("response_text", ""),
            "data": state.get("response_data"),
        }],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Graph
# ─────────────────────────────────────────────────────────────────────────────


def build_transfer_subgraph():
    g = StateGraph(BankingState)
    g.add_node("entry", entry_node)
    g.add_node("extract", extract_node)
    g.add_node("resolve", resolve_node)
    g.add_node("clarify", clarify_node)
    g.add_node("ask_amount", ask_amount_node)
    g.add_node("validate_and_secure", validate_and_secure_node)
    g.add_node("confirm", confirm_node)
    g.add_node("otp", otp_node)
    g.add_node("execute", execute_node)
    g.add_node("compose", compose_node)

    g.add_edge(START, "entry")
    g.add_edge("extract", "resolve")
    # 이후 라우팅은 각 노드의 Command(goto=…) 가 동적으로 결정
    g.add_edge("compose", END)
    return g.compile()

