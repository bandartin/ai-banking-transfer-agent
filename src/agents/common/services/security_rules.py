"""
SecurityAgent 의 결정론적 사기탐지/리스크 룰 엔진.

LLM 은 여기 관여하지 않는다 — 모든 룰은 코드와 데이터로 평가된다.
TransferAgent 가 확인 카드를 띄우기 전에 이 평가를 의뢰(A2A 협업)하고,
결과(risk_score, force_otp, warnings)가 확인 카드에 반영된다.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from src.models.database import db, Favorite, Recipient, TransferHistory
from src.agents.context import BankingContext
from src.agents.common.schemas import RiskAssessment, TransferSummary


def assess_transfer(ctx: BankingContext, user_id: int, summary: TransferSummary) -> RiskAssessment:
    """이체 1건에 대한 리스크 평가."""
    score = 0
    rules: list[str] = []
    warnings: list[str] = []
    force_otp = False

    amount = summary.amount

    # R1 — 고액 이체 (OTP 임계값 이상): 기존 OTP 정책
    if amount >= ctx.otp_threshold:
        score += 30
        rules.append("R1_high_amount")

    # R2 — 심야 시간대(23~06시) 100만원 이상
    hour = datetime.now().hour
    if (hour >= 23 or hour < 6) and amount >= 1_000_000:
        score += 25
        rules.append("R2_night_large")
        warnings.append("심야 시간대 고액 이체입니다. 보이스피싱이 의심되면 즉시 중단하세요.")

    # R3 — 익숙하지 않은 수신자 + 50만원 이상
    fav = (
        db.session.query(Favorite)
        .join(Recipient, Favorite.recipient_id == Recipient.id)
        .filter(
            Favorite.user_id == user_id,
            Recipient.account_number == summary.recipient_account,
        )
        .first()
    )
    send_count = fav.send_count if fav else 0
    if send_count < 2 and amount >= 500_000:
        score += 25
        rules.append("R3_unfamiliar_recipient")
        warnings.append(
            f"'{summary.recipient_name}'님과의 이체 이력이 거의 없습니다. 수신자 정보를 다시 확인해 주세요."
        )

    # R4 — 단시간 다건 (최근 10분 내 3건 이상)
    recent_count = (
        db.session.query(TransferHistory)
        .filter(
            TransferHistory.user_id == user_id,
            TransferHistory.status == "completed",
            TransferHistory.transferred_at >= datetime.utcnow() - timedelta(minutes=10),
        )
        .count()
    )
    if recent_count >= 3:
        score += 20
        rules.append("R4_burst")
        warnings.append("짧은 시간에 여러 건의 이체가 발생했습니다.")

    # R5 — 리스크 프로필 고객: 임계값 강화 (100만원부터 OTP)
    if ctx.risk_profile == "high":
        score += 10
        rules.append("R5_high_risk_profile")
        if amount >= 1_000_000:
            force_otp = True
            warnings.append("고객님 계정은 보안 강화 대상입니다. 100만원 이상 이체에 OTP가 필요합니다.")

    level = "high" if score >= 50 else "medium" if score >= 25 else "low"
    return RiskAssessment(
        risk_score=min(score, 100),
        level=level,
        triggered_rules=rules,
        warnings=warnings,
        force_otp=force_otp,
    )


def security_report(ctx: BankingContext, user_id: int) -> dict:
    """단독 호출용 보안 리포트 ("내 계좌 안전해?")."""
    since = datetime.utcnow() - timedelta(days=7)
    recent = (
        db.session.query(TransferHistory)
        .filter(TransferHistory.user_id == user_id, TransferHistory.transferred_at >= since)
        .all()
    )
    night = [t for t in recent if t.transferred_at.hour >= 23 or t.transferred_at.hour < 6]
    large = [t for t in recent if t.amount >= ctx.otp_threshold]

    return {
        "week_transfer_count": len(recent),
        "week_total_amount": sum(t.amount for t in recent),
        "night_transfers": len(night),
        "large_transfers": len(large),
        "risk_profile": ctx.risk_profile,
        "otp_threshold": ctx.otp_threshold,
    }
