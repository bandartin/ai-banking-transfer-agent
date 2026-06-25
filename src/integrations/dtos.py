"""Typed data transfer objects for external banking integrations.

These DTOs are intentionally plain dataclasses.  They describe the contract we
want from IBK/AWX-facing adapters without binding the rest of the code to a
specific API payload shape, SQLAlchemy row, or SDK object.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Optional


ExecutionMode = Literal["mock", "dry_run", "live"]


@dataclass(frozen=True)
class ExternalCallMeta:
    """Non-sensitive metadata about a call to a system outside the agent."""

    system: str
    operation: str
    request_id: str = ""
    status_code: str = ""
    latency_ms: int = 0
    error_code: str = ""
    error_message: str = ""


@dataclass(frozen=True)
class AccountSnapshot:
    """Authoritative account state as observed at a point in time."""

    account_id: int | str
    account_number: str
    account_name: str
    bank_name: str
    account_type: str
    balance: int
    is_primary: bool = False
    is_active: bool = True
    observed_at: datetime = field(default_factory=datetime.utcnow)
    source: str = "mock"


@dataclass(frozen=True)
class TransferLimitSnapshot:
    """Transfer limits returned by a policy or account inquiry system."""

    single_transfer_limit: int
    daily_limit: int
    daily_used: int
    observed_at: datetime = field(default_factory=datetime.utcnow)
    source: str = "mock"

    @property
    def daily_remaining(self) -> int:
        return max(0, self.daily_limit - self.daily_used)


@dataclass(frozen=True)
class RecipientSnapshot:
    """A transfer recipient candidate."""

    recipient_id: int | str
    name: str
    bank_name: str
    account_number: str
    favorite_id: int | str | None = None
    alias: str | None = None
    send_count: int = 0
    last_sent_at: str | None = None
    is_favorite: bool = True
    source: str = "mock"

    def as_legacy_dict(self) -> dict[str, Any]:
        """Return the dict shape currently expected by TransferAgent."""
        return {
            "type": self.source,
            "favorite_id": self.favorite_id,
            "recipient_id": self.recipient_id,
            "alias": self.alias,
            "name": self.name,
            "bank_name": self.bank_name,
            "account_number": self.account_number,
            "send_count": self.send_count,
            "last_sent_at": self.last_sent_at,
            "is_favorite": self.is_favorite,
        }


@dataclass(frozen=True)
class TransferExecutionRequest:
    """Request sent to the eventual transfer execution adapter."""

    user_id: int
    session_id: str
    idempotency_key: str
    source_account_id: int | str
    recipient_id: int | str | None
    amount: int
    fee: int
    memo: str | None = None
    confirmation_snapshot: dict[str, Any] = field(default_factory=dict)
    mode: ExecutionMode = "mock"


@dataclass(frozen=True)
class TransferExecutionOutcome:
    """Normalized result from a transfer execution backend."""

    success: bool
    transfer_id: int | str | None = None
    external_reference_id: str = ""
    new_balance: int | None = None
    status: str = "completed"
    error_code: str = ""
    error_message: str = ""


@dataclass(frozen=True)
class KnowledgeChunk:
    """A retrieved piece of knowledge with source metadata."""

    chunk_id: str
    title: str
    content: str
    score: float
    collection: str
    source_uri: str = ""
    document_version: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeSearchResult:
    """Retrieval output returned to knowledge-oriented agents."""

    query: str
    collection: str
    chunks: list[KnowledgeChunk]
    answer_hint: str = ""
    source: str = "mock"
    threshold_met: bool = True
    error_message: str = ""
    raw_count: int = 0
