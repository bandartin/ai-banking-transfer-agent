"""
호칭 학습 메모리 서비스.

사용자가 수신자를 부르는 표현("여친", "여자친구", "내사랑" → 김서연)을
alias_memories 테이블에 영속화한다.

  · 즐겨찾기 별칭으로 못 찾은 호칭은 되묻기(clarification)로 해소하고,
    해소 결과를 learn() 으로 저장 → 다음 세션부터는 즉시 해석된다.
  · 같은 호칭이 다른 사람으로 다시 지정되면 매핑을 갱신한다 (호칭은 변한다).
  · 사용할 때마다 bump() 로 hit_count/last_used_at 을 갱신해 신뢰도를 누적한다.

LangGraph Store 대신 RDB 테이블을 쓰는 이유: 금융 도메인에서는 장기 기억도
감사(audit) 가능한 정형 저장소에 두는 것이 운영/컴플라이언스에 유리하다.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from src.models.database import db, AliasMemory, Favorite, Recipient


def lookup(user_id: int, alias: str) -> Optional[dict]:
    """기억된 호칭으로 수신자를 찾는다. 즐겨찾기 검색 실패 후에 호출된다."""
    if not alias:
        return None

    mem: Optional[AliasMemory] = (
        db.session.query(AliasMemory)
        .filter(
            AliasMemory.user_id == user_id,
            db.func.lower(AliasMemory.alias) == alias.strip().lower(),
        )
        .first()
    )
    if mem is None:
        return None

    recipient = db.session.get(Recipient, mem.recipient_id)
    if recipient is None:
        return None

    # 해당 수신자가 즐겨찾기에도 있으면 favorite_id 를 함께 반환 (통계 갱신용)
    fav = (
        db.session.query(Favorite)
        .filter(Favorite.user_id == user_id, Favorite.recipient_id == recipient.id)
        .first()
    )

    return {
        "type": "alias_memory",
        "alias_memory_id": mem.id,
        "favorite_id": fav.id if fav else None,
        "recipient_id": recipient.id,
        "alias": mem.alias,
        "name": recipient.name,
        "bank_name": recipient.bank_name,
        "account_number": recipient.account_number,
        "hit_count": mem.hit_count,
        "learned": mem.source == "learned",
    }


def learn(user_id: int, alias: str, recipient_id: int, source: str = "learned") -> AliasMemory:
    """호칭→수신자 매핑을 저장(upsert)한다. 기존 매핑과 다르면 갱신한다."""
    alias = alias.strip()
    mem: Optional[AliasMemory] = (
        db.session.query(AliasMemory)
        .filter(
            AliasMemory.user_id == user_id,
            db.func.lower(AliasMemory.alias) == alias.lower(),
        )
        .first()
    )

    now = datetime.utcnow()
    if mem is None:
        mem = AliasMemory(
            user_id=user_id,
            alias=alias,
            recipient_id=recipient_id,
            hit_count=1,
            source=source,
            last_used_at=now,
        )
        db.session.add(mem)
    else:
        if mem.recipient_id != recipient_id:
            # 호칭이 다른 사람을 가리키게 됨 → 매핑 갱신, 신뢰도 리셋
            mem.recipient_id = recipient_id
            mem.hit_count = 1
        else:
            mem.hit_count = (mem.hit_count or 0) + 1
        mem.last_used_at = now
        mem.updated_at = now

    db.session.commit()
    return mem


def bump(user_id: int, alias: str) -> None:
    """기억된 호칭 사용 시 신뢰도(hit_count) 누적."""
    mem = (
        db.session.query(AliasMemory)
        .filter(
            AliasMemory.user_id == user_id,
            db.func.lower(AliasMemory.alias) == alias.strip().lower(),
        )
        .first()
    )
    if mem:
        mem.hit_count = (mem.hit_count or 0) + 1
        mem.last_used_at = datetime.utcnow()
        db.session.commit()


def list_for_user(user_id: int) -> List[dict]:
    """UI(즐겨찾기 페이지)에 노출할 학습된 호칭 목록."""
    rows = (
        db.session.query(AliasMemory)
        .filter(AliasMemory.user_id == user_id)
        .order_by(AliasMemory.hit_count.desc())
        .all()
    )
    out = []
    for m in rows:
        r = db.session.get(Recipient, m.recipient_id)
        out.append({
            "alias": m.alias,
            "recipient_name": r.name if r else "?",
            "bank_name": r.bank_name if r else "?",
            "hit_count": m.hit_count,
            "source": m.source,
            "last_used_at": m.last_used_at.isoformat() if m.last_used_at else None,
        })
    return out
