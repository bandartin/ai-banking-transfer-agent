"""결정론적 한국어 파서 단위 테스트."""

import pytest

from src.agents.common.parsing import (
    classify_intent,
    detect_intents,
    extract_slots,
    is_cancellation,
    is_confirmation,
    parse_amount,
)
from src.agents.common.llm import _cross_check_slots
from src.agents.common.schemas import ExtractedSlots


class TestAmountParser:
    @pytest.mark.parametrize("text,expected", [
        ("5만원", 50_000),
        ("300만원", 3_000_000),
        ("1억", 100_000_000),
        ("150,000원", 150_000),
        ("3000원", 3_000),
        ("만원", 10_000),            # 한글 수사
        ("오만원", 50_000),
        ("삼십만원", 300_000),
        ("백만원", 1_000_000),
        ("5만5천원", 55_000),
    ])
    def test_amounts(self, text, expected):
        assert parse_amount(text) == expected

    def test_no_amount(self):
        assert parse_amount("엄마한테 보내줘") is None


class TestIntent:
    def test_transfer(self):
        assert classify_intent("엄마에게 5만원 보내줘") == "transfer"

    def test_balance(self):
        assert classify_intent("내 잔고 보여줘") == "balance_inquiry"

    def test_multi_intent(self):
        intents = detect_intents("잔고 보여주고 자주 보내는 사람 추천해줘")
        assert "balance_inquiry" in intents
        assert "recommendation" in intents

    def test_transfer_overrides(self):
        intents = detect_intents("월세 보내야 하지?")
        assert "transfer" in intents

    def test_security(self):
        assert classify_intent("내 계좌 보안 점검해줘") == "security_inquiry"

    def test_confirm_cancel(self):
        assert is_confirmation("확인")
        assert is_confirmation("네")
        assert is_cancellation("취소")
        assert not is_confirmation("취소")


class TestSlots:
    def test_basic(self):
        s = extract_slots("엄마에게 5만원 보내줘")
        assert s.recipient_alias == "엄마"
        assert s.amount == 50_000

    def test_girlfriend_alias(self):
        s = extract_slots("여친한테 2만원 보내줘")
        assert s.recipient_alias == "여친"

    def test_memo_natural(self):
        s = extract_slots("지연한테 3만원 보내고 밥값이라고 적어줘")
        assert s.memo == "밥값"

    def test_last_transfer(self):
        s = extract_slots("지난번처럼 보내줘")
        assert s.use_last_transfer is True

    def test_recurring(self):
        s = extract_slots("월세 보내야 하지?")
        assert s.recurring_hint == "월세"

    def test_extended_slot_metadata(self):
        s = extract_slots("비상금통장에서 한빛은행 엄마에게 5만원 보내고 밥값이라고 적어줘")
        assert s.raw_amount_text == "5만원"
        assert s.recipient_alias == "엄마"
        assert s.recipient_text == "엄마"
        assert s.bank_hint == "한빛은행"
        assert s.source_account_hint == "비상금통장"
        assert s.memo == "밥값"
        assert s.extraction_method == "rule"
        assert s.missing_fields == []
        assert s.evidence["amount"] == "5만원"

    def test_missing_fields(self):
        s = extract_slots("엄마한테 보내줘")
        assert "amount" in s.missing_fields

    def test_llm_rule_cross_check_prefers_rule_amount(self):
        llm_slots = ExtractedSlots(recipient_alias="엄마", amount=500_000, extraction_method="llm")
        rule_slots = ExtractedSlots(
            recipient_alias="엄마",
            amount=50_000,
            raw_amount_text="5만원",
            evidence={"amount": "5만원"},
            extraction_method="rule",
        )
        merged = _cross_check_slots(llm_slots, rule_slots)
        assert merged.amount == 50_000
        assert "amount" in merged.ambiguous_fields
        assert merged.evidence["amount_conflict"] == "llm=500000, rule=50000"
        assert merged.extraction_method == "llm+rule_cross_check"
