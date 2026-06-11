"""
BankingState — Supervisor 와 모든 Sub-Agent 가 공유하는 LangGraph 상태.

병렬 fan-out(Send) 시 두 브랜치가 같은 키에 쓰면 LangGraph 는 기본(LastValue)
채널에서 오류를 냅니다. 그래서 모든 키에 reducer 를 명시합니다:

  · _replace      : 마지막 쓰기가 이김 (스칼라 키 — 병렬 브랜치는 서로 다른
                    키만 의미있게 쓰도록 설계되어 있어 안전)
  · operator.add  : 리스트 누적 (trace / 활동 로그 / 에이전트 결과 — 병렬 안전)

상태는 컴파일 시 연결한 SqliteSaver 체크포인터가 thread_id(=session_id)별로
영속화합니다. 과거의 수동 state_json 직렬화는 제거되었습니다.
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional, TypedDict


def _replace(_old: Any, new: Any) -> Any:
    """Last-write-wins reducer — 병렬 브랜치의 동일 값 쓰기를 허용."""
    return new


def _accumulate(old: Any, new: Any) -> list:
    """리스트 누적 reducer.

    체크포인터가 채널을 턴 사이에 유지하므로, 새 턴 시작 시 None 을 써서
    명시적으로 초기화할 수 있게 한다 (fresh_turn_state 참고).
    """
    if new is None:
        return []
    return list(old or []) + list(new)


class BankingState(TypedDict, total=False):
    # ── 세션/입력 ────────────────────────────────────────────────────────────
    user_id: Annotated[int, _replace]
    session_id: Annotated[str, _replace]
    current_message: Annotated[str, _replace]

    # ── Supervisor planning ──────────────────────────────────────────────────
    intent: Annotated[str, _replace]            # 대표 인텐트 (UI/로그용)
    plan: Annotated[Optional[Dict[str, Any]], _replace]   # ExecutionPlan dump
    sub_intent: Annotated[str, _replace]        # Send 로 브랜치별 주입되는 작업 지시

    # ── Transfer 슬롯/해석 (transfer 에이전트 전용 — 항상 단독 실행) ─────────
    recipient_alias: Annotated[Optional[str], _replace]
    amount: Annotated[Optional[int], _replace]
    memo: Annotated[Optional[str], _replace]
    use_last_transfer: Annotated[bool, _replace]
    recurring_hint: Annotated[Optional[str], _replace]
    resolved_recipient_id: Annotated[Optional[int], _replace]
    resolved_favorite_id: Annotated[Optional[int], _replace]
    alias_learned_from: Annotated[Optional[str], _replace]  # 학습된 호칭 (예: "여친")
    candidate_recipients: Annotated[List[Dict[str, Any]], _replace]  # 되묻기 후보
    clarify_mode: Annotated[str, _replace]  # "ambiguity" | "unknown_alias" | "ask_recipient"

    # ── 검증/보안/실행 결과 ──────────────────────────────────────────────────
    pending_transfer_data: Annotated[Optional[Dict[str, Any]], _replace]
    validation_errors: Annotated[List[str], _replace]
    risk_assessment: Annotated[Optional[Dict[str, Any]], _replace]
    transfer_executed: Annotated[bool, _replace]
    transfer_id: Annotated[Optional[int], _replace]
    new_balance: Annotated[Optional[int], _replace]

    # ── 에이전트 협업 산출물 (병렬 안전 — 리스트 누적) ───────────────────────
    agent_results: Annotated[List[Dict[str, Any]], _accumulate]
    agent_activity: Annotated[List[Dict[str, Any]], _accumulate]
    node_logs: Annotated[List[Dict[str, Any]], _accumulate]
    graph_trace: Annotated[List[str], _accumulate]

    # ── 최종 응답 (respond 노드가 합성) ──────────────────────────────────────
    response_type: Annotated[str, _replace]
    response_text: Annotated[str, _replace]
    response_data: Annotated[Optional[Dict[str, Any]], _replace]
    debug_info: Annotated[Dict[str, Any], _replace]


def fresh_turn_state(user_id: int, session_id: str, message: str) -> BankingState:
    """새 턴 입력 — 이전 턴의 슬롯/결과 키를 명시적으로 초기화."""
    return BankingState(
        user_id=user_id,
        session_id=session_id,
        current_message=message,
        intent="",
        plan=None,
        sub_intent="",
        recipient_alias=None,
        amount=None,
        memo=None,
        use_last_transfer=False,
        recurring_hint=None,
        resolved_recipient_id=None,
        resolved_favorite_id=None,
        alias_learned_from=None,
        candidate_recipients=[],
        clarify_mode="",
        pending_transfer_data=None,
        validation_errors=[],
        risk_assessment=None,
        transfer_executed=False,
        transfer_id=None,
        new_balance=None,
        # None → _accumulate reducer 가 이전 턴의 누적 리스트를 초기화
        agent_results=None,
        agent_activity=None,
        node_logs=None,
        graph_trace=None,
        response_type="message",
        response_text="",
        response_data=None,
        debug_info={},
    )
