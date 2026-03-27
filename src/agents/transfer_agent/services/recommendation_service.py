"""
Recipient recommendation engine.

Scoring model:
  - Favorites flagged as is_favorite: +50
  - Each past send: +2 (capped at +20)
  - Recency: +10 if sent in last 7 days, +5 if last 30 days
  - Recurring template: +30
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List

from src.models.database import db, Favorite, RecurringTransfer, TransferHistory
from src.agents.transfer_agent.schemas import RecipientRecommendation


def get_recommendations(user_id: int, limit: int = 5) -> List[RecipientRecommendation]:
    """Return the top *limit* recommended recipients for *user_id*."""
    scores: dict[int, dict] = {}  # favorite_id -> score bundle

    # ── Favorites ────────────────────────────────────────────────────────────
    favs: List[Favorite] = (
        db.session.query(Favorite)
        .filter(Favorite.user_id == user_id)
        .all()
    )
    for f in favs:
        score = 0.0
        reasons = []

        if f.is_favorite:
            score += 50
            reasons.append("즐겨찾기")

        capped_sends = min(f.send_count or 0, 10) * 2
        if capped_sends > 0:
            score += capped_sends
            reasons.append(f"이체 {f.send_count}회")

        if f.last_sent_at:
            delta = datetime.utcnow() - f.last_sent_at
            if delta <= timedelta(days=7):
                score += 10
                reasons.append("최근 7일 이내")
            elif delta <= timedelta(days=30):
                score += 5
                reasons.append("최근 30일 이내")

        scores[f.id] = {
            "favorite": f,
            "score": score,
            "reasons": reasons,
            "suggested_amount": None,
        }

    # ── Recurring templates ──────────────────────────────────────────────────
    recurring: List[RecurringTransfer] = (
        db.session.query(RecurringTransfer)
        .filter(
            RecurringTransfer.user_id == user_id,
            RecurringTransfer.is_active == True,
            RecurringTransfer.favorite_id != None,
        )
        .all()
    )
    for rt in recurring:
        fid = rt.favorite_id
        if fid in scores:
            scores[fid]["score"] += 30
            scores[fid]["reasons"].append(f"자동이체({rt.alias})")
            scores[fid]["suggested_amount"] = rt.default_amount
        # (If the favorite isn't in scores yet, skip — it means it's not a
        #  saved favorite of this user and shouldn't be recommended directly.)

    # ── Sort and build result ────────────────────────────────────────────────
    sorted_entries = sorted(scores.values(), key=lambda x: x["score"], reverse=True)

    results = []
    for rank, entry in enumerate(sorted_entries[:limit], start=1):
        f = entry["favorite"]
        r = f.recipient
        results.append(
            RecipientRecommendation(
                rank=rank,
                alias=f.alias,
                name=r.name,
                bank_name=r.bank_name,
                account_number=r.account_number,
                score=entry["score"],
                reason=", ".join(entry["reasons"]) or "저장된 수신자",
                suggested_amount=entry["suggested_amount"],
            )
        )

    return results
