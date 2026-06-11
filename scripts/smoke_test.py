"""수동 스모크 테스트 — 전체 멀티 에이전트 파이프라인을 시나리오별로 실행한다.

실행:  .venv\\Scripts\\python.exe scripts\\smoke_test.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# .env 의 LangSmith 설정이 스모크 실행을 방해하지 않도록 선제 차단
os.environ["LANGCHAIN_TRACING_V2"] = "false"

from app import create_app
from config import Config


class SmokeConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    LLM_PROVIDER = "deterministic"
    CHECKPOINT_DB_PATH = ":memory:"
    LANGSMITH_ENABLED = False


def main():
    from src.agents.supervisor.graph import reset_graph_singleton
    reset_graph_singleton()

    app = create_app(SmokeConfig)
    with app.app_context():
        import seed
        seed.run(app)

        from src.agents.supervisor import run_banking_agent

        def turn(user_id, msg, sid, label=""):
            r = run_banking_agent(user_id, msg, session_id=sid)
            print(f"\n=== [{label}] U{user_id}: {msg}")
            print(f"  intent={r['intent']} type={r['response_type']} pending={r['pending_state']}")
            plan = r.get("plan") or {}
            steps = [(s['agent'], s['sub_intent']) for s in plan.get('steps', [])]
            print(f"  plan={steps} parallel={plan.get('parallel')}")
            print(f"  activity={[(a['agent'], a['event']) for a in r.get('agent_activity', [])]}")
            print("  " + r["response_text"][:200].replace("\n", "\n  "))
            return r

        # 1. 잔고 조회
        turn(1, "내 잔고 보여줘", "s1", "단일 조회")

        # 2. 병렬: 잔고 + 추천
        r = turn(1, "잔고 보여주고 자주 보내는 사람도 추천해줘", "s2", "병렬 fan-out")
        assert (r.get("plan") or {}).get("parallel"), "병렬 계획이어야 함"

        # 3. 이체 확인 → 확인 (interrupt 멀티턴)
        r = turn(1, "엄마에게 5만원 보내줘", "s3", "이체 요청")
        assert r["pending_state"] == "awaiting_confirmation", r["pending_state"]
        r = turn(1, "확인", "s3", "이체 확인")
        assert r["response_type"] == "success", r["response_type"]

        # 4. 모호성: 민수 → 선택 → 확인 (이후 학습 검증)
        r = turn(1, "민수에게 3만원 보내줘", "s4", "동명이인")
        assert r["pending_state"] == "awaiting_clarification", r["pending_state"]
        r = turn(1, "1", "s4", "후보 선택")
        assert r["pending_state"] == "awaiting_confirmation", r["pending_state"]
        r = turn(1, "취소", "s4", "취소")
        assert "취소" in r["response_text"]

        # 5. 호칭 학습: 여친 → 되묻기 → 김서연 지정 → 다음 세션 즉시 해석
        r = turn(1, "여친한테 2만원 보내줘", "s5", "모르는 호칭")
        assert r["pending_state"] == "awaiting_clarification", r["pending_state"]
        r = turn(1, "김서연", "s5", "호칭 지정")
        assert r["pending_state"] == "awaiting_confirmation", r["pending_state"]
        r = turn(1, "확인", "s5", "이체 확인")
        assert r["response_type"] == "success", r["response_type"]
        # 새 세션에서 '여친' 즉시 해석 (학습 효과)
        r = turn(1, "여친한테 1만원 보내줘", "s6", "학습된 호칭 (새 세션)")
        assert r["pending_state"] == "awaiting_confirmation", f"학습 실패: {r['pending_state']}"
        assert "서연" in r["response_text"] or "김서연" in r["response_text"]
        turn(1, "취소", "s6", "취소")

        # 6. OTP 플로우 (300만원 이상)
        r = turn(1, "집주인한테 400만원 보내줘", "s7", "고액 이체")
        assert r["pending_state"] == "awaiting_confirmation", r["pending_state"]
        r = turn(1, "확인", "s7", "확인 → OTP 요청")
        assert r["pending_state"] == "awaiting_otp", r["pending_state"]
        r = turn(1, "123456", "s7", "OTP 입력")
        assert r["response_type"] == "success", r["response_type"]

        # 7. 확인 대기 중 새 요청 → Supervisor 핸드오프
        r = turn(1, "지연한테 만원 보내줘", "s8", "이체 요청")
        assert r["pending_state"] == "awaiting_confirmation", r["pending_state"]
        r = turn(1, "잔고 얼마지?", "s8", "확인 중 새 요청 → 재계획")
        assert r["response_type"] == "balance", r["response_type"]

        # 8. 금액 누락 → 되묻기
        r = turn(1, "엄마한테 보내줘", "s9", "금액 누락")
        assert r["pending_state"] == "awaiting_amount", r["pending_state"]
        r = turn(1, "5만원", "s9", "금액 입력")
        assert r["pending_state"] == "awaiting_confirmation", r["pending_state"]
        turn(1, "취소", "s9", "취소")

        # 9. 정기이체 힌트
        r = turn(1, "월세 보내야 하지?", "s10", "정기이체")
        assert r["pending_state"] == "awaiting_confirmation", r["pending_state"]
        turn(1, "취소", "s10", "취소")

        # 10. 시니어 사용자 말투 (user 2)
        r = turn(2, "잔고 보여줘", "s11", "시니어 말투")
        assert r["user_profile"]["tone"] == "senior", r["user_profile"]

        # 11. 시드된 호칭 메모리 (user 3: 와이프)
        r = turn(3, "와이프한테 50만원 보내줘", "s12", "시드 호칭")
        assert r["pending_state"] == "awaiting_confirmation", r["pending_state"]
        turn(3, "취소", "s12", "취소")

        # 12. 보안 강화 고객(user3) 100만원 이상 → force OTP
        r = turn(3, "아버지한테 200만원 보내줘", "s13", "리스크 고객 이체")
        assert r["pending_state"] == "awaiting_confirmation"
        r = turn(3, "확인", "s13", "확인 → 강화 OTP")
        assert r["pending_state"] == "awaiting_otp", f"force_otp 실패: {r['pending_state']}"
        turn(3, "취소", "s13", "취소")

        # 13. 확인 중 금액 수정
        r = turn(1, "동생한테 5만원 보내줘", "s14", "이체 요청")
        r = turn(1, "아니 3만원으로 해줘", "s14", "금액 수정")
        assert r["pending_state"] == "awaiting_confirmation"
        assert "30,000" in r["response_text"], r["response_text"][:200]
        turn(1, "취소", "s14", "취소")

        print("\n\n✅ 모든 스모크 시나리오 통과!")


if __name__ == "__main__":
    main()
