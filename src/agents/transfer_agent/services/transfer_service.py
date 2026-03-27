"""
Deterministic transfer business logic.

All validation and execution is implemented as pure Python logic against
SQLite state.  The LLM is never involved in these decisions.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from flask import current_app

from src.models.database import (
    db,
    Account,
    AuditLog,
    Favorite,
    Recipient,
    TransferHistory,
    TransferLimit,
)
from src.agents.transfer_agent.schemas import (
    TransferSummary,
    ValidationResult,
    TransferResult,
)
from src.agents.transfer_agent.services.balance_service import (
    get_primary_account,
    get_transfer_limit,
    _maybe_reset_daily,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fee calculation
# ─────────────────────────────────────────────────────────────────────────────


def calculate_fee(source_bank: str, destination_bank: str) -> int:
    """
    Same-bank transfers are free; all other transfers cost INTERBANK_FEE (KRW).
    """
    fee = current_app.config.get("INTERBANK_FEE", 500)
    if source_bank == destination_bank:
        return 0
    return fee


# ─────────────────────────────────────────────────────────────────────────────
# Build transfer summary
# ─────────────────────────────────────────────────────────────────────────────


def build_transfer_summary(
    user_id: int,
    recipient_data: dict,
    amount: int,
    memo: Optional[str] = None,
) -> Optional[TransferSummary]:
    """Assemble a TransferSummary from resolved data, ready for validation."""
    source_account = get_primary_account(user_id)
    if not source_account:
        return None

    fee = calculate_fee(source_account.bank_name, recipient_data["bank_name"])
    total = amount + fee
    otp_threshold = current_app.config.get("OTP_THRESHOLD", 3_000_000)

    return TransferSummary(
        source_account_id=source_account.id,
        source_account_name=source_account.account_name,
        source_account_number=source_account.account_number,
        current_balance=source_account.balance,
        recipient_name=recipient_data["name"],
        recipient_bank=recipient_data["bank_name"],
        recipient_account=recipient_data["account_number"],
        recipient_alias=recipient_data.get("alias"),
        amount=amount,
        fee=fee,
        total_deducted=total,
        remaining_balance=source_account.balance - total,
        memo=memo,
        requires_otp=amount >= otp_threshold,
        warnings=[],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Pre-validation (deterministic — no LLM)
# ─────────────────────────────────────────────────────────────────────────────


def validate_transfer(user_id: int, summary: TransferSummary) -> ValidationResult:
    """Run all pre-transfer checks.  Returns a ValidationResult."""
    errors = []
    warnings = []

    # 1. Source account active
    account = db.session.get(Account, summary.source_account_id)
    if not account or not account.is_active:
        errors.append("출금 계좌가 비활성 상태입니다.")
        return ValidationResult(passed=False, errors=errors)

    # 2. Sufficient balance
    if account.balance < summary.total_deducted:
        shortage = summary.total_deducted - account.balance
        errors.append(
            f"잔액이 부족합니다. "
            f"필요 금액: {_fmt(summary.total_deducted)}원, "
            f"현재 잔액: {_fmt(account.balance)}원 "
            f"(부족액: {_fmt(shortage)}원)"
        )

    # 3. Single transfer limit
    tl = get_transfer_limit(user_id)
    if tl and summary.amount > tl.single_transfer_limit:
        errors.append(
            f"1회 이체 한도를 초과했습니다. "
            f"요청: {_fmt(summary.amount)}원, "
            f"한도: {_fmt(tl.single_transfer_limit)}원"
        )

    # 4. Daily limit
    if tl:
        remaining = tl.daily_limit - tl.daily_used
        if summary.amount > remaining:
            errors.append(
                f"일일 이체 한도를 초과했습니다. "
                f"오늘 남은 한도: {_fmt(remaining)}원, "
                f"요청: {_fmt(summary.amount)}원"
            )

    # 5. Minimum amount
    if summary.amount <= 0:
        errors.append("이체 금액은 0원보다 커야 합니다.")

    # Warnings
    if summary.remaining_balance < 10_000:
        warnings.append("이체 후 잔액이 1만원 미만이 됩니다.")

    return ValidationResult(
        passed=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Transfer execution (atomic DB transaction)
# ─────────────────────────────────────────────────────────────────────────────


def execute_transfer(
    user_id: int,
    summary: TransferSummary,
    favorite_id: Optional[int] = None,
) -> TransferResult:
    """
    Execute the transfer atomically.

    Steps inside a single DB transaction:
      1. Deduct balance from source account
      2. Insert TransferHistory record
      3. Update TransferLimit daily_used
      4. Update Favorite.send_count / last_sent_at
      5. Insert AuditLog entry
    """
    try:
        account = db.session.get(Account, summary.source_account_id)
        if not account:
            return TransferResult(success=False, error_message="출금 계좌를 찾을 수 없습니다.")

        # Retrieve recipient — look up by account number + bank
        recipient = (
            db.session.query(Recipient)
            .filter(
                Recipient.account_number == summary.recipient_account,
                Recipient.bank_name == summary.recipient_bank,
            )
            .first()
        )
        if not recipient:
            return TransferResult(success=False, error_message="수신 계좌 정보를 확인할 수 없습니다.")

        # 1. Deduct balance
        account.balance -= summary.total_deducted

        # 2. Create history record
        th = TransferHistory(
            user_id=user_id,
            source_account_id=summary.source_account_id,
            recipient_id=recipient.id,
            favorite_id=favorite_id,
            amount=summary.amount,
            fee=summary.fee,
            memo=summary.memo,
            status="completed",
            transferred_at=datetime.utcnow(),
        )
        db.session.add(th)

        # 3. Update daily limit used
        tl = get_transfer_limit(user_id)
        if tl:
            _maybe_reset_daily(tl)
            tl.daily_used += summary.amount

        # 4. Update favorite stats
        if favorite_id:
            fav = db.session.get(Favorite, favorite_id)
            if fav:
                fav.send_count = (fav.send_count or 0) + 1
                fav.last_sent_at = datetime.utcnow()

        # 5. Audit log
        audit = AuditLog(
            user_id=user_id,
            action="transfer_executed",
            entity_type="transfer_history",
            details_json=json.dumps(
                {
                    "summary": summary.model_dump(),
                    "favorite_id": favorite_id,
                },
                ensure_ascii=False,
                default=str,
            ),
        )
        db.session.add(audit)

        db.session.commit()
        db.session.refresh(account)

        return TransferResult(
            success=True,
            transfer_id=th.id,
            new_balance=account.balance,
        )

    except Exception as exc:
        db.session.rollback()
        return TransferResult(
            success=False,
            error_message=f"이체 처리 중 오류가 발생했습니다: {exc}",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────


def _fmt(amount: int) -> str:
    """Format integer KRW with comma separators."""
    return f"{amount:,}"
