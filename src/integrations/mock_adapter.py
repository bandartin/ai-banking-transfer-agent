"""Mock adapters backed by the current SQLAlchemy demo schema.

This module preserves today's behavior while providing the same boundary that a
future IBK API adapter will implement.  In other words, it is not "just mock
code"; it is the compatibility layer that lets us refactor safely before the
real interfaces are available.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Optional

from src.agents.common.schemas import (
    RecipientRecommendation,
    TransferResult,
    TransferSummary,
    ValidationResult,
)
from src.models.database import (
    Account,
    AuditLog,
    Favorite,
    Recipient,
    RecurringTransfer,
    TransferEvent,
    TransferHistory,
    TransferLimit,
    TransferRequest,
    db,
)
from .dtos import KnowledgeChunk, KnowledgeSearchResult, TransferExecutionRequest, TransferLimitSnapshot
from .knowledge_guard import assess_knowledge_query


class MockBankingAdapter:
    source_name = "mock-sqlalchemy"

    def __init__(self, execution_mode: str = "mock") -> None:
        self.execution_mode = execution_mode

    # ── Account / balance ──────────────────────────────────────────────────

    def get_primary_account(self, user_id: int) -> Optional[Account]:
        return (
            db.session.query(Account)
            .filter(Account.user_id == user_id, Account.is_primary == True, Account.is_active == True)
            .first()
        )

    def get_all_accounts(self, user_id: int) -> list[Account]:
        return (
            db.session.query(Account)
            .filter(Account.user_id == user_id, Account.is_active == True)
            .all()
        )

    def find_account_by_hint(self, user_id: int, hint: str) -> Optional[Account]:
        if not hint:
            return None
        hint_lower = hint.strip().lower()
        for account in self.get_all_accounts(user_id):
            fields = [
                account.account_name,
                account.account_type,
                account.account_number,
                account.account_number.replace("-", "") if account.account_number else "",
            ]
            if any(hint_lower in (field or "").lower() for field in fields):
                return account
        return None

    def get_transfer_limit(self, user_id: int) -> Optional[TransferLimit]:
        tl = db.session.query(TransferLimit).filter(TransferLimit.user_id == user_id).first()
        if tl:
            self.maybe_reset_daily(tl)
        return tl

    def get_transfer_limit_snapshot(self, user_id: int) -> TransferLimitSnapshot | None:
        tl = self.get_transfer_limit(user_id)
        if not tl:
            return None
        return TransferLimitSnapshot(
            single_transfer_limit=tl.single_transfer_limit,
            daily_limit=tl.daily_limit,
            daily_used=tl.daily_used,
            source=self.source_name,
        )

    def maybe_reset_daily(self, tl: TransferLimit) -> None:
        today = date.today()
        if tl.last_reset_date != today:
            tl.daily_used = 0
            tl.last_reset_date = today
            db.session.add(tl)
            db.session.flush()

    def get_balance_summary(self, user_id: int) -> dict[str, Any]:
        accounts = self.get_all_accounts(user_id)
        tl = self.get_transfer_limit(user_id)

        daily_limit = tl.daily_limit if tl else 0
        daily_used = tl.daily_used if tl else 0
        single_limit = tl.single_transfer_limit if tl else 0

        return {
            "accounts": [
                {
                    "id": a.id,
                    "name": a.account_name,
                    "number": a.account_number,
                    "bank": a.bank_name,
                    "type": a.account_type,
                    "balance": a.balance,
                    "is_primary": a.is_primary,
                    "observed_at": datetime.utcnow().isoformat(),
                    "source": self.source_name,
                }
                for a in accounts
            ],
            "daily_limit": daily_limit,
            "daily_used": daily_used,
            "daily_remaining": max(0, daily_limit - daily_used),
            "single_transfer_limit": single_limit,
            "observed_at": datetime.utcnow().isoformat(),
            "source": self.source_name,
        }

    # ── Recipient resolution ────────────────────────────────────────────────

    def find_recipients_by_alias(self, user_id: int, alias: str) -> list[dict[str, Any]]:
        if not alias:
            return []

        alias_lower = alias.strip().lower()
        exact = (
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
            return [self._fav_to_dict(f) for f in exact]

        partial = (
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
        return [self._fav_to_dict(f) for f in partial]

    def find_recurring_transfer(self, user_id: int, hint: str) -> dict[str, Any] | None:
        if not hint:
            return None
        hint_lower = hint.strip().lower()
        rt = (
            db.session.query(RecurringTransfer)
            .filter(
                RecurringTransfer.user_id == user_id,
                RecurringTransfer.is_active == True,
                db.func.lower(RecurringTransfer.alias).contains(hint_lower),
            )
            .first()
        )
        return self._recurring_to_dict(rt) if rt else None

    def find_last_transfer(self, user_id: int) -> dict[str, Any] | None:
        th = (
            db.session.query(TransferHistory)
            .filter(TransferHistory.user_id == user_id, TransferHistory.status == "completed")
            .order_by(TransferHistory.transferred_at.desc())
            .first()
        )
        return self._history_to_dict(th) if th else None

    def get_top_recipients(self, user_id: int, limit: int = 5) -> list[dict[str, Any]]:
        favs = (
            db.session.query(Favorite)
            .filter(Favorite.user_id == user_id)
            .order_by(Favorite.send_count.desc(), Favorite.last_sent_at.desc())
            .limit(limit)
            .all()
        )
        return [self._fav_to_dict(f) for f in favs]

    # ── Recommendation ──────────────────────────────────────────────────────

    def get_recommendations(self, user_id: int, limit: int = 5) -> list[RecipientRecommendation]:
        scores: dict[int, dict[str, Any]] = {}
        favs = db.session.query(Favorite).filter(Favorite.user_id == user_id).all()
        for f in favs:
            score = 0.0
            reasons: list[str] = []
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

            scores[f.id] = {"favorite": f, "score": score, "reasons": reasons, "suggested_amount": None}

        recurring = (
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

        sorted_entries = sorted(scores.values(), key=lambda x: x["score"], reverse=True)
        results = []
        for rank, entry in enumerate(sorted_entries[:limit], start=1):
            f = entry["favorite"]
            r = f.recipient
            results.append(
                RecipientRecommendation(
                    rank=rank,
                    favorite_id=f.id,
                    recipient_id=r.id,
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

    # ── Transfer validation/execution ───────────────────────────────────────

    def validate_transfer(self, user_id: int, summary: TransferSummary) -> ValidationResult:
        errors: list[str] = []
        warnings: list[str] = []

        account = db.session.get(Account, summary.source_account_id)
        if not account or not account.is_active:
            return ValidationResult(passed=False, errors=["출금 계좌가 비활성 상태입니다."])

        if account.balance < summary.total_deducted:
            shortage = summary.total_deducted - account.balance
            errors.append(
                f"잔액이 부족합니다. "
                f"필요 금액: {self._fmt(summary.total_deducted)}원, "
                f"현재 잔액: {self._fmt(account.balance)}원 "
                f"(부족액: {self._fmt(shortage)}원)"
            )

        tl = self.get_transfer_limit(user_id)
        if tl and summary.amount > tl.single_transfer_limit:
            errors.append(
                f"1회 이체 한도를 초과했습니다. "
                f"요청: {self._fmt(summary.amount)}원, "
                f"한도: {self._fmt(tl.single_transfer_limit)}원"
            )

        if tl:
            remaining = tl.daily_limit - tl.daily_used
            if summary.amount > remaining:
                errors.append(
                    f"일일 이체 한도를 초과했습니다. "
                    f"오늘 남은 한도: {self._fmt(remaining)}원, "
                    f"요청: {self._fmt(summary.amount)}원"
                )

        if summary.amount <= 0:
            errors.append("이체 금액은 0원보다 커야 합니다.")

        if summary.remaining_balance < 10_000:
            warnings.append("이체 후 잔액이 1만원 미만입니다.")

        return ValidationResult(passed=len(errors) == 0, errors=errors, warnings=warnings)

    def execute_transfer(
        self,
        user_id: int,
        summary: TransferSummary,
        favorite_id: int | None = None,
        execution_request: TransferExecutionRequest | None = None,
    ) -> TransferResult:
        if self.execution_mode == "dry_run":
            return TransferResult(
                success=True,
                transfer_id=None,
                new_balance=summary.current_balance,
                error_message=None,
            )

        try:
            account = db.session.get(Account, summary.source_account_id)
            if not account:
                return TransferResult(success=False, error_message="출금 계좌를 찾을 수 없습니다.")

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

            request_row = self._ensure_transfer_request(user_id, summary, recipient, favorite_id, execution_request)
            if request_row.status == "executed" and request_row.transfer_history_id:
                # Idempotent replay: return the previous successful result
                # instead of creating a second ledger entry.
                db.session.refresh(account)
                return TransferResult(
                    success=True,
                    transfer_id=request_row.transfer_history_id,
                    new_balance=account.balance,
                )

            self._add_transfer_event(request_row, "executing", {"adapter": self.source_name})

            account.balance -= summary.total_deducted
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

            tl = self.get_transfer_limit(user_id)
            if tl:
                self.maybe_reset_daily(tl)
                tl.daily_used += summary.amount

            if favorite_id:
                fav = db.session.get(Favorite, favorite_id)
                if fav:
                    fav.send_count = (fav.send_count or 0) + 1
                    fav.last_sent_at = datetime.utcnow()

            audit = AuditLog(
                user_id=user_id,
                action="transfer_executed",
                entity_type="transfer_history",
                details_json=json.dumps(
                    {"summary": summary.model_dump(), "favorite_id": favorite_id, "adapter": self.source_name},
                    ensure_ascii=False,
                    default=str,
                ),
            )
            db.session.add(audit)
            db.session.flush()

            request_row.status = "executed"
            request_row.transfer_history_id = th.id
            request_row.external_reference_id = f"mock-{th.id}"
            request_row.executed_at = datetime.utcnow()
            self._add_transfer_event(request_row, "executed", {"transfer_history_id": th.id})

            db.session.commit()
            db.session.refresh(account)
            return TransferResult(success=True, transfer_id=th.id, new_balance=account.balance)
        except Exception as exc:
            db.session.rollback()
            return TransferResult(success=False, error_message=f"이체 처리 중 오류가 발생했습니다: {exc}")

    def _ensure_transfer_request(
        self,
        user_id: int,
        summary: TransferSummary,
        recipient: Recipient,
        favorite_id: int | None,
        execution_request: TransferExecutionRequest | None,
    ) -> TransferRequest:
        idempotency_key = execution_request.idempotency_key if execution_request else ""
        if idempotency_key:
            existing = (
                db.session.query(TransferRequest)
                .filter(TransferRequest.idempotency_key == idempotency_key)
                .first()
            )
            if existing:
                return existing

        row = TransferRequest(
            user_id=user_id,
            session_id=execution_request.session_id if execution_request else "",
            idempotency_key=idempotency_key or f"mock-{user_id}-{datetime.utcnow().timestamp()}",
            status="confirmed",
            execution_mode=self.execution_mode,
            source_account_id=summary.source_account_id,
            recipient_id=recipient.id,
            favorite_id=favorite_id,
            amount=summary.amount,
            fee=summary.fee,
            total_deducted=summary.total_deducted,
            confirmation_snapshot_json=json.dumps(summary.model_dump(), ensure_ascii=False, default=str),
            confirmed_at=datetime.utcnow(),
        )
        db.session.add(row)
        db.session.flush()
        self._add_transfer_event(row, "confirmed", {"source": self.source_name})
        return row

    def _add_transfer_event(self, request_row: TransferRequest, event_type: str, payload: dict[str, Any]) -> None:
        db.session.add(
            TransferEvent(
                transfer_request_id=request_row.id,
                user_id=request_row.user_id,
                event_type=event_type,
                payload_json=json.dumps(payload, ensure_ascii=False, default=str),
            )
        )

    # ── Shape helpers ───────────────────────────────────────────────────────

    def _fav_to_dict(self, f: Favorite) -> dict[str, Any]:
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

    def _recurring_to_dict(self, rt: RecurringTransfer) -> dict[str, Any]:
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

    def _history_to_dict(self, th: TransferHistory) -> dict[str, Any]:
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

    @staticmethod
    def _fmt(amount: int) -> str:
        return f"{amount:,}"


class MockKnowledgeAdapter:
    """Small local knowledge base used until AWX collections are connected."""

    source_name = "mock-knowledge"

    _DOCS = [
        KnowledgeChunk(
            chunk_id="menu-transfer-001",
            title="이체 메뉴",
            content="모바일뱅킹 앱의 이체 메뉴는 홈 하단 '이체' 탭 또는 전체메뉴 > 이체/출금 > 계좌이체에서 찾을 수 있습니다.",
            score=0.92,
            collection="menu_catalog",
            source_uri="mock://menu/transfer",
            document_version="2026.06",
            updated_at="2026-06-22",
            metadata={"menu_path": "전체메뉴 > 이체/출금 > 계좌이체"},
        ),
        KnowledgeChunk(
            chunk_id="menu-limit-001",
            title="이체한도 조회 메뉴",
            content="이체한도 조회와 변경은 전체메뉴 > 보안/인증 > 이체한도 관리에서 확인합니다.",
            score=0.89,
            collection="menu_catalog",
            source_uri="mock://menu/limit",
            document_version="2026.06",
            updated_at="2026-06-22",
            metadata={"menu_path": "전체메뉴 > 보안/인증 > 이체한도 관리"},
        ),
        KnowledgeChunk(
            chunk_id="product-deposit-001",
            title="정기예금 안내",
            content="정기예금은 일정 기간 목돈을 맡기고 약정 금리에 따라 이자를 받는 예금 상품입니다. 중도해지 시 약정 금리보다 낮은 금리가 적용될 수 있습니다.",
            score=0.86,
            collection="product_docs",
            source_uri="mock://product/deposit",
            document_version="2026.06",
            updated_at="2026-06-22",
            metadata={"product_type": "deposit"},
        ),
        KnowledgeChunk(
            chunk_id="fee-transfer-001",
            title="타행 이체 수수료 안내",
            content="타행 이체 수수료는 고객 등급, 채널, 상품 조건에 따라 면제 또는 감면될 수 있습니다. 실제 수수료는 이체 확인 단계의 시스템 계산값을 기준으로 합니다.",
            score=0.84,
            collection="fee_policy_docs",
            source_uri="mock://fee/transfer",
            document_version="2026.06",
            updated_at="2026-06-22",
            metadata={"policy_scope": "transfer_fee"},
        ),
    ]

    def retrieve(
        self,
        query: str,
        *,
        collection: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> KnowledgeSearchResult:
        guard = assess_knowledge_query(query, collection=collection)
        if not guard.allowed:
            return KnowledgeSearchResult(
                query=query,
                collection=collection,
                chunks=[],
                source=self.source_name,
                threshold_met=False,
                error_message=guard.reason,
            )

        query_l = (query or "").lower()
        candidates = [d for d in self._DOCS if collection == "all" or d.collection == collection]
        scored = []
        for doc in candidates:
            haystack = f"{doc.title} {doc.content} {' '.join(str(v) for v in doc.metadata.values())}".lower()
            score = doc.score
            if query_l and any(token and token in haystack for token in query_l.split()):
                score = min(0.99, score + 0.05)
            if query_l and query_l in haystack:
                score = min(0.99, score + 0.08)
            scored.append((score, doc))
        scored.sort(key=lambda item: item[0], reverse=True)
        chunks = [
            KnowledgeChunk(**{**doc.__dict__, "score": score})
            for score, doc in scored[:top_k]
        ]
        threshold_met = bool(chunks and chunks[0].score >= 0.7)
        return KnowledgeSearchResult(
            query=query,
            collection=collection,
            chunks=chunks if threshold_met else [],
            source=self.source_name,
            threshold_met=threshold_met,
            raw_count=len(scored),
        )
