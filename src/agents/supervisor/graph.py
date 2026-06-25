"""
Supervisor (Leader) Agent — 계획 → 디스패치 → 집계.

[하이라키 구조]
                    ┌─────────── plan (LLM Planning / rule 폴백) ───────────┐
   사용자 메시지 →  │  ExecutionPlan: 어떤 Sub-Agent 를 어떤 순서로?         │
                    └──┬────────────┬───────────────┬──────────────┬───────┘
              Command  │     Send   │        Send   │       Send   │
                       ▼            ▼               ▼              ▼
                  [transfer]    [inquiry]      [recommend]    [security]
                       │            │               │              │
                       └────────────┴───────┬───────┴──────────────┘
                                            ▼
                                        respond (집계 + 나이 맞춤 말투)

[최신 기능]
  · Send API            : 계획에 따라 Sub-Agent 를 *동적으로 병렬* fan-out
  · Subgraph 합성       : 각 Sub-Agent 는 독립 StateGraph → 상위 그래프의 노드
  · SqliteSaver         : thread_id(=세션)별 상태 영속화 — 수동 직렬화 제거
  · interrupt 전파      : Sub-Agent 내부의 interrupt 가 부모를 관통해 사용자에게 도달
  · Runtime context     : invoke(…, context=BankingContext(…)) 로 의존성 주입
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from typing import Union

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, Send

from src.agents.context import BankingContext, build_context
from src.agents.state import BankingState, fresh_turn_state
from src.agents.common.tracing import traced, activity
from src.agents.common import llm as llm_helper
from src.agents.supervisor.planner import make_plan
from src.agents.supervisor.prompts import apply_tone, build_polish_prompt
from src.agents.subagents import (
    build_financial_calculator_subgraph,
    build_inquiry_subgraph,
    build_menu_search_subgraph,
    build_product_guide_subgraph,
    build_recommend_subgraph,
    build_security_subgraph,
    build_tool_calling_subgraph,
    build_transfer_subgraph,
)

_UNKNOWN_TEXT = (
    "죄송합니다, 요청을 이해하지 못했어요.\n"
    "다음과 같이 말씀해 주세요:\n"
    "• 엄마에게 5만원 보내줘\n"
    "• 내 잔고 보여줘\n"
    "• 잔고 보여주고 보낼 만한 사람도 추천해줘\n"
    "• 월세 보내야 하지?"
)

# 응답 종류 매핑 (UI 렌더링 힌트)
_KIND_TO_RESPONSE_TYPE = {
    "balance": "balance",
    "history": "history",
    "recurring": "message",
    "recipients": "recommendation",
    "security_report": "message",
    "menu_search": "message",
    "product_guide": "message",
    "calculation": "message",
    "success": "success",
    "error": "error",
    "cancelled": "message",
    "message": "message",
}


# ─────────────────────────────────────────────────────────────────────────────
# Node — plan (Supervisor 의 두뇌)
# ─────────────────────────────────────────────────────────────────────────────


@traced("supervisor", "plan")
def plan_node(state: dict, runtime: Runtime[BankingContext]) -> dict:
    ctx = runtime.context
    message = state.get("current_message", "")

    plan = make_plan(ctx, message)

    return {
        "plan": plan.model_dump(),
        "intent": plan.primary_intent,
        "agent_activity": [activity("supervisor", "plan", {
            "planner": plan.planner,
            "parallel": plan.parallel,
            "steps": [
                {"agent": s.agent, "sub_intent": s.sub_intent, "reason": s.reason}
                for s in plan.steps
            ],
            "note": plan.note,
        })],
    }


def route_plan(state: dict) -> Union[str, list]:
    """plan → Sub-Agent 디스패치.  모든 단계를 Send 로 fan-out 한다.

    Send 입력을 명시적 키로 한정하는 이유: 컴파일된 서브그래프 노드는 완료 시
    자신의 전체 상태를 부모에 다시 쓰므로, 부모의 누적 리스트(agent_activity 등)를
    시드하면 중복 누적된다. 필요한 스칼라만 전달해 서브그래프 산출물만 합류시킨다.
    """
    plan = state.get("plan") or {}
    steps = plan.get("steps") or []

    if not steps:
        return "respond"

    sends = []
    for step in steps:
        sends.append(Send(step["agent"], {
            "user_id": state["user_id"],
            "session_id": state.get("session_id", ""),
            "current_message": state.get("current_message", ""),
            "intent": plan.get("primary_intent", ""),
            "sub_intent": step["sub_intent"],
            "last_recommendations": state.get("last_recommendations", []),
            "last_history_items": state.get("last_history_items", []),
            "last_balance_summary": state.get("last_balance_summary"),
            "last_followup_source": state.get("last_followup_source", ""),
        }))
    return sends


# ─────────────────────────────────────────────────────────────────────────────
# Node — respond (집계 + Dynamic Prompting 말투 적용)
# ─────────────────────────────────────────────────────────────────────────────


@traced("supervisor", "respond")
def respond_node(state: dict, runtime: Runtime[BankingContext]) -> dict:
    ctx = runtime.context
    results = state.get("agent_results") or []
    plan = state.get("plan") or {}
    steps = plan.get("steps") or []

    if not results:
        text = apply_tone(ctx, _UNKNOWN_TEXT, "message")
        return {
            "response_type": "message",
            "response_text": text,
            "response_data": None,
            "agent_activity": [activity("supervisor", "respond", {"results": 0})],
        }

    # 계획 단계 순서대로 결과 정렬 (병렬 완료 순서는 비결정적이므로)
    def _order(entry: dict) -> int:
        for i, s in enumerate(steps):
            if s["agent"] == entry.get("agent") and s["sub_intent"] == entry.get("kind"):
                return i
            if s["agent"] == entry.get("agent"):
                return i
        return len(steps)

    results = sorted(results, key=_order)

    text = "\n\n".join(r.get("text", "") for r in results if r.get("text"))
    primary = results[0]
    response_type = _KIND_TO_RESPONSE_TYPE.get(primary.get("kind", "message"), "message")

    if len(results) == 1:
        response_data = primary.get("data")
    else:
        response_data = {r.get("kind", f"r{i}"): r.get("data") for i, r in enumerate(results)}

    # ── Dynamic Prompting: 나이 기반 말투 (결정론 보정 + 선택적 LLM 다듬기) ──
    text = apply_tone(ctx, text, response_type)
    if ctx.llm_enabled and response_type in ("message", "balance", "history", "recommendation"):
        text = llm_helper.polish_response(ctx, text, build_polish_prompt(ctx))

    return {
        "response_type": response_type,
        "response_text": text,
        "response_data": response_data,
        "agent_activity": [activity("supervisor", "respond", {
            "results": len(results), "tone": ctx.tone,
        })],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Graph 조립
# ─────────────────────────────────────────────────────────────────────────────


def build_banking_graph(checkpointer=None):
    """Supervisor + 4 Sub-Agent 하이라키 그래프를 컴파일한다."""
    g = StateGraph(BankingState, context_schema=BankingContext)

    g.add_node("plan", plan_node)
    g.add_node("transfer", build_transfer_subgraph())
    g.add_node("inquiry", build_inquiry_subgraph())
    g.add_node("recommend", build_recommend_subgraph())
    g.add_node("security", build_security_subgraph())
    g.add_node("menu_search", build_menu_search_subgraph())
    g.add_node("product_guide", build_product_guide_subgraph())
    g.add_node("financial_calculator", build_financial_calculator_subgraph())
    g.add_node("tool_agent", build_tool_calling_subgraph())
    g.add_node("respond", respond_node)

    g.add_edge(START, "plan")
    g.add_conditional_edges(
        "plan", route_plan,
        [
            "transfer",
            "inquiry",
            "recommend",
            "security",
            "menu_search",
            "product_guide",
            "financial_calculator",
            "tool_agent",
            "respond",
        ],
    )
    g.add_edge("transfer", "respond")
    g.add_edge("inquiry", "respond")
    g.add_edge("recommend", "respond")
    g.add_edge("security", "respond")
    g.add_edge("menu_search", "respond")
    g.add_edge("product_guide", "respond")
    g.add_edge("financial_calculator", "respond")
    g.add_edge("tool_agent", "respond")
    g.add_edge("respond", END)

    return g.compile(checkpointer=checkpointer)


# ─────────────────────────────────────────────────────────────────────────────
# 프로세스 싱글턴 (체크포인터 포함)
# ─────────────────────────────────────────────────────────────────────────────

_graph = None
_conn = None
_graph_lock = threading.Lock()


def _get_graph(checkpoint_path: str):
    global _graph, _conn
    if _graph is None:
        with _graph_lock:
            if _graph is None:
                _conn = sqlite3.connect(checkpoint_path, check_same_thread=False)
                _graph = build_banking_graph(checkpointer=SqliteSaver(_conn))
    return _graph


def reset_graph_singleton() -> None:
    """테스트/리셋용 — 컴파일된 그래프와 체크포인터 연결을 폐기한다."""
    global _graph, _conn
    with _graph_lock:
        if _conn is not None:
            try:
                _conn.close()
            except Exception:
                pass
        _graph = None
        _conn = None


# ─────────────────────────────────────────────────────────────────────────────
# Flask 경계 — 한 턴 실행
# ─────────────────────────────────────────────────────────────────────────────

_PENDING_STATE_BY_KIND = {
    "clarification": "awaiting_clarification",
    "ask_amount": "awaiting_amount",
    "confirmation": "awaiting_confirmation",
    "otp": "awaiting_otp",
}


def run_banking_agent(user_id: int, message: str, session_id: str | None = None) -> dict:
    """
    한 턴 실행.  Flask 와 에이전트 사이의 유일한 접점:
      1. User 로드 → BankingContext 구성 (Runtime 주입용)
      2. 체크포인트에 미해결 interrupt 가 있으면 Command(resume=) 으로 재개,
         없으면 새 턴 상태로 invoke
      3. __interrupt__ 발생 시 payload 를 응답으로 변환
      4. 채팅/실행 로그 영속화
    """
    from flask import current_app
    from src.models.database import db, AgentRunLog, ChatMessage, ChatSession, User

    if session_id is None:
        session_id = str(uuid.uuid4())

    user = db.session.get(User, user_id)
    if user is None:
        raise ValueError(f"unknown user_id={user_id}")

    ctx = build_context(current_app.config, user, session_id)
    graph = _get_graph(current_app.config.get("CHECKPOINT_DB_PATH", "banking_checkpoints.db"))
    config = {"configurable": {"thread_id": f"{user_id}:{session_id}"}}

    # ── 미해결 interrupt 감지 → resume ──────────────────────────────────────
    try:
        snapshot = graph.get_state(config)
        has_pending = bool(snapshot.next)
    except Exception:
        has_pending = False

    if has_pending:
        graph_input = Command(resume=message)
    else:
        graph_input = fresh_turn_state(user_id, session_id, message)

    t_start = time.monotonic()
    langsmith_url = None

    if current_app.config.get("LANGSMITH_ENABLED"):
        from langchain_core.tracers.context import collect_runs
        with collect_runs() as cb:
            result = graph.invoke(graph_input, config=config, context=ctx)
        if cb.traced_runs:
            run_id = str(cb.traced_runs[0].id)
            project = current_app.config.get("LANGSMITH_PROJECT", "banking-transfer-agent")
            langsmith_url = f"https://smith.langchain.com/o/0/projects/p/{project}/r/{run_id}"
    else:
        result = graph.invoke(graph_input, config=config, context=ctx)

    total_ms = max(1, int((time.monotonic() - t_start) * 1000))
    checkpoint_values = _latest_checkpoint_values(graph, config)

    # ── 응답 구성: interrupt payload 또는 최종 상태 ─────────────────────────
    interrupts = result.get("__interrupt__") or []
    interrupt_debug_info = {}
    if interrupts:
        payload = interrupts[0].value if hasattr(interrupts[0], "value") else interrupts[0]
        payload = payload if isinstance(payload, dict) else {"response_text": str(payload)}
        response_type = payload.get("response_type", "message")
        response_text = apply_tone(ctx, payload.get("response_text", ""), response_type)
        response_data = payload.get("response_data")
        interrupt_debug_info = payload.get("debug_info") or {}
        pending_state = _PENDING_STATE_BY_KIND.get(payload.get("kind", ""), "awaiting_input")
    else:
        response_type = result.get("response_type", "message")
        response_text = result.get("response_text", "")
        response_data = result.get("response_data")
        pending_state = "none"

    plan = result.get("plan")
    agent_activity = result.get("agent_activity") or []
    node_logs = result.get("node_logs") or []
    graph_trace = result.get("graph_trace") or []
    intent = result.get("intent", "")

    # ── 채팅 메시지/세션 기록 ────────────────────────────────────────────────
    session = (
        db.session.query(ChatSession)
        .filter(ChatSession.session_id == session_id, ChatSession.user_id == user_id)
        .first()
    )
    if not session:
        session = ChatSession(user_id=user_id, session_id=session_id, state_json=None)
        db.session.add(session)
        db.session.flush()

    db.session.add(ChatMessage(
        session_id=session.id, role="user", content=message, intent=intent,
        slots_json=json.dumps({
            "recipient_alias": result.get("recipient_alias"),
            "amount": result.get("amount"),
            "memo": result.get("memo"),
        }, ensure_ascii=False),
    ))
    db.session.add(ChatMessage(
        session_id=session.id, role="assistant", content=response_text, intent=intent,
    ))

    # ── 에이전트 실행 로그 ───────────────────────────────────────────────────
    run_log = AgentRunLog(
        user_id=user_id,
        session_id=session_id,
        user_message=message,
        intent=intent,
        response_type=response_type,
        response_text=response_text[:500],
        pending_state=pending_state,
        graph_trace=",".join(graph_trace),
        node_logs_json=json.dumps(node_logs, ensure_ascii=False, default=str),
        plan_json=json.dumps(plan, ensure_ascii=False, default=str) if plan else None,
        agent_activity_json=json.dumps(agent_activity, ensure_ascii=False, default=str),
        total_duration_ms=total_ms,
        langsmith_url=langsmith_url,
    )
    db.session.add(run_log)
    db.session.commit()

    return {
        "response_text": response_text,
        "response_type": response_type,
        "response_data": response_data,
        "intent": intent,
        "plan": plan,
        "agent_activity": agent_activity,
        "node_logs": node_logs,
        "graph_trace": graph_trace,
        "debug_info": result.get("debug_info") or interrupt_debug_info or checkpoint_values.get("debug_info", {}),
        "pending_state": pending_state,
        "session_id": session_id,
        "user_profile": {
            "display_name": ctx.display_name,
            "age": ctx.age,
            "tone": ctx.tone,
            "tier": ctx.customer_tier,
            "risk_profile": ctx.risk_profile,
        },
        "langsmith_url": langsmith_url,
        "run_log_id": run_log.id,
    }


def _latest_checkpoint_values(graph, config: dict) -> dict:
    try:
        snapshot = graph.get_state(config)
        values = getattr(snapshot, "values", None)
    except Exception:
        return {}
    return values if isinstance(values, dict) else {}
