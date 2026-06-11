"""Balance and transfer limit queries."""

from __future__ import annotations

from datetime import date
from typing import List, Optional

from src.models.database import db, Account, TransferLimit, User


def get_primary_account(user_id: int) -> Optional[Account]:
    """Return the primary checking account for *user_id*."""
    return (
        db.session.query(Account)
        .filter(
            Account.user_id == user_id,
            Account.is_primary == True,
            Account.is_active == True,
        )
        .first()
    )


def get_all_accounts(user_id: int) -> List[Account]:
    return (
        db.session.query(Account)
        .filter(Account.user_id == user_id, Account.is_active == True)
        .all()
    )


def get_transfer_limit(user_id: int) -> Optional[TransferLimit]:
    tl = (
        db.session.query(TransferLimit)
        .filter(TransferLimit.user_id == user_id)
        .first()
    )
    if tl:
        _maybe_reset_daily(tl)
    return tl


def _maybe_reset_daily(tl: TransferLimit) -> None:
    today = date.today()
    if tl.last_reset_date != today:
        tl.daily_used = 0
        tl.last_reset_date = today
        db.session.add(tl)
        db.session.flush()


def get_balance_summary(user_id: int) -> dict:
    """Return a dict suitable for the balance display and agent response."""
    accounts = get_all_accounts(user_id)
    tl = get_transfer_limit(user_id)

    account_list = [
        {
            "id": a.id,
            "name": a.account_name,
            "number": a.account_number,
            "bank": a.bank_name,
            "type": a.account_type,
            "balance": a.balance,
            "is_primary": a.is_primary,
        }
        for a in accounts
    ]

    daily_limit = tl.daily_limit if tl else 0
    daily_used = tl.daily_used if tl else 0
    single_limit = tl.single_transfer_limit if tl else 0

    return {
        "accounts": account_list,
        "daily_limit": daily_limit,
        "daily_used": daily_used,
        "daily_remaining": max(0, daily_limit - daily_used),
        "single_transfer_limit": single_limit,
    }
