"""
response_generator node — builds the final Korean response text and UI payload.
"""

from __future__ import annotations

from datetime import datetime
from typing import List

from src.models.database import db, TransferHistory, Recipient
from src.agents.transfer_agent.services.balance_service import get_balance_summary
from src.agents.transfer_agent.services.recommendation_service import get_recommendations
from src.agents.transfer_agent.prompts.korean_prompts import RESPONSE_TEMPLATES


def generate_response_node(state: dict) -> dict:
    """LangGraph node: produce response_text and response_data for the UI."""
    trace = list(state.get("graph_trace", []))
    trace.append("generate_response")

    intent = state.get("intent", "unknown")
    response_type = state.get("response_type", "message")
    user_id = state["user_id"]

    # ── Delegate by response_type set by earlier nodes ───────────────────────

    if response_type == "success":
        return _success_response(state, trace)

    if response_type == "error":
        # response_text already set by earlier node
        return {"graph_trace": trace}

    if response_type == "otp_request":
        return {"graph_trace": trace}

    if state.get("is_ambiguous"):
        return _ambiguity_response(state, trace)

    if state.get("validation_passed") and state.get("pending_transfer_data"):
        return _confirmation_response(state, trace)

    # ── Intent-driven responses ──────────────────────────────────────────────
    if intent == "balance_inquiry":
        return _balance_response(user_id, state, trace)

    if intent == "history_inquiry":
        return _history_response(user_id, state, trace)

    if intent == "recommendation":
        return _recommendation_response(user_id, state, trace)

    if intent == "recurring_inquiry":
        return _recurring_response(user_id, state, trace)

    if intent in ("cancel_transfer", "cancel"):
        return {
            "response_type": "message",
            "response_text": RESPONSE_TEMPLATES["transfer_cancelled"],
            "pending_state": "none",
            "pending_transfer_data": None,
            "graph_trace": trace,
        }

    if intent in ("confirm_transfer",) and not state.get("pending_transfer_data"):
        return {
            "response_type": "message",
            "response_text": RESPONSE_TEMPLATES["no_pending_transfer"],
            "graph_trace": trace,
        }

    # ── Transfer with missing fields ─────────────────────────────────────────
    if intent == "transfer":
        return _missing_fields_response(state, trace)

    # ── Fallback ─────────────────────────────────────────────────────────────
    return {
        "response_type": "message",
        "response_text": RESPONSE_TEMPLATES["unknown_intent"],
        "graph_trace": trace,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Individual response builders
# ─────────────────────────────────────────────────────────────────────────────


def _success_response(state: dict, trace: list) -> dict:
    # response_data is populated by execute_transfer_node with a summary snapshot
    data = state.get("response_data") or {}
    transfer_id = data.get("transfer_id") or state.get("transfer_id")
    new_balance = data.get("new_balance") or state.get("new_balance", 0)
    amount = data.get("amount", 0)
    fee = data.get("fee", 0)
    alias = data.get("recipient_alias") or data.get("recipient_name", "")
    memo_text = f"\n메모: {data.get('memo')}" if data.get("memo") else ""
    fee_text = f" (수수료 {fee:,}원 포함)" if fee > 0 else ""

    text = (
        f"✅ 이체가 완료되었습니다!\n\n"
        f"수신자: {alias}\n"
        f"이체 금액: {amount:,}원{fee_text}\n"
        f"이체 후 잔액: {new_balance:,}원"
        f"{memo_text}"
    )

    return {
        "response_type": "success",
        "response_text": text,
        "response_data": {
            "transfer_id": transfer_id,
            "new_balance": new_balance,
            "amount": amount,
            "fee": fee,
            "alias": alias,
        },
        "graph_trace": trace,
    }


def _ambiguity_response(state: dict, trace: list) -> dict:
    candidates = state.get("candidate_recipients", [])
    alias = state.get("recipient_alias", "")
    lines = [f"'{alias}'에 해당하는 수신자가 여러 명입니다. 어느 분께 보내시겠어요?\n"]
    for c in candidates:
        acc_masked = _mask_account(c.get("account_number", ""))
        lines.append(f"{c['index']}. {c.get('alias') or c.get('name')} — {c['bank_name']} {acc_masked}")

    return {
        "response_type": "ambiguity",
        "response_text": "\n".join(lines),
        "response_data": {"candidates": candidates},
        "pending_state": "awaiting_clarification",
        "graph_trace": trace,
    }


def _confirmation_response(state: dict, trace: list) -> dict:
    data = state.get("pending_transfer_data", {})
    warnings = state.get("validation_warnings", [])
    otp_required = data.get("requires_otp", False)
    pending_next = "awaiting_otp" if otp_required else "awaiting_confirmation"

    alias = data.get("recipient_alias") or data.get("recipient_name", "")
    fee = data.get("fee", 0)
    fee_text = f"{fee:,}원" if fee > 0 else "없음 (동일 은행)"

    warn_text = ""
    if warnings:
        warn_text = "\n\n⚠️ " + "\n⚠️ ".join(warnings)

    otp_text = "\n\n🔒 금액이 300만원 이상입니다. OTP 확인이 필요합니다." if otp_required else ""

    text = (
        f"📋 이체 확인\n\n"
        f"출금 계좌: {data.get('source_account_name')} ({_mask_account(data.get('source_account_number',''))})\n"
        f"현재 잔액: {data.get('current_balance', 0):,}원\n"
        f"────────────────\n"
        f"수신자: {alias} ({data.get('recipient_bank')})\n"
        f"수신 계좌: {_mask_account(data.get('recipient_account',''))}\n"
        f"이체 금액: {data.get('amount', 0):,}원\n"
        f"수수료: {fee_text}\n"
        f"이체 후 잔액: {data.get('remaining_balance', 0):,}원\n"
    )
    if data.get("memo"):
        text += f"메모: {data.get('memo')}\n"
    text += warn_text + otp_text

    if otp_required:
        text += "\n\n6자리 OTP를 입력해 주세요."
    else:
        text += "\n\n이체하시겠습니까? (확인/취소)"

    return {
        "response_type": "otp_request" if otp_required else "confirmation",
        "response_text": text,
        "response_data": data,
        "pending_state": pending_next,
        "graph_trace": trace,
    }


def _balance_response(user_id: int, state: dict, trace: list) -> dict:
    summary = get_balance_summary(user_id)
    lines = ["💰 계좌 잔액\n"]
    for a in summary["accounts"]:
        primary_mark = " ★" if a["is_primary"] else ""
        lines.append(f"• {a['name']}{primary_mark}: {a['balance']:,}원")

    lines.append(
        f"\n오늘 이체 가능 금액: {summary['daily_remaining']:,}원\n"
        f"(1회 한도: {summary['single_transfer_limit']:,}원 | "
        f"일일 한도: {summary['daily_limit']:,}원)"
    )
    return {
        "response_type": "balance",
        "response_text": "\n".join(lines),
        "response_data": summary,
        "graph_trace": trace,
    }


def _history_response(user_id: int, state: dict, trace: list) -> dict:
    records = (
        db.session.query(TransferHistory)
        .filter(TransferHistory.user_id == user_id, TransferHistory.status == "completed")
        .order_by(TransferHistory.transferred_at.desc())
        .limit(10)
        .all()
    )
    if not records:
        return {
            "response_type": "history",
            "response_text": "최근 이체 내역이 없습니다.",
            "response_data": {"history": []},
            "graph_trace": trace,
        }

    lines = ["📜 최근 이체 내역\n"]
    history_list = []
    for r in records:
        rec: Recipient = r.recipient
        alias = r.favorite.alias if r.favorite else rec.name
        date_str = r.transferred_at.strftime("%m/%d %H:%M")
        fee_str = f"+{r.fee:,}원 수수료" if r.fee else ""
        lines.append(f"• {date_str} | {alias} ({rec.bank_name}) | {r.amount:,}원 {fee_str}")
        history_list.append({
            "id": r.id,
            "alias": alias,
            "name": rec.name,
            "bank": rec.bank_name,
            "account": rec.account_number,
            "amount": r.amount,
            "fee": r.fee,
            "memo": r.memo,
            "status": r.status,
            "transferred_at": r.transferred_at.isoformat(),
        })

    return {
        "response_type": "history",
        "response_text": "\n".join(lines),
        "response_data": {"history": history_list},
        "graph_trace": trace,
    }


def _recommendation_response(user_id: int, state: dict, trace: list) -> dict:
    recs = get_recommendations(user_id)
    if not recs:
        return {
            "response_type": "recommendation",
            "response_text": "추천할 수신자 정보가 없습니다.",
            "response_data": {"recommendations": []},
            "graph_trace": trace,
        }

    lines = ["⭐ 추천 수신자\n"]
    rec_list = []
    for r in recs:
        amount_str = f" | 추천 금액 {r.suggested_amount:,}원" if r.suggested_amount else ""
        lines.append(f"{r.rank}. {r.alias or r.name} ({r.bank_name}){amount_str} — {r.reason}")
        rec_list.append(r.model_dump())

    return {
        "response_type": "recommendation",
        "response_text": "\n".join(lines),
        "response_data": {"recommendations": rec_list},
        "graph_trace": trace,
    }


def _recurring_response(user_id: int, state: dict, trace: list) -> dict:
    from src.models.database import RecurringTransfer
    rts = (
        db.session.query(RecurringTransfer)
        .filter(
            RecurringTransfer.user_id == user_id,
            RecurringTransfer.is_active == True,
        )
        .all()
    )
    if not rts:
        return {
            "response_type": "message",
            "response_text": "등록된 자동이체가 없습니다.",
            "graph_trace": trace,
        }

    lines = ["🔄 자동이체 목록\n"]
    rt_list = []
    for rt in rts:
        due = rt.next_due_date.strftime("%m/%d") if rt.next_due_date else "미정"
        lines.append(f"• {rt.alias}: {rt.default_amount:,}원 (매월 {rt.day_of_month}일, 다음 납부: {due})")
        rt_list.append({
            "id": rt.id,
            "alias": rt.alias,
            "amount": rt.default_amount,
            "day_of_month": rt.day_of_month,
            "next_due_date": rt.next_due_date.isoformat() if rt.next_due_date else None,
        })

    return {
        "response_type": "message",
        "response_text": "\n".join(lines),
        "response_data": {"recurring": rt_list},
        "graph_trace": trace,
    }


def _missing_fields_response(state: dict, trace: list) -> dict:
    missing = []
    if not state.get("recipient_alias") and not state.get("resolved_recipient_id"):
        missing.append("수신자")
    if not state.get("amount"):
        missing.append("이체 금액")

    if missing:
        text = f"{', '.join(missing)}를 알려주세요.\n예: 엄마에게 5만원 보내줘"
    else:
        text = "수신자를 찾지 못했습니다. 정확한 이름이나 별칭을 입력해 주세요."

    return {
        "response_type": "message",
        "response_text": text,
        "graph_trace": trace,
    }


def _mask_account(account_number: str) -> str:
    """Show only last 4 digits."""
    if not account_number:
        return "****"
    clean = account_number.replace("-", "")
    return f"****{clean[-4:]}" if len(clean) > 4 else account_number
