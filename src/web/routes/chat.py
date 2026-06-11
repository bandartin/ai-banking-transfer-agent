"""Chat blueprint — serves the main chat page and the AJAX message endpoint."""

from __future__ import annotations

import uuid
from flask import Blueprint, current_app, jsonify, render_template, request, session

from src.agents.supervisor import run_banking_agent
from src.models.database import db, ChatMessage, ChatSession, User

bp = Blueprint("chat", __name__)


def current_user_id() -> int:
    """세션에서 선택된 데모 사용자 (없으면 기본 사용자)."""
    return session.get("user_id", current_app.config["DEMO_USER_ID"])


@bp.route("/")
def index():
    """Redirect root to chat."""
    return render_template("chat.html", users=_demo_users(), current_user=None)


@bp.route("/chat")
def chat():
    """Main chat page."""
    if "session_id" not in session:
        session["session_id"] = str(uuid.uuid4())

    user_id = current_user_id()
    session_id = session["session_id"]

    chat_session = (
        db.session.query(ChatSession)
        .filter(
            ChatSession.session_id == session_id,
            ChatSession.user_id == user_id,
        )
        .first()
    )
    messages = []
    if chat_session:
        messages = (
            db.session.query(ChatMessage)
            .filter(ChatMessage.session_id == chat_session.id)
            .order_by(ChatMessage.created_at.asc())
            .all()
        )

    return render_template(
        "chat.html",
        messages=messages,
        session_id=session_id,
        llm_provider=current_app.config.get("LLM_PROVIDER", "deterministic"),
        users=_demo_users(),
        current_user=db.session.get(User, user_id),
    )


def _demo_users():
    return db.session.query(User).filter(User.is_active == True).order_by(User.id).all()


@bp.route("/api/chat/message", methods=["POST"])
def send_message():
    """AJAX endpoint — receives a user message and returns the agent response."""
    data = request.get_json(force=True)
    message: str = (data.get("message") or "").strip()

    if not message:
        return jsonify({"error": "메시지를 입력해 주세요."}), 400

    user_id = current_user_id()

    if "session_id" not in session:
        session["session_id"] = str(uuid.uuid4())
    session_id = session["session_id"]

    try:
        result = run_banking_agent(user_id=user_id, message=message, session_id=session_id)
        return jsonify(result)
    except Exception as exc:
        current_app.logger.exception("Agent error")
        return jsonify({
            "response_text": f"처리 중 오류가 발생했습니다: {exc}",
            "response_type": "error",
            "response_data": None,
            "intent": "error",
            "plan": None,
            "agent_activity": [],
            "node_logs": [],
            "debug_info": {"exception": str(exc)},
            "graph_trace": [],
            "pending_state": "none",
        }), 500


@bp.route("/api/chat/user", methods=["POST"])
def switch_user():
    """데모 사용자 전환 — 나이 기반 맞춤 말투(Dynamic Prompting) 시연용."""
    data = request.get_json(force=True)
    user_id = int(data.get("user_id", 0))
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "존재하지 않는 사용자입니다."}), 404

    session["user_id"] = user.id
    session["session_id"] = str(uuid.uuid4())  # 사용자 전환 시 새 대화 스레드
    return jsonify({
        "status": "ok",
        "user_id": user.id,
        "display_name": user.display_name,
        "age": user.age,
        "session_id": session["session_id"],
    })


@bp.route("/api/chat/reset", methods=["POST"])
def reset_chat():
    """Clear current session state."""
    user_id = current_user_id()
    session_id = session.get("session_id")

    if session_id:
        chat_session = (
            db.session.query(ChatSession)
            .filter(
                ChatSession.session_id == session_id,
                ChatSession.user_id == user_id,
            )
            .first()
        )
        if chat_session:
            db.session.query(ChatMessage).filter(
                ChatMessage.session_id == chat_session.id
            ).delete()
            db.session.delete(chat_session)
            db.session.commit()

    # Issue a new session_id — 새 LangGraph 체크포인트 스레드가 시작된다
    session["session_id"] = str(uuid.uuid4())
    return jsonify({"status": "ok", "session_id": session["session_id"]})
