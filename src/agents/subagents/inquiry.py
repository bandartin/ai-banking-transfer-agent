"""
InquiryAgent — 잔액/이체내역/자동이체 조회 Sub-Agent (읽기 전용).

Supervisor 가 Send(arg={"sub_intent": "balance" | "history" | "recurring"}) 로
디스패치한다. 복합 발화("잔고 보여주고 내역도")면 같은 서브그래프가
서로 다른 sub_intent 로 병렬 fan-out 된다.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from src.agents.context import BankingContext
from src.agents.state import BankingState
from src.agents.common.tracing import traced, activity
from src.agents.common.services.balance_service import get_balance_summary
from src.models.database import db, Recipient, RecurringTransfer, TransferHistory


@traced("inquiry", "run")
def inquiry_node(state: dict, runtime: Runtime[BankingContext]) -> dict:
    user_id = state["user_id"]
    sub = state.get("sub_intent") or "balance"

    if sub == "history":
        result = _history(user_id)
    elif sub == "recurring":
        result = _recurring(user_id)
    else:
        result = _balance(user_id)

    return {
        "agent_results": [{"agent": "inquiry", "kind": sub, **result}],
        "agent_activity": [activity("inquiry", f"{sub}_done")],
    }


def _balance(user_id: int) -> dict:
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
    return {"text": "\n".join(lines), "data": summary}


def _history(user_id: int) -> dict:
    records = (
        db.session.query(TransferHistory)
        .filter(TransferHistory.user_id == user_id, TransferHistory.status == "completed")
        .order_by(TransferHistory.transferred_at.desc())
        .limit(10)
        .all()
    )
    if not records:
        return {"text": "최근 이체 내역이 없습니다.", "data": {"history": []}}

    lines = ["📜 최근 이체 내역\n"]
    history_list = []
    for r in records:
        rec: Recipient = r.recipient
        alias = r.favorite.alias if r.favorite else rec.name
        date_str = r.transferred_at.strftime("%m/%d %H:%M")
        memo_str = f" · {r.memo}" if r.memo else ""
        lines.append(f"• {date_str} | {alias} ({rec.bank_name}) | {r.amount:,}원{memo_str}")
        history_list.append({
            "id": r.id,
            "alias": alias,
            "name": rec.name,
            "bank": rec.bank_name,
            "amount": r.amount,
            "fee": r.fee,
            "memo": r.memo,
            "transferred_at": r.transferred_at.isoformat(),
        })
    return {"text": "\n".join(lines), "data": {"history": history_list}}


def _recurring(user_id: int) -> dict:
    rts = (
        db.session.query(RecurringTransfer)
        .filter(RecurringTransfer.user_id == user_id, RecurringTransfer.is_active == True)
        .all()
    )
    if not rts:
        return {"text": "등록된 자동이체가 없습니다.", "data": {"recurring": []}}

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
        })
    return {"text": "\n".join(lines), "data": {"recurring": rt_list}}


def build_inquiry_subgraph():
    g = StateGraph(BankingState)
    g.add_node("run", inquiry_node)
    g.add_edge(START, "run")
    g.add_edge("run", END)
    return g.compile()
