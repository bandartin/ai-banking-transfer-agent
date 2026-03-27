"""Tests for the deterministic Korean NLP parser."""

import pytest
from src.agents.transfer_agent.services.llm_service import (
    parse_amount,
    classify_intent_deterministic,
    extract_slots_deterministic,
    is_confirmation,
    is_cancellation,
)


class TestParseAmount:
    def test_만원(self):
        assert parse_amount("5만원") == 50_000

    def test_백만원(self):
        assert parse_amount("300만원") == 3_000_000

    def test_천원(self):
        assert parse_amount("3천원") == 3_000

    def test_억(self):
        assert parse_amount("1억") == 100_000_000

    def test_천만(self):
        assert parse_amount("2천만원") == 20_000_000

    def test_comma(self):
        assert parse_amount("150,000원") == 150_000

    def test_raw_won(self):
        assert parse_amount("50000원") == 50_000

    def test_none(self):
        assert parse_amount("그냥 보내줘") is None


class TestClassifyIntent:
    def test_transfer(self):
        assert classify_intent_deterministic("엄마에게 5만원 보내줘") == "transfer"

    def test_balance(self):
        assert classify_intent_deterministic("내 잔고 보여줘") == "balance_inquiry"

    def test_history(self):
        assert classify_intent_deterministic("최근 이체내역 보여줘") == "history_inquiry"

    def test_recommendation(self):
        assert classify_intent_deterministic("자주 보내는 사람 추천해줘") == "recommendation"

    def test_unknown(self):
        assert classify_intent_deterministic("오늘 날씨가 어때요?") == "unknown"


class TestExtractSlots:
    def test_alias_and_amount(self):
        slots = extract_slots_deterministic("엄마에게 5만원 보내줘")
        assert slots.recipient_alias == "엄마"
        assert slots.amount == 50_000

    def test_recurring_hint_wolse(self):
        slots = extract_slots_deterministic("월세 보내야 하지?")
        assert slots.recurring_hint == "월세"

    def test_last_transfer(self):
        slots = extract_slots_deterministic("지난번처럼 보내줘")
        assert slots.use_last_transfer is True

    def test_large_amount(self):
        slots = extract_slots_deterministic("300만원 송금해줘")
        assert slots.amount == 3_000_000

    def test_hante_pattern(self):
        slots = extract_slots_deterministic("민수한테 10만원 보내줘")
        assert slots.recipient_alias == "민수"
        assert slots.amount == 100_000


class TestConfirmation:
    def test_is_confirm(self):
        assert is_confirmation("확인") is True
        assert is_confirmation("보내") is True
        assert is_confirmation("예") is True

    def test_is_cancel(self):
        assert is_cancellation("취소") is True
        assert is_cancellation("아니오") is True

    def test_not_confirm(self):
        assert is_confirmation("5만원 보내줘") is False
