"""Balance and transfer limit queries.

The public functions in this module are kept for compatibility with the
existing agents and tests.  Internally they now delegate to the integration
adapter so the same agent code can run against the current mock DB or a future
IBK account/limit API.
"""

from __future__ import annotations

from datetime import date
from typing import List, Optional

from src.integrations import get_banking_adapter
from src.models.database import db, Account, TransferLimit


def get_primary_account(user_id: int) -> Optional[Account]:
    """Return the primary checking account for *user_id*."""
    return get_banking_adapter().get_primary_account(user_id)


def get_all_accounts(user_id: int) -> List[Account]:
    return get_banking_adapter().get_all_accounts(user_id)


def find_account_by_hint(user_id: int, hint: str) -> Optional[Account]:
    """Find an active source account by account name/type/number fragment."""
    return get_banking_adapter().find_account_by_hint(user_id, hint)


def get_transfer_limit(user_id: int) -> Optional[TransferLimit]:
    return get_banking_adapter().get_transfer_limit(user_id)


def _maybe_reset_daily(tl: TransferLimit) -> None:
    """Compatibility helper for code/tests that still import this symbol."""
    today = date.today()
    if tl.last_reset_date != today:
        tl.daily_used = 0
        tl.last_reset_date = today
        db.session.add(tl)
        db.session.flush()


def get_balance_summary(user_id: int) -> dict:
    """Return a dict suitable for the balance display and agent response."""
    return get_banking_adapter().get_balance_summary(user_id)
