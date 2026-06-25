"""멀티 에이전트 파이프라인 통합 테스트 (Supervisor + Sub-Agents)."""

import pytest
from src.agents.supervisor import run_banking_agent


SESSION_ID = "test-session-001"


class TestSupervisorPlanning:
    def test_balance_inquiry_plan(self, app):
        with app.app_context():
            r = run_banking_agent(1, "내 잔고 보여줘", session_id=SESSION_ID + "-bal")
            assert r["intent"] == "balance_inquiry"
            assert r["response_type"] == "balance"
            steps = r["plan"]["steps"]
            assert steps == [{"agent": "inquiry", "sub_intent": "balance",
                              "reason": steps[0]["reason"]}]

    def test_parallel_fanout(self, app):
        """복합 발화 → 병렬 Send 계획 + 결과 합성."""
        with app.app_context():
            r = run_banking_agent(1, "잔고 보여주고 자주 보내는 사람도 추천해줘",
                                  session_id=SESSION_ID + "-par")
            plan = r["plan"]
            assert plan["parallel"] is True
            agents = {s["agent"] for s in plan["steps"]}
            assert agents == {"inquiry", "recommend"}
            # 두 에이전트의 결과가 하나의 응답으로 합성
            assert "잔액" in r["response_text"] or "잔고" in r["response_text"]
            assert "추천" in r["response_text"]

    def test_unknown(self, app):
        with app.app_context():
            r = run_banking_agent(1, "오늘 날씨 어때?", session_id=SESSION_ID + "-unk")
            assert r["plan"]["steps"] == []
            assert r["response_type"] == "message"


class TestTransferMultiTurn:
    """interrupt 기반 멀티턴 시나리오."""

    def test_confirmation_flow(self, app):
        sid = SESSION_ID + "-confirm"
        with app.app_context():
            r1 = run_banking_agent(1, "엄마에게 5만원 보내줘", session_id=sid)
            assert r1["pending_state"] == "awaiting_confirmation"
            assert r1["response_type"] == "confirmation"
            assert r1["response_data"]["amount"] == 50_000

            r2 = run_banking_agent(1, "확인", session_id=sid)
            assert r2["response_type"] == "success"
            assert r2["pending_state"] == "none"

    def test_cancel_flow(self, app):
        sid = SESSION_ID + "-cancel"
        with app.app_context():
            r1 = run_banking_agent(1, "엄마에게 5만원 보내줘", session_id=sid)
            assert r1["pending_state"] == "awaiting_confirmation"

            r2 = run_banking_agent(1, "취소", session_id=sid)
            assert r2["pending_state"] == "none"
            assert "취소" in r2["response_text"]

    def test_ambiguity_clarification(self, app):
        """동명이인 되묻기 → 선택."""
        sid = SESSION_ID + "-minsu"
        with app.app_context():
            r1 = run_banking_agent(1, "민수에게 5만원 보내줘", session_id=sid)
            assert r1["pending_state"] == "awaiting_clarification"
            assert len(r1["response_data"]["candidates"]) >= 2

            r2 = run_banking_agent(1, "1", session_id=sid)
            assert r2["pending_state"] == "awaiting_confirmation"

            r3 = run_banking_agent(1, "취소", session_id=sid)
            assert r3["pending_state"] == "none"

    def test_missing_amount_asks(self, app):
        sid = SESSION_ID + "-amount"
        with app.app_context():
            r1 = run_banking_agent(1, "지연한테 보내줘", session_id=sid)
            assert r1["pending_state"] == "awaiting_amount"

            r2 = run_banking_agent(1, "3만원", session_id=sid)
            assert r2["pending_state"] == "awaiting_confirmation"
            assert r2["response_data"]["amount"] == 30_000

            run_banking_agent(1, "취소", session_id=sid)

    def test_new_request_during_confirmation_handoff(self, app):
        """확인 대기 중 새 요청 → Command(PARENT) 로 Supervisor 재계획."""
        sid = SESSION_ID + "-handoff"
        with app.app_context():
            r1 = run_banking_agent(1, "동생한테 2만원 보내줘", session_id=sid)
            assert r1["pending_state"] == "awaiting_confirmation"

            r2 = run_banking_agent(1, "잔고 얼마야?", session_id=sid)
            assert r2["response_type"] == "balance"
            assert r2["pending_state"] == "none"

    def test_otp_flow(self, app):
        """300만원 이상 → OTP interrupt."""
        sid = SESSION_ID + "-otp"
        with app.app_context():
            r1 = run_banking_agent(1, "집주인한테 350만원 보내줘", session_id=sid)
            assert r1["pending_state"] == "awaiting_confirmation"

            r2 = run_banking_agent(1, "확인", session_id=sid)
            assert r2["pending_state"] == "awaiting_otp"

            r3 = run_banking_agent(1, "000000", session_id=sid)  # 오답
            assert r3["pending_state"] == "awaiting_otp"

            r4 = run_banking_agent(1, "123456", session_id=sid)
            assert r4["response_type"] == "success"

    def test_recurring_hint(self, app):
        with app.app_context():
            sid = SESSION_ID + "-wolse"
            r = run_banking_agent(1, "월세 보내야 하지?", session_id=sid)
            assert r["pending_state"] == "awaiting_confirmation"
            assert r["response_data"]["amount"] == 550_000
            run_banking_agent(1, "취소", session_id=sid)

    def test_bank_hint_disambiguates_recipient(self, app):
        """은행 힌트가 동명이인 후보를 좁힌다."""
        sid = SESSION_ID + "-bank-hint"
        with app.app_context():
            r = run_banking_agent(1, "구름뱅크 민수에게 5만원 보내줘", session_id=sid)
            assert r["pending_state"] == "awaiting_confirmation"
            assert r["response_data"]["recipient_name"] == "이민수"
            assert r["debug_info"]["extracted_slots"]["bank_hint"] == "구름뱅크"
            run_banking_agent(1, "취소", session_id=sid)

    def test_source_account_hint_selects_account(self, app):
        """출금계좌 힌트가 이체 요약의 출금 계좌에 반영된다."""
        sid = SESSION_ID + "-source-hint"
        with app.app_context():
            r = run_banking_agent(1, "비상금통장에서 엄마에게 5만원 보내줘", session_id=sid)
            assert r["pending_state"] == "awaiting_confirmation"
            assert r["response_data"]["source_account_name"] == "비상금통장"
            assert r["debug_info"]["extracted_slots"]["source_account_hint"] == "비상금통장"
            run_banking_agent(1, "취소", session_id=sid)

    def test_recommendation_followup_transfer_by_number(self, app):
        """추천 목록 조회 후 '1번'을 다음 턴 이체 수신자로 참조한다."""
        sid = SESSION_ID + "-rec-followup"
        with app.app_context():
            r1 = run_banking_agent(1, "자주 보내는 사람 추천해줘", session_id=sid)
            assert r1["response_type"] == "recommendation"
            first = r1["response_data"]["recommendations"][0]

            r2 = run_banking_agent(1, "1번한테 3만원 보내줘", session_id=sid)
            assert r2["pending_state"] == "awaiting_confirmation"
            assert r2["response_data"]["amount"] == 30_000
            assert r2["response_data"]["recipient_name"] == first["name"]

            run_banking_agent(1, "취소", session_id=sid)

    def test_history_followup_retransfer_by_number(self, app):
        """최근 이체내역 조회 후 '1번 내역대로' 재송금한다."""
        sid = SESSION_ID + "-hist-followup"
        with app.app_context():
            r1 = run_banking_agent(1, "최근 이체내역 보여줘", session_id=sid)
            assert r1["response_type"] == "history"
            first = r1["response_data"]["history"][0]

            r2 = run_banking_agent(1, "1번 내역대로 다시 보내줘", session_id=sid)
            assert r2["pending_state"] == "awaiting_confirmation"
            assert r2["response_data"]["amount"] == first["amount"]
            assert r2["response_data"]["recipient_name"] == first["name"]

            run_banking_agent(1, "취소", session_id=sid)


