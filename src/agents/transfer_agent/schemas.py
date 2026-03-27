"""
Pydantic schemas used for structured extraction, validation, and API contracts.
"""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# Slot extraction result
# ─────────────────────────────────────────────────────────────────────────────


class ExtractedSlots(BaseModel):
    """Slots extracted from a single user utterance."""

    recipient_alias: Optional[str] = Field(None, description="수신자 별칭 (엄마, 민수 등)")
    amount: Optional[int] = Field(None, description="이체 금액 (KRW 정수)")
    memo: Optional[str] = Field(None, description="이체 메모")
    use_last_transfer: bool = Field(False, description="'지난번처럼' 패턴 감지 여부")
    recurring_hint: Optional[str] = Field(None, description="반복이체 키워드 (월세, 관리비 등)")
    bank_hint: Optional[str] = Field(None, description="수신 은행 힌트")


# ─────────────────────────────────────────────────────────────────────────────
# Resolved recipient
# ─────────────────────────────────────────────────────────────────────────────


class ResolvedRecipient(BaseModel):
    """A fully resolved transfer target."""

    favorite_id: Optional[int] = None
    recipient_id: int
    alias: Optional[str] = None
    name: str
    bank_name: str
    account_number: str
    source: str = Field(description="'favorite' | 'history' | 'recurring'")
    confidence: float = Field(1.0, ge=0.0, le=1.0)


class AmbiguityCandidate(BaseModel):
    """One entry in a list of ambiguous recipient candidates."""

    index: int  # 1-based, for display ("1번", "2번")
    favorite_id: Optional[int] = None
    recipient_id: int
    alias: Optional[str] = None
    name: str
    bank_name: str
    account_number: str


# ─────────────────────────────────────────────────────────────────────────────
# Transfer summary (shown in confirmation card)
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


# ─────────────────────────────────────────────────────────────────────────────
# Validation result
# ─────────────────────────────────────────────────────────────────────────────


class ValidationResult(BaseModel):
    passed: bool
    errors: List[str] = []
    warnings: List[str] = []


# ─────────────────────────────────────────────────────────────────────────────
# Transfer execution result
# ─────────────────────────────────────────────────────────────────────────────


class TransferResult(BaseModel):
    success: bool
    transfer_id: Optional[int] = None
    new_balance: Optional[int] = None
    error_message: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Balance info
# ─────────────────────────────────────────────────────────────────────────────


class BalanceInfo(BaseModel):
    accounts: List[dict]  # list of {name, number, balance, available_today}
    daily_limit: int
    daily_used: int
    daily_remaining: int
    single_transfer_limit: int


# ─────────────────────────────────────────────────────────────────────────────
# Recommendation
# ─────────────────────────────────────────────────────────────────────────────


class RecipientRecommendation(BaseModel):
    rank: int
    alias: Optional[str]
    name: str
    bank_name: str
    account_number: str
    score: float
    reason: str  # "즐겨찾기", "최근 이체", "자동이체"
    suggested_amount: Optional[int] = None
