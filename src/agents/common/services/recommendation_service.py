"""Recipient recommendation service.

Today this returns recommendations from the mock SQLAlchemy adapter.  In a real
IBK deployment the same function can be backed by a batch snapshot, an analytic
feature store, or a recommendation API, while RecommendAgent keeps the same
simple call signature.
"""

from __future__ import annotations

from typing import List

from src.agents.common.schemas import RecipientRecommendation
from src.integrations import get_banking_adapter


def get_recommendations(user_id: int, limit: int = 5) -> List[RecipientRecommendation]:
    """Return the top *limit* recommended recipients for *user_id*."""
    return get_banking_adapter().get_recommendations(user_id, limit=limit)