class TestAliasMemory:
    """호칭 학습 — 되묻기로 해소된 호칭이 세션을 넘어 기억된다."""

    def test_learn_and_recall(self, app):
        with app.app_context():
            # 1) 모르는 호칭 → 되묻기
            sid1 = SESSION_ID + "-gf1"
            r1 = run_banking_agent(1, "자기야한테 만원 보내줘", session_id=sid1)
            assert r1["pending_state"] == "awaiting_clarification"

            # 2) 이름으로 지정 → 학습
            r2 = run_banking_agent(1, "김서연", session_id=sid1)
            assert r2["pending_state"] == "awaiting_confirmation"
            run_banking_agent(1, "취소", session_id=sid1)

            # 3) *새 세션* 에서 즉시 해석
            sid2 = SESSION_ID + "-gf2"
            r3 = run_banking_agent(1, "자기야한테 2만원 보내줘", session_id=sid2)
            assert r3["pending_state"] == "awaiting_confirmation"
            assert "김서연" in r3["response_text"]
            run_banking_agent(1, "취소", session_id=sid2)

    def test_seeded_alias(self, app):
        """시드된 호칭(사용자3 '와이프')은 첫 사용부터 해석된다."""
        with app.app_context():
            sid = SESSION_ID + "-wife"
            r = run_banking_agent(3, "와이프한테 50만원 보내줘", session_id=sid)
            assert r["pending_state"] == "awaiting_confirmation"
            assert "최예린" in r["response_text"]
            run_banking_agent(3, "취소", session_id=sid)


class TestDynamicPrompting:
    def test_senior_tone_profile(self, app):
        with app.app_context():
            r = run_banking_agent(2, "잔고 보여줘", session_id=SESSION_ID + "-senior")
            assert r["user_profile"]["tone"] == "senior"
            # 시니어 글로서리: '일일 한도' 풀어쓰기
            assert "하루에 보낼 수 있는" in r["response_text"]

    def test_young_tone_profile(self, app):
        with app.app_context():
            r = run_banking_agent(1, "잔고 보여줘", session_id=SESSION_ID + "-young")
            assert r["user_profile"]["tone"] == "young"


class TestSecurityCollaboration:
    def test_security_consulted_on_transfer(self, app):
        """TransferAgent → SecurityAgent 협업이 활동 로그에 남는다."""
        sid = SESSION_ID + "-sec"
        with app.app_context():
            run_banking_agent(1, "엄마한테 1만원 보내줘", session_id=sid)
            r = run_banking_agent(1, "확인", session_id=sid)
            events = [(a["agent"], a["event"]) for a in r["agent_activity"]]
            assert ("transfer", "security_consult") in events
            assert ("security", "assess_done") in events

    def test_high_risk_user_force_otp(self, app):
        """보안 강화 고객(user3)은 100만원 이상에서 OTP 강제."""
        sid = SESSION_ID + "-risk"
        with app.app_context():
            r1 = run_banking_agent(3, "아버지한테 150만원 보내줘", session_id=sid)
            assert r1["pending_state"] == "awaiting_confirmation"
            r2 = run_banking_agent(3, "확인", session_id=sid)
            assert r2["pending_state"] == "awaiting_otp"
            run_banking_agent(3, "취소", session_id=sid)
