"""에이전트 실행 로그 — 목록 + 상세 라우트."""

from __future__ import annotations

import json

from flask import Blueprint, current_app, render_template, request

from src.models.database import db, AgentRunLog

bp = Blueprint("agent_logs", __name__, url_prefix="/agent-logs")

PER_PAGE = 30


@bp.route("/")
def index():
    page = request.args.get("page", 1, type=int)
    intent_filter = request.args.get("intent", "")

    q = db.session.query(AgentRunLog).order_by(AgentRunLog.created_at.desc())
    if intent_filter:
        q = q.filter(AgentRunLog.intent == intent_filter)

    total = q.count()
    runs = q.offset((page - 1) * PER_PAGE).limit(PER_PAGE).all()
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)

    # Intent 목록 (필터용)
    intents = [
        r[0] for r in
        db.session.query(AgentRunLog.intent).distinct().order_by(AgentRunLog.intent).all()
        if r[0]
    ]

    return render_template(
        "agent_logs.html",
        runs=runs,
        page=page,
        total=total,
        total_pages=total_pages,
        intent_filter=intent_filter,
        intents=intents,
        detail=None,
    )


@bp.route("/<int:run_id>")
def detail(run_id: int):
    run = db.session.get(AgentRunLog, run_id)
    if not run:
        return "로그를 찾을 수 없습니다.", 404

    def _parse(blob, default):
        try:
            return json.loads(blob or "") or default
        except Exception:
            return default

    node_logs = _parse(run.node_logs_json, [])
    plan = _parse(run.plan_json, None)
    agent_activity = _parse(run.agent_activity_json, [])
    trace = [t.strip() for t in (run.graph_trace or "").split(",") if t.strip()]

    return render_template(
        "agent_logs.html",
        runs=[],
        page=1,
        total=0,
        total_pages=1,
        intent_filter="",
        intents=[],
        detail=run,
        node_logs=node_logs,
        plan=plan,
        agent_activity=agent_activity,
        trace=trace,
    )
