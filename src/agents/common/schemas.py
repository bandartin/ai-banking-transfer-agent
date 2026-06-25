"""
Pydantic schemas — structured extraction, planning, validation, API contracts.
"""

from __future__ import annotations

from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# Supervisor execution plan (LLM structured output)
# ─────────────────────────────────────────────────────────────────────────────


AgentName = Literal[
    "transfer",
    "inquiry",
    "recommend",
    "security",
    "menu_search",
    "product_guide",
    "financial_calculator",
    "tool_agent",
]


class PlanStep(BaseModel):
    """Supervisor 가 하위 에이전트에게 내리는 작업 한 건."""

    agent: AgentName = Field(description="호출할 하위 에이전트")
    sub_intent: str = Field(
        description=(
            "에이전트 내 세부 작업: inquiry→balance|history|recurring, "
            "recommend→recipients, security→report, transfer→transfer, "
            "menu_search→menu, product_guide→guide, financial_calculator→calculate"
        )
    )
    reason: str = Field("", description="이 에이전트를 선택한 이유 (가시화용)")


class ExecutionPlan(BaseModel):
    """Supervisor planning 결과 — 병렬 단계는 Send 로 fan-out 된다."""

    steps: List[PlanStep] = Field(default_factory=list)
    parallel: bool = Field(False, description="steps 를 병렬 실행할지 여부")
    primary_intent: str = Field("unknown", description="대표 인텐트 (로그/UI용)")
    planner: str = Field("rule", description="'llm' | 'rule' — 계획 생성 주체")
    note: str = Field("", description="플래너 메모 (가시화용)")


# ─────────────────────────────────────────────────────────────────────────────
# Slot extraction result
# ─────────────────────────────────────────────────────────────────────────────


class ExtractedSlots(BaseModel):
    """Slots extracted from a single user utterance."""

    raw_amount_text: Optional[str] = Field(None, description="원문 금액 표현")
    recipient_text: Optional[str] = Field(None, description="원문 수신자 표현")
    recipient_alias: Optional[str] = Field(None, description="수신자 별칭 (엄마, 여친, 민수 등)")
    amount: Optional[int] = Field(None, description="이체 금액 (KRW 정수)")
    memo: Optional[str] = Field(None, description="이체 메모")
    use_last_transfer: bool = Field(False, description="'지난번처럼' 패턴 감지 여부")
    recurring_hint: Optional[str] = Field(None, description="반복이체 키워드 (월세, 관리비 등)")
    bank_hint: Optional[str] = Field(None, description="수신 은행 힌트")
    source_account_hint: Optional[str] = Field(None, description="출금 계좌 힌트")
    confidence: float = Field(1.0, ge=0.0, le=1.0, description="슬롯 추출 신뢰도")
    ambiguous_fields: List[str] = Field(default_factory=list, description="불확실하거나 교차검증이 필요한 필드")
    missing_fields: List[str] = Field(default_factory=list, description="이체 실행에 필요한데 누락된 필드")
    evidence: Dict[str, str] = Field(default_factory=dict, description="슬롯별 근거가 된 원문 조각")
    extraction_method: str = Field("rule", description="'rule' | 'llm' | 'llm+rule_cross_check'")


# ─────────────────────────────────────────────────────────────────────────────
# Security agent — risk assessment
# ─────────────────────────────────────────────────────────────────────────────


class RiskAssessment(BaseModel):
    """SecurityAgent 의 결정론적 리스크 평가 결과."""

    risk_score: int = Field(0, ge=0, le=100)
    level: str = Field("low", description="'low' | 'medium' | 'high'")
    triggered_rules: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    force_otp: bool = Field(False, description="규칙상 금액과 무관하게 OTP 강제")


# ─────────────────────────────────────────────────────────────────────────────
# Transfer domain schemas
# ─────────────────────────────────────────────────────────────────────────────


class TransferSummary(BaseModel):
    """Complete transfer details ready for user confirmation."""

    source_account_id: int
    source_account_name: str
    source_account_number: str
    current_balance: int

    recipient_name: str
    recipient_bank: str
    recipient_account: str
    recipient_alias: Optional[str] = None

    amount: int
    fee: int
    total_deducted: int  # amount + fee
    remaining_balance: int  # current_balance - total_deducted

    memo: Optional[str] = None
    requires_otp: bool = False
    warnings: List[str] = []


class ValidationResult(BaseModel):
    passed: bool
    errors: List[str] = []
    warnings: List[str] = []


class TransferResult(BaseModel):
    success: bool
    transfer_id: Optional[int] = None
    new_balance: Optional[int] = None
    error_message: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Recommendation
# ─────────────────────────────────────────────────────────────────────────────


class RecipientRecommendation(BaseModel):
    rank: int
    favorite_id: Optional[int] = None
    recipient_id: Optional[int] = None
    alias: Optional[str]
    name: str
    bank_name: str
    account_number: str
    score: float
    reason: str  # "즐겨찾기", "최근 이체", "자동이체"
    suggested_amount: Optional[int] = None
