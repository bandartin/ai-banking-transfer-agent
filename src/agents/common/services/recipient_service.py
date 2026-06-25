"""Recipient resolution service.

The function names and return dictionaries match the original mock
implementation, but the actual lookup is delegated to the configured banking
adapter.  That keeps TransferAgent stable while allowing a future IBK adapter to
resolve favorites, registered recipients, and recurring-transfer templates from
real systems.
"""

from __future__ import annotations

from typing import List, Optional

from src.integrations import get_banking_adapter


def find_by_alias(user_id: int, alias: str) -> List[dict]:
    """Return all registered recipient entries matching *alias* for *user_id*."""
    return get_banking_adapter().find_recipients_by_alias(user_id, alias)


def find_by_recurring_hint(user_id: int, hint: str) -> Optional[dict]:
    """Return the first matching recurring transfer template for *hint*."""
    return get_banking_adapter().find_recurring_transfer(user_id, hint)


def find_last_transfer(user_id: int) -> Optional[dict]:
    """Return the most recent completed transfer for *user_id*."""
    return get_banking_adapter().find_last_transfer(user_id)


def get_top_recipients(user_id: int, limit: int = 5) -> List[dict]:
    """Return top recipients scored by recency and frequency."""
    return get_banking_adapter().get_top_recipients(user_id, limit=limit)

