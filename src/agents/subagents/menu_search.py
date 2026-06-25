"""MenuSearchAgent — AWX/RAG-backed menu and screen-path search.

This agent is deliberately read-only.  It can explain where a feature lives in
the app or branch 업무 화면, but it must not retrieve or infer customer
balances, limits, or transfer execution state.  Those belong to the real-time
banking integration ports.
"""

from __future__ import annotations

import json

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from src.agents.context import BankingContext
from src.agents.state import BankingState
from src.agents.common.tracing import activity, traced
from src.integrations import get_knowledge_adapter
from src.models.database import RagRetrievalLog, db


@traced("menu_search", "run")
def menu_search_node(state: dict, runtime: Runtime[BankingContext]) -> dict:
    ctx = runtime.context
    query = state.get("current_message", "")
    result = get_knowledge_adapter().retrieve(query, collection="menu_catalog", top_k=5)
    _log_retrieval(ctx, state, "menu_search", result)

    if not result.chunks:
        text = result.error_message or "관련 메뉴를 찾지 못했습니다. 메뉴명이나 하려는 업무를 조금 더 구체적으로 말씀해 주세요."
        data = {"query": query, "results": [], "source": result.source, "error_message": result.error_message}
    else:
        lines = ["🔎 메뉴 검색 결과\n"]
        items = []
        for idx, chunk in enumerate(result.chunks, start=1):
            menu_path = chunk.metadata.get("menu_path", "")
            suffix = f" — {menu_path}" if menu_path else ""
            lines.append(f"{idx}. {chunk.title}{suffix}")
            items.append({
                "rank": idx,
                "title": chunk.title,
                "content": chunk.content,
                "score": chunk.score,
                "menu_path": menu_path,
                "chunk_id": chunk.chunk_id,
                "source_uri": chunk.source_uri,
                "document_version": chunk.document_version,
                "updated_at": chunk.updated_at,
            })
        text = "\n".join(lines)
        data = {"query": query, "results": items, "source": result.source}

    return {
        "agent_results": [{
            "agent": "menu_search",
            "kind": "menu_search",
            "text": text,
            "data": data,
        }],
        "agent_activity": [activity("menu_search", "done", {"count": len(result.chunks), "source": result.source})],
    }


def _log_retrieval(ctx: BankingContext, state: dict, agent_name: str, result) -> None:
    """Persist retrieval metadata for explainability and RAG QA."""
    try:
        db.session.add(
            RagRetrievalLog(
                user_id=ctx.user_id,
                session_id=state.get("session_id", ctx.session_id),
                agent_name=agent_name,
                query_text=result.query,
                collection=result.collection,
                top_score=str(result.chunks[0].score) if result.chunks else "",
                threshold_met=result.threshold_met,
                chunks_json=json.dumps([c.__dict__ for c in result.chunks], ensure_ascii=False, default=str),
                source=result.source,
            )
        )
        db.session.flush()
    except Exception:
        db.session.rollback()


def build_menu_search_subgraph():
    g = StateGraph(BankingState)
    g.add_node("run", menu_search_node)
    g.add_edge(START, "run")
    g.add_edge("run", END)
    return g.compile()
