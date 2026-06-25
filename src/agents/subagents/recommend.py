"""
RecommendAgent — 이체 패턴 기반 추천 Sub-Agent.

[최신 기능] 노드 캐싱(CachePolicy): 추천 점수 계산은 사용자별로 60초간 캐시된다.
같은 턴/짧은 간격의 반복 호출에서 DB 재계산을 생략한다 (node_logs 의
duration 으로 캐시 적중을 확인할 수 있다).
"""

from __future__ import annotations

from langgraph.cache.memory import InMemoryCache
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import CachePolicy

from src.agents.context import BankingContext
from src.agents.state import BankingState
from src.agents.common.tracing import traced, activity
from src.agents.common.services.recommendation_service import get_recommendations


@traced("recommend", "run")
def recommend_node(state: dict, runtime: Runtime[BankingContext]) -> dict:
    user_id = state["user_id"]
    recs = get_recommendations(user_id)

    if not recs:
        return {
            "agent_results": [{
                "agent": "recommend", "kind": "recipients",
                "text": "추천할 수신자 정보가 없습니다.",
                "data": {"recommendations": []},
            }],
            "last_recommendations": [],
            "last_followup_source": "recommendations",
            "agent_activity": [activity("recommend", "done", {"count": 0})],
        }

    lines = ["⭐ 추천 수신자\n"]
    rec_list = []
    for r in recs:
        amount_str = f" | 추천 금액 {r.suggested_amount:,}원" if r.suggested_amount else ""
        lines.append(f"{r.rank}. {r.alias or r.name} ({r.bank_name}){amount_str} — {r.reason}")
        rec_list.append(r.model_dump())

    return {
        "agent_results": [{
            "agent": "recommend", "kind": "recipients",
            "text": "\n".join(lines),
            "data": {"recommendations": rec_list},
        }],
        "last_recommendations": rec_list,
        "last_followup_source": "recommendations",
        "agent_activity": [activity("recommend", "done", {"count": len(rec_list)})],
    }


def build_recommend_subgraph():
    g = StateGraph(BankingState)
    g.add_node(
        "run",
        recommend_node,
        # 캐시 키 = user_id — 60초 내 동일 사용자 재호출은 캐시 적중
        cache_policy=CachePolicy(ttl=60, key_func=lambda s: str(s.get("user_id"))),
    )
    g.add_edge(START, "run")
    g.add_edge("run", END)
    return g.compile(cache=InMemoryCache())
