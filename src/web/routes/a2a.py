"""
A2A (Agent-to-Agent) protocol blueprint.

표준 A2A 의 핵심 표면을 노출한다:
  · GET  /.well-known/agent-card.json        — 대표(Supervisor) Agent Card
  · GET  /api/a2a/agents                     — 모든 Sub-Agent 카드 목록 (discovery)
  · GET  /api/a2a/agents/<name>              — 개별 Agent Card
  · POST /api/a2a/agents/<name>/invoke       — JSON-RPC 스타일 message/send

외부 에이전트는 카드를 발견(discovery)한 뒤 invoke 로 Sub-Agent 를 직접 호출할
수 있다. (운영 환경에서는 a2a-sdk 의 ASGI 서버로 대체 가능 — 카드 스키마 동일)
"""

from __future__ import annotations

import uuid

from flask import Blueprint, current_app, jsonify, request

from src.agents.a2a.cards import AGENT_CARDS, public_card
from src.agents.context import build_context
from src.models.database import db, User

bp = Blueprint("a2a", __name__)


@bp.route("/.well-known/agent-card.json")
def well_known_card():
    """대표 Agent Card — Supervisor 가 묶어서 노출."""
    base = request.url_root.rstrip("/")
    return jsonify({
        "protocolVersion": "0.3.0",
        "name": "EumBank-AI-Transfer-Supervisor",
        "description": "으뜸은행 AI 이체 Supervisor. 하위 4개 도메인 에이전트(transfer/inquiry/recommend/security)를 LangGraph 하이라키로 오케스트레이션한다.",
        "url": f"{base}/api/a2a/agents/supervisor/invoke",
        "preferredTransport": "JSONRPC",
        "skills": [s for card in AGENT_CARDS.values() for s in card["skills"]],
        "subAgents": [f"{base}/api/a2a/agents/{key}" for key in AGENT_CARDS],
    })


@bp.route("/api/a2a/agents")
def list_agents():
    base = request.url_root.rstrip("/")
    return jsonify({key: public_card(key, base) for key in AGENT_CARDS})


@bp.route("/api/a2a/agents/<agent_key>")
def get_agent(agent_key: str):
    if agent_key not in AGENT_CARDS:
        return jsonify({"error": "unknown agent"}), 404
    return jsonify(public_card(agent_key, request.url_root.rstrip("/")))


@bp.route("/api/a2a/agents/<agent_key>/invoke", methods=["POST"])
def invoke_agent(agent_key: str):
    """JSON-RPC 스타일 message/send.

    요청 예:
      {"jsonrpc": "2.0", "id": "1", "method": "message/send",
       "params": {"message": {"parts": [{"text": "내 잔고 보여줘"}]},
                  "metadata": {"user_id": 1, "sub_intent": "balance"}}}
    """
    body = request.get_json(force=True) or {}
    params = body.get("params") or {}
    meta = params.get("metadata") or {}

    parts = (params.get("message") or {}).get("parts") or []
    text = " ".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()

    user_id = int(meta.get("user_id", current_app.config["DEMO_USER_ID"]))
    user = db.session.get(User, user_id)
    if user is None:
        return _rpc_error(body, -32602, "unknown user_id")

    ctx = build_context(current_app.config, user, meta.get("session_id") or str(uuid.uuid4()))

    if agent_key == "supervisor":
        # 전체 파이프라인 위임 (interrupt 발생 가능 — 단발 호출 데모이므로 그대로 반환)
        from src.agents.supervisor import run_banking_agent
        result = run_banking_agent(user_id=user_id, message=text, session_id=ctx.session_id)
        artifact = {"text": result["response_text"], "data": result.get("response_data")}
        return _rpc_result(body, artifact, result.get("agent_activity", []))

    if agent_key not in AGENT_CARDS:
        return _rpc_error(body, -32601, "unknown agent")

    # Sub-Agent 단독 호출 (stateless)
    from src.agents.subagents import (
        build_financial_calculator_subgraph,
        build_inquiry_subgraph,
        build_menu_search_subgraph,
        build_product_guide_subgraph,
        build_recommend_subgraph,
        build_security_subgraph,
    )
    builders = {
        "inquiry": build_inquiry_subgraph,
        "recommend": build_recommend_subgraph,
        "security": build_security_subgraph,
        "menu_search": build_menu_search_subgraph,
        "product_guide": build_product_guide_subgraph,
        "financial_calculator": build_financial_calculator_subgraph,
    }
    if agent_key == "transfer":
        return _rpc_error(
            body, -32600,
            "transfer 에이전트는 Human-in-the-Loop(확인/OTP)가 필요하므로 supervisor 경유로만 호출 가능합니다.",
        )

    graph = builders[agent_key]()
    out = graph.invoke(
        {
            "user_id": user_id,
            "session_id": ctx.session_id,
            "current_message": text,
            "sub_intent": meta.get("sub_intent", ""),
        },
        context=ctx,
    )
    results = out.get("agent_results") or []
    artifact = results[0] if results else {"text": "", "data": None}
    return _rpc_result(body, artifact, out.get("agent_activity", []))


def _rpc_result(body: dict, artifact: dict, activity: list):
    return jsonify({
        "jsonrpc": "2.0",
        "id": body.get("id"),
        "result": {
            "kind": "task",
            "status": {"state": "completed"},
            "artifacts": [{
                "parts": [{"kind": "text", "text": artifact.get("text", "")}],
                "metadata": {"data": artifact.get("data"), "agent_activity": activity},
            }],
        },
    })


def _rpc_error(body: dict, code: int, message: str):
    return jsonify({
        "jsonrpc": "2.0", "id": body.get("id"),
        "error": {"code": code, "message": message},
    }), 400
