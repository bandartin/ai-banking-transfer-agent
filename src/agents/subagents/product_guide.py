"""ProductGuideAgent — product, fee, FAQ, and policy explanation via RAG.

The agent answers from knowledge documents and returns source metadata.  It is
not allowed to decide customer-specific fee waivers or transfer feasibility;
those values must come from authoritative banking ports at the point of action.
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


@traced("product_guide", "run")
def product_guide_node(state: dict, runtime: Runtime[BankingContext]) -> dict:
    ctx = runtime.context
    query = state.get("current_message", "")
    collection = _choose_collection(query)
    result = get_knowledge_adapter().retrieve(query, collection=collection, top_k=4)
    _log_retrieval(ctx, state, "product_guide", result)

    if not result.chunks:
        text = result.error_message or "근거 문서를 찾지 못해 안내를 보류합니다. 상품명이나 궁금한 조건을 더 구체적으로 알려주세요."
        data = {"query": query, "sources": [], "source": result.source, "error_message": result.error_message}
    else:
        top = result.chunks[0]
        lines = [
            f"📘 {top.title}",
            "",
            top.content,
            "",
            "출처:",
        ]
        sources = []
        for chunk in result.chunks:
            lines.append(f"- {chunk.title} ({chunk.document_version or 'version n/a'}, score {chunk.score:.2f})")
            sources.append({
                "chunk_id": chunk.chunk_id,
                "title": chunk.title,
                "score": chunk.score,
                "source_uri": chunk.source_uri,
                "document_version": chunk.document_version,
                "updated_at": chunk.updated_at,
            })
        text = "\n".join(lines)
        data = {"query": query, "collection": collection, "sources": sources, "source": result.source}

    return {
        "agent_results": [{
            "agent": "product_guide",
            "kind": "product_guide",
            "text": text,
            "data": data,
        }],
        "agent_activity": [activity("product_guide", "done", {"count": len(result.chunks), "collection": collection})],
    }


def _choose_collection(query: str) -> str:
    if any(token in query for token in ("수수료", "면제", "타행")):
        return "fee_policy_docs"
    return "product_docs"


def _log_retrieval(ctx: BankingContext, state: dict, agent_name: str, result) -> None:
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


def build_product_guide_subgraph():
    g = StateGraph(BankingState)
    g.add_node("run", product_guide_node)
    g.add_edge(START, "run")
    g.add_edge("run", END)
    return g.compile()
