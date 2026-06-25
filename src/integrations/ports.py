"""Protocols that define the banking and knowledge integration boundary."""

from __future__ import annotations

from typing import Any, Protocol

from src.agents.common.schemas import (
    RecipientRecommendation,
    TransferResult,
    TransferSummary,
    ValidationResult,
)
from .dtos import (
    KnowledgeSearchResult,
    TransferExecutionRequest,
    TransferLimitSnapshot,
)


class BankingIntegrationPort(Protocol):
    """Port used by agents for customer/account/transfer operations.

    The real IBK implementation can call APIs, DB views, MCI/ESB services, or a
    dry-run sandbox.  The current implementation uses the demo SQLite schema.
    Keeping the method names close to existing service functions lets us move
    incrementally without rewriting the LangGraph workflows.
    """

    source_name: str

    def get_primary_account(self, user_id: int) -> Any | None: ...
    def get_all_accounts(self, user_id: int) -> list[Any]: ...
    def find_account_by_hint(self, user_id: int, hint: str) -> Any | None: ...
    def get_transfer_limit(self, user_id: int) -> Any | None: ...
    def get_transfer_limit_snapshot(self, user_id: int) -> TransferLimitSnapshot | None: ...
    def get_balance_summary(self, user_id: int) -> dict[str, Any]: ...

    def find_recipients_by_alias(self, user_id: int, alias: str) -> list[dict[str, Any]]: ...
    def find_recurring_transfer(self, user_id: int, hint: str) -> dict[str, Any] | None: ...
    def find_last_transfer(self, user_id: int) -> dict[str, Any] | None: ...
    def get_top_recipients(self, user_id: int, limit: int = 5) -> list[dict[str, Any]]: ...
    def get_recommendations(self, user_id: int, limit: int = 5) -> list[RecipientRecommendation]: ...

    def validate_transfer(self, user_id: int, summary: TransferSummary) -> ValidationResult: ...
    def execute_transfer(
        self,
        user_id: int,
        summary: TransferSummary,
        favorite_id: int | None = None,
        execution_request: TransferExecutionRequest | None = None,
    ) -> TransferResult: ...


class KnowledgeSearchPort(Protocol):
    """Port used by RAG-style agents.

    Customer/account values must not be routed through this port.  It is for
    menu, FAQ, product, fee, and operation-manual knowledge only.
    """

    source_name: str

    def retrieve(
        self,
        query: str,
        *,
        collection: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> KnowledgeSearchResult: ...

