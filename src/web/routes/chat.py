"""Chat blueprint — serves the main chat page and the AJAX message endpoint."""

from __future__ import annotations

import uuid
from flask import Blueprint, current_app, jsonify, render_template, request, session

from src.agents.transfer_agent import run_transfer_agent
from src.models.database import db, ChatSession, ChatMessage

bp = Blueprint("chat", __name__)


@bp.route("/")
def index():
    """Redirect root to chat."""
    return render_template("chat.html")


@bp.route("/chat")
def chat():
    """Main chat page."""
    # Ensure a session_id cookie exists
    if "session_id" not in session:
        session["session_id"] = str(uuid.uuid4())

    user_id = current_app.config["DEMO_USER_ID"]
    session_id = session["session_id"]

    # Load existing messages for the session
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
    )


@bp.route("/api/chat/message", methods=["POST"])
def send_message():
    """AJAX endpoint — receives a user message and returns the agent response."""
    data = request.get_json(force=True)
    message: str = (data.get("message") or "").strip()

    if not message:
        return jsonify({"error": "메시지를 입력해 주세요."}), 400

    user_id = current_app.config["DEMO_USER_ID"]

    if "session_id" not in session:
        session["session_id"] = str(uuid.uuid4())
    session_id = session["session_id"]

    try:
        result = run_transfer_agent(user_id=user_id, message=message, session_id=session_id)
        return jsonify(result)
    except Exception as exc:
        current_app.logger.exception("Agent error")
        return jsonify({
            "response_text": f"처리 중 오류가 발생했습니다: {exc}",
            "response_type": "error",
            "response_data": None,
            "intent": "error",
            "debug_info": {"exception": str(exc)},
            "graph_trace": [],
            "pending_state": "none",
        }), 500


@bp.route("/api/chat/reset", methods=["POST"])
def reset_chat():
    """Clear current session state."""
    user_id = current_app.config["DEMO_USER_ID"]
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

    # Issue a new session_id
    session["session_id"] = str(uuid.uuid4())
    return jsonify({"status": "ok", "session_id": session["session_id"]})
