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
