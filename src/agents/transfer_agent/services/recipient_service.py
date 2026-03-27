"""
Deterministic recipient resolution service.

Priority order:
  1. Exact alias match in favorites
  2. Partial alias match in favorites
  3. Recent transfer history
  4. Recurring transfer templates
"""

from __future__ import annotations

from typing import List, Optional

from src.models.database import db, Favorite, Recipient, RecurringTransfer, TransferHistory


def find_by_alias(user_id: int, alias: str) -> List[dict]:
    """
    Return all favorite entries matching *alias* for *user_id*.

    Matching strategy (in order):
      1. Case-insensitive exact match on Favorite.alias
      2. Case-insensitive exact match on Recipient.name
      3. Partial (contains) match on either
    """
    if not alias:
        return []

    alias_lower = alias.strip().lower()

    # 1 & 2 – exact matches first
    exact: List[Favorite] = (
        db.session.query(Favorite)
        .join(Recipient, Favorite.recipient_id == Recipient.id)
        .filter(
            Favorite.user_id == user_id,
            db.or_(
                db.func.lower(Favorite.alias) == alias_lower,
                db.func.lower(Recipient.name) == alias_lower,
            ),
        )
        .all()
    )

    if exact:
        return [_fav_to_dict(f) for f in exact]

    # 3 – partial matches
    partial: List[Favorite] = (
        db.session.query(Favorite)
        .join(Recipient, Favorite.recipient_id == Recipient.id)
        .filter(
            Favorite.user_id == user_id,
            db.or_(
                db.func.lower(Favorite.alias).contains(alias_lower),
                db.func.lower(Recipient.name).contains(alias_lower),
            ),
        )
        .all()
    )

    return [_fav_to_dict(f) for f in partial]


def find_by_recurring_hint(user_id: int, hint: str) -> Optional[dict]:
    """
    Return the first matching recurring transfer template for the given hint
    keyword (e.g. "월세", "관리비").
    """
    if not hint:
        return None

    hint_lower = hint.strip().lower()

    rt: Optional[RecurringTransfer] = (
        db.session.query(RecurringTransfer)
        .filter(
            RecurringTransfer.user_id == user_id,
            RecurringTransfer.is_active == True,
            db.func.lower(RecurringTransfer.alias).contains(hint_lower),
        )
        .first()
    )

    if rt is None:
        return None

    return _recurring_to_dict(rt)


def find_last_transfer(user_id: int) -> Optional[dict]:
    """Return the most recent completed transfer for *user_id*."""
    th: Optional[TransferHistory] = (
        db.session.query(TransferHistory)
        .filter(
            TransferHistory.user_id == user_id,
            TransferHistory.status == "completed",
        )
        .order_by(TransferHistory.transferred_at.desc())
        .first()
    )

    if th is None:
        return None

    return _history_to_dict(th)


def get_top_recipients(user_id: int, limit: int = 5) -> List[dict]:
    """
    Return top recipients scored by recency × frequency.
    Favorites are boosted.
    """
    favs: List[Favorite] = (
        db.session.query(Favorite)
        .filter(Favorite.user_id == user_id)
        .order_by(Favorite.send_count.desc(), Favorite.last_sent_at.desc())
        .limit(limit)
        .all()
    )
    return [_fav_to_dict(f) for f in favs]


# ─────────────────────────────────────────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────────────────────────────────────────


def _fav_to_dict(f: Favorite) -> dict:
    r: Recipient = f.recipient
    return {
        "type": "favorite",
        "favorite_id": f.id,
        "recipient_id": r.id,
        "alias": f.alias,
        "name": r.name,
        "bank_name": r.bank_name,
        "account_number": r.account_number,
        "send_count": f.send_count,
        "last_sent_at": f.last_sent_at.isoformat() if f.last_sent_at else None,
        "is_favorite": f.is_favorite,
    }


def _recurring_to_dict(rt: RecurringTransfer) -> dict:
    result = {
        "type": "recurring",
        "recurring_id": rt.id,
        "alias": rt.alias,
        "default_amount": rt.default_amount,
        "memo": rt.memo,
        "day_of_month": rt.day_of_month,
        "favorite_id": rt.favorite_id,
        "recipient_id": None,
        "name": None,
        "bank_name": None,
        "account_number": None,
    }

    if rt.favorite and rt.favorite.recipient:
        r = rt.favorite.recipient
        result["recipient_id"] = r.id
        result["name"] = r.name
        result["bank_name"] = r.bank_name
        result["account_number"] = r.account_number

    return result


def _history_to_dict(th: TransferHistory) -> dict:
    r: Recipient = th.recipient
    return {
        "type": "history",
        "transfer_id": th.id,
        "favorite_id": th.favorite_id,
        "recipient_id": r.id,
        "alias": th.favorite.alias if th.favorite else None,
        "name": r.name,
        "bank_name": r.bank_name,
        "account_number": r.account_number,
        "amount": th.amount,
        "memo": th.memo,
        "transferred_at": th.transferred_at.isoformat(),
    }
