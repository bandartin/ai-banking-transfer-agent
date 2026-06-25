"""Deterministic transfer business logic (Flask-free).

LLM is never allowed to decide balances, limits, fees, authentication, or
execution.  This module assembles deterministic transfer summaries and delegates
authoritative validation/execution to the configured integration adapter.

Default local behavior is unchanged because `MockBankingAdapter` still uses the
current SQLAlchemy demo schema.  In an IBK deployment the adapter can be swapped
for API/MCI/ESB calls without rewriting the LangGraph workflow.
"""

from __future__ import annotations

from typing import Optional

from src.agents.context import BankingContext
from src.agents.common.schemas import TransferResult, TransferSummary, ValidationResult
from src.agents.common.services.balance_service import (
    find_account_by_hint,
    get_all_accounts,
    get_primary_account,
)
from src.integrations import get_banking_adapter
from src.integrations.dtos import TransferExecutionRequest
from src.models.database import Account, db


# ─────────────────────────────────────────────────────────────────────────────
# Fee calculation
# ─────────────────────────────────────────────────────────────────────────────


def calculate_fee(ctx: BankingContext, source_bank: str, destination_bank: str) -> int:
    """Same-bank transfers are free; all other transfers cost ctx.interbank_fee."""
    if source_bank == destination_bank:
        return 0
    return ctx.interbank_fee


# ─────────────────────────────────────────────────────────────────────────────
# Build transfer summary
# ─────────────────────────────────────────────────────────────────────────────


def build_transfer_summary(
    ctx: BankingContext,
    user_id: int,
    recipient_data: dict,
    amount: int,
    memo: Optional[str] = None,
    source_account_id: Optional[int] = None,
) -> Optional[TransferSummary]:
    """Assemble a `TransferSummary` from resolved deterministic data.

    In production the account row returned by the adapter should represent an
    authoritative observation from IBK's account inquiry system.  This function
    only formats that observation into the shape needed by the confirmation
    card and downstream validation.
    """
    if source_account_id:
        source_account = db.session.get(Account, source_account_id)
        if source_account and (source_account.user_id != user_id or not source_account.is_active):
            source_account = None
    else:
        source_account = get_primary_account(user_id)
    if not source_account:
        return None

    fee = calculate_fee(ctx, source_account.bank_name, recipient_data["bank_name"])
    total = amount + fee

    return TransferSummary(
        source_account_id=source_account.id,
        source_account_name=source_account.account_name,
        source_account_number=source_account.account_number,
        current_balance=source_account.balance,
        recipient_name=recipient_data["name"],
        recipient_bank=recipient_data["bank_name"],
        recipient_account=recipient_data["account_number"],
        recipient_alias=recipient_data.get("alias"),
        amount=amount,
        fee=fee,
        total_deducted=total,
        remaining_balance=source_account.balance - total,
        memo=memo,
        requires_otp=amount >= ctx.otp_threshold,
        warnings=[],
    )


def resolve_source_account(user_id: int, hint: Optional[str]) -> tuple[Optional[int], Optional[str]]:
    """Resolve a source account hint to an account id.

    The return contract intentionally stays `(account_id, error_message)` so the
    existing TransferAgent can continue to decide whether to continue or show a
    user-facing error.
    """
    if not hint:
        return None, None

    account = find_account_by_hint(user_id, hint)
    if account:
        return account.id, None

    available = ", ".join(f"{a.account_name}({a.account_type})" for a in get_all_accounts(user_id))
    return None, f"'{hint}'에 해당하는 출금 계좌를 찾지 못했습니다. 사용 가능한 계좌: {available}"


# ─────────────────────────────────────────────────────────────────────────────
# Pre-validation and execution
# ─────────────────────────────────────────────────────────────────────────────


def validate_transfer(user_id: int, summary: TransferSummary) -> ValidationResult:
    """Run all pre-transfer checks through the configured banking adapter."""
    return get_banking_adapter().validate_transfer(user_id, summary)


def execute_transfer(
    user_id: int,
    summary: TransferSummary,
    favorite_id: Optional[int] = None,
    execution_request: TransferExecutionRequest | None = None,
) -> TransferResult:
    """Execute or dry-run the transfer through the configured banking adapter."""
    return get_banking_adapter().execute_transfer(
        user_id,
        summary,
        favorite_id=favorite_id,
        execution_request=execution_request,
    )


def _fmt(amount: int) -> str:
    return f"{amount:,}"
