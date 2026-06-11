"""Tests for the deterministic transfer business logic."""

import pytest
from src.agents.context import BankingContext
from src.agents.common.schemas import TransferSummary
from src.agents.common.services.transfer_service import (
    calculate_fee,
    validate_transfer,
)


def _ctx() -> BankingContext:
    return BankingContext(user_id=1, session_id="t", interbank_fee=500)


class TestFeeCalculation:
    def test_same_bank_free(self, app):
        assert calculate_fee(_ctx(), "으뜸은행", "으뜸은행") == 0

    def test_interbank_fee(self, app):
        assert calculate_fee(_ctx(), "으뜸은행", "한빛은행") == 500


class TestValidation:
    """Validation tests use in-memory DB seeded by conftest."""

    def _make_summary(self, amount: int, fee: int = 500, balance: int = 8_250_000) -> TransferSummary:
        return TransferSummary(
            source_account_id=1,
            source_account_name="주계좌",
            source_account_number="024-01-0123456",
            current_balance=balance,
            recipient_name="이순자",
            recipient_bank="한빛은행",
            recipient_account="1002-123-456789",
            recipient_alias="엄마",
            amount=amount,
            fee=fee,
            total_deducted=amount + fee,
            remaining_balance=balance - amount - fee,
        )

    def test_valid_small_transfer(self, app, db):
        with app.app_context():
            result = validate_transfer(1, self._make_summary(50_000))
            assert result.passed is True
            assert result.errors == []

    def test_insufficient_balance(self, app, db):
        with app.app_context():
            result = validate_transfer(1, self._make_summary(9_000_000))
            assert result.passed is False
            assert any("잔액이 부족" in e for e in result.errors)

    def test_single_limit_exceeded(self, app, db):
        with app.app_context():
            result = validate_transfer(1, self._make_summary(15_000_000, fee=0))
            assert result.passed is False
            assert any("1회 이체 한도" in e for e in result.errors)

    def test_zero_amount(self, app, db):
        with app.app_context():
            result = validate_transfer(1, self._make_summary(0, fee=0))
            assert result.passed is False
