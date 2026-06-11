"""
SecurityAgent — 보안/사기탐지 Sub-Agent.

두 가지 모드로 동작한다:
  1. 협업 모드 (A2A collaboration):
     TransferAgent 가 확인 카드 직전에 이 서브그래프를 직접 invoke 하여
     리스크 평가(RiskAssessment)를 의뢰한다.
  2. 단독 모드:
     Supervisor 계획에 security(report) 단계가 있으면 보안 리포트를 생성한다.

모든 판정은 security_rules 의 결정론적 룰 — LLM 무관.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from src.agents.context import BankingContext
from src.agents.state import BankingState
from src.agents.common.tracing import traced, activity
from src.agents.common.schemas import TransferSummary
from src.agents.common.services import security_rules


@traced("security", "assess")
def assess_node(state: dict, runtime: Runtime[BankingContext]) -> dict:
    ctx = runtime.context
    user_id = state["user_id"]
    pending = state.get("pending_transfer_data")

    # ── 협업 모드: 이체 1건 리스크 평가 ─────────────────────────────────────
    if pending:
        summary = TransferSummary(**pending)
        assessment = security_rules.assess_transfer(ctx, user_id, summary)
        return {
            "risk_assessment": assessment.model_dump(),
            "agent_activity": [
                activity("security", "assess_done", {
                    "risk_score": assessment.risk_score,
                    "level": assessment.level,
                    "rules": assessment.triggered_rules,
                    "force_otp": assessment.force_otp,
                }),
            ],
        }

    # ── 단독 모드: 보안 리포트 ───────────────────────────────────────────────
    report = security_rules.security_report(ctx, user_id)
    text = (
        "🛡️ 계좌 보안 점검 결과\n\n"
        f"• 최근 7일 이체: {report['week_transfer_count']}건 / {report['week_total_amount']:,}원\n"
        f"• 심야 시간대 이체: {report['night_transfers']}건\n"
        f"• 고액({ctx.otp_threshold:,}원 이상) 이체: {report['large_transfers']}건\n"
        f"• 보안 등급: {'⚠️ 강화 관리 대상' if report['risk_profile'] == 'high' else '정상'}"
    )
    if report["risk_profile"] == "high":
        text += "\n\n최근 이상거래 이력으로 100만원 이상 이체 시 OTP가 추가로 요구됩니다."

    return {
        "agent_results": [{
            "agent": "security",
            "kind": "security_report",
            "text": text,
            "data": report,
        }],
        "agent_activity": [activity("security", "report_done", {"week_count": report["week_transfer_count"]})],
    }


def build_security_subgraph():
    g = StateGraph(BankingState)
    g.add_node("assess", assess_node)
    g.add_edge(START, "assess")
    g.add_edge("assess", END)
    return g.compile()


# 협업 호출용 싱글턴 (TransferAgent 가 사용)
_security_graph = None


def get_security_graph():
    global _security_graph
    if _security_graph is None:
        _security_graph = build_security_subgraph()
    return _security_graph
