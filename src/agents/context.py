"""
BankingContext — LangGraph Runtime context schema.

[Runtime 학습 포인트]
State 와 Context 의 분리가 LangGraph 1.x Runtime 의 핵심입니다.

  · State   : 대화가 진행되며 노드가 읽고 *변경*하는 데이터 (의도, 금액, 검증결과 …)
              → 체크포인터에 저장되어 턴 사이에 유지됨
  · Context : 한 번의 invoke 동안 *불변*인 실행 환경/의존성 (사용자 정보, LLM 설정 …)
              → graph.invoke(state, context=BankingContext(...)) 로 매 호출 주입
              → 노드 시그니처 (state, runtime: Runtime[BankingContext]) 로 접근

이 프로젝트에서 Context 는 세 가지 문제를 해결합니다:
  1. Flask(current_app) 결합 제거 — 에이전트가 웹 없이도(A2A·테스트) 동작
  2. Dynamic Prompting 입력원 — 나이/등급/리스크에 따라 프롬프트·말투가 달라짐
  3. 테스트 용이성 — context 주입만으로 LLM on/off, 사용자 프로필 강제 가능
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BankingContext:
    """Immutable per-invocation execution context for the banking agents."""

    # ── 사용자 식별/프로필 (Dynamic Prompting 의 입력원) ─────────────────────
    user_id: int
    session_id: str
    display_name: str = ""
    age: Optional[int] = None            # 나이 → 말투/설명 수준 결정
    customer_tier: str = "standard"      # "standard" | "vip"
    risk_profile: str = "normal"         # "normal" | "high" → 보안 에이전트 강화

    # ── LLM 설정 (키가 없으면 결정론적 파서로 폴백) ──────────────────────────
    llm_provider: str = "deterministic"  # "openai" | "deterministic"
    openai_model: str = "gpt-4o-mini"
    openai_api_key: str = ""

    # ── 비즈니스 정책 (코드 상수 대신 컨텍스트로 주입) ───────────────────────
    interbank_fee: int = 500
    otp_threshold: int = 3_000_000
    demo_otp_code: str = "123456"
    source_bank_name: str = "으뜸은행"

    @property
    def llm_enabled(self) -> bool:
        return self.llm_provider == "openai" and bool(self.openai_api_key)

    @property
    def tone(self) -> str:
        """나이 기반 말투 프로필 — Dynamic Prompting 에서 사용."""
        if self.age is None:
            return "standard"
        if self.age >= 60:
            return "senior"      # 차분하고 자세한 설명, 금융용어 풀어쓰기
        if self.age < 35:
            return "young"       # 간결, 친근한 존댓말, 이모지 약간
        return "standard"        # 표준 존댓말


def build_context(app_config: dict, user, session_id: str) -> BankingContext:
    """Flask config + User ORM row → BankingContext.

    이 함수가 Flask 와 에이전트 사이의 유일한 접점입니다.
    노드들은 절대 current_app 을 읽지 않고 runtime.context 만 사용합니다.
    """
    provider = app_config.get("LLM_PROVIDER", "deterministic")
    api_key = app_config.get("OPENAI_API_KEY", "")
    if provider == "openai" and not api_key:
        provider = "deterministic"  # 키 없으면 자동 폴백

    return BankingContext(
        user_id=user.id,
        session_id=session_id,
        display_name=user.display_name,
        age=user.age,
        customer_tier=getattr(user, "customer_tier", "standard") or "standard",
        risk_profile=getattr(user, "risk_profile", "normal") or "normal",
        llm_provider=provider,
        openai_model=app_config.get("OPENAI_MODEL", "gpt-4o-mini"),
        openai_api_key=api_key,
        interbank_fee=app_config.get("INTERBANK_FEE", 500),
        otp_threshold=app_config.get("OTP_THRESHOLD", 3_000_000),
        demo_otp_code=app_config.get("DEMO_OTP_CODE", "123456"),
        source_bank_name=app_config.get("SOURCE_BANK_NAME", "으뜸은행"),
    )
