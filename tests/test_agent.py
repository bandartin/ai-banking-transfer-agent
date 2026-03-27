"""Integration tests for the full transfer agent graph."""

import pytest
from src.agents.transfer_agent import run_transfer_agent


SESSION_ID = "test-session-001"


class TestAgentIntegration:
    """These tests run the full LangGraph pipeline with deterministic mode."""

    def test_balance_inquiry(self, app):
        with app.app_context():
            result = run_transfer_agent(1, "내 잔고 보여줘", session_id=SESSION_ID + "-bal")
            assert result["intent"] == "balance_inquiry"
            assert "잔액" in result["response_text"] or "잔고" in result["response_text"]

    def test_history_inquiry(self, app):
        with app.app_context():
            result = run_transfer_agent(1, "최근 이체내역 보여줘", session_id=SESSION_ID + "-hist")
            assert result["intent"] == "history_inquiry"

    def test_transfer_to_mom_shows_confirmation(self, app):
        with app.app_context():
            result = run_transfer_agent(1, "엄마에게 5만원 보내줘", session_id=SESSION_ID + "-mom")
            assert result["intent"] == "transfer"
            assert result["response_type"] == "confirmation"
            assert result["pending_state"] == "awaiting_confirmation"
            data = result["response_data"]
            assert data["amount"] == 50_000

    def test_transfer_ambiguity_minsu(self, app):
        with app.app_context():
            result = run_transfer_agent(1, "민수에게 5만원 보내줘", session_id=SESSION_ID + "-minsu")
            assert result["response_type"] == "ambiguity"
            assert result["pending_state"] == "awaiting_clarification"
            candidates = result["response_data"]["candidates"]
            assert len(candidates) >= 2

    def test_confirm_transfer_after_confirmation(self, app):
        """Two-turn test: request → confirm."""
        sid = SESSION_ID + "-confirm"
        with app.app_context():
            r1 = run_transfer_agent(1, "엄마에게 5만원 보내줘", session_id=sid)
            assert r1["pending_state"] == "awaiting_confirmation"

            r2 = run_transfer_agent(1, "확인", session_id=sid)
            assert r2["response_type"] == "success"
            assert r2["pending_state"] == "none"

    def test_cancel_transfer(self, app):
        """Two-turn test: request → cancel."""
        sid = SESSION_ID + "-cancel"
        with app.app_context():
            r1 = run_transfer_agent(1, "엄마에게 5만원 보내줘", session_id=sid)
            assert r1["pending_state"] == "awaiting_confirmation"

            r2 = run_transfer_agent(1, "취소", session_id=sid)
            assert r2["pending_state"] == "none"
            assert "취소" in r2["response_text"]

    def test_recurring_wolse(self, app):
        with app.app_context():
            result = run_transfer_agent(1, "월세 보내야 하지?", session_id=SESSION_ID + "-wolse")
            assert result["intent"] == "transfer"
            # Should resolve 집주인 from recurring and show confirmation
            assert result["response_type"] in ("confirmation", "message")

    def test_recommendation(self, app):
        with app.app_context():
            result = run_transfer_agent(1, "자주 보내는 사람 추천해줘", session_id=SESSION_ID + "-rec")
            assert result["intent"] == "recommendation"
