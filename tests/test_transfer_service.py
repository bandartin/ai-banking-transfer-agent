"""Tests for the deterministic transfer business logic."""

import pytest
from src.agents.transfer_agent.schemas import TransferSummary
from src.agents.transfer_agent.services.transfer_service import (
    calculate_fee,
    validate_transfer,
)
from src.models.database import Account


class TestFeeCalculation:
    def test_same_bank_free(self, app):
        with app.app_context():
            fee = calculate_fee("으뜸은행", "으뜸은행")
            assert fee == 0

    def test_interbank_fee(self, app):
        with app.app_context():
            fee = calculate_fee("으뜸은행", "한빛은행")
            assert fee == 500


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
            summary = self._make_summary(50_000)
            result = validate_transfer(1, summary)
            assert result.passed is True
            assert result.errors == []

    def test_insufficient_balance(self, app, db):
        with app.app_context():
            # Request more than the DB account balance (8,250,000)
            summary = self._make_summary(9_000_000)
            result = validate_transfer(1, summary)
            assert result.passed is False
            assert any("잔액이 부족" in e for e in result.errors)

    def test_single_limit_exceeded(self, app, db):
        with app.app_context():
            summary = self._make_summary(15_000_000, fee=0)  # > 10M limit
            result = validate_transfer(1, summary)
            assert result.passed is False
            assert any("1회 이체 한도" in e for e in result.errors)

    def test_zero_amount(self, app, db):
        with app.app_context():
            summary = self._make_summary(0, fee=0)
            result = validate_transfer(1, summary)
            assert result.passed is False
