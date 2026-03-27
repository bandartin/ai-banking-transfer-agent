"""
LLM provider abstraction layer.

Default mode: deterministic (no API key required).
Optional: set LLM_PROVIDER=openai or LLM_PROVIDER=anthropic in .env.

The LLM is used ONLY for intent classification and slot extraction.
All validation and execution remain in deterministic Python code.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from flask import current_app

from src.agents.transfer_agent.schemas import ExtractedSlots


# ─────────────────────────────────────────────────────────────────────────────
# Korean amount parser (deterministic)
# ─────────────────────────────────────────────────────────────────────────────

_AMOUNT_PATTERNS = [
    # "300만원", "5만원", "1억", "1억5천", "2천500만원" …
    (r"(\d+(?:\.\d+)?)억\s*(\d+)?천?만?\s*원?", "억"),
    (r"(\d+(?:\.\d+)?)천만\s*원?", "천만"),
    (r"(\d+(?:\.\d+)?)백만\s*원?", "백만"),
    (r"(\d+(?:\.\d+)?)만\s*원?", "만"),
    (r"(\d+(?:\.\d+)?)천\s*원?", "천"),
    (r"(\d{1,3}(?:,\d{3})+)\s*원?", "comma"),
    (r"(\d+)\s*원", "raw"),
]


def parse_amount(text: str) -> Optional[int]:
    """Parse a Korean amount expression into an integer KRW value."""
    text = text.replace(" ", "")

    # 억 + 천만 compound: e.g. "1억5천만원"
    m = re.search(r"(\d+)억\s*(\d+)천만", text)
    if m:
        return int(m.group(1)) * 100_000_000 + int(m.group(2)) * 10_000_000

    m = re.search(r"(\d+)억\s*(\d+)천", text)
    if m:
        return int(m.group(1)) * 100_000_000 + int(m.group(2)) * 1_000

    m = re.search(r"(\d+(?:\.\d+)?)억", text)
    if m:
        return int(float(m.group(1)) * 100_000_000)

    m = re.search(r"(\d+(?:\.\d+)?)천만", text)
    if m:
        return int(float(m.group(1)) * 10_000_000)

    m = re.search(r"(\d+(?:\.\d+)?)백만", text)
    if m:
        return int(float(m.group(1)) * 1_000_000)

    m = re.search(r"(\d+(?:\.\d+)?)만", text)
    if m:
        return int(float(m.group(1)) * 10_000)

    m = re.search(r"(\d+(?:\.\d+)?)천", text)
    if m:
        return int(float(m.group(1)) * 1_000)

    # Comma-separated: "150,000원"
    m = re.search(r"(\d{1,3}(?:,\d{3})+)", text)
    if m:
        return int(m.group(1).replace(",", ""))

    m = re.search(r"(\d+)원", text)
    if m:
        return int(m.group(1))

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Korean intent classifier (deterministic)
# ─────────────────────────────────────────────────────────────────────────────

# Ordered list — specific intents are checked BEFORE the general transfer intent.
# Each entry is (intent_name, [patterns]).
_INTENT_RULES_ORDERED = [
    ("balance_inquiry", [
        r"잔고", r"잔액", r"얼마.*있", r"통장.*잔", r"balance",
        r"얼마까지.*이체", r"오늘.*한도",
    ]),
    ("history_inquiry", [
        r"이체내역", r"거래내역", r"내역.*보여", r"최근.*이체",
        r"이체.*목록", r"보낸.*기록",
    ]),
    ("recommendation", [
        r"추천", r"자주.*보내", r"주로.*보내", r"누구한테.*보내",
    ]),
    ("recurring_inquiry", [
        r"자동이체", r"정기이체", r"자동.*확인", r"정기.*확인",
    ]),
    # transfer is checked last to avoid matching "보내" inside recommendation phrases
    ("transfer", [
        r"보내줘", r"보내주세요", r"송금", r"계좌이체", r"입금해줘",
        r"[가-힣]+(?:에게|한테|께).*(?:보내|이체|송금)",
        r"(?:보내|이체|송금).*[가-힣]+(?:에게|한테|께)",
        r"(?:\d+|[가-힣]+)원.*(?:보내|이체|송금)",
        r"(?:보내|이체|송금).*(?:\d+|[가-힣]+)원",
    ]),
]


def classify_intent_deterministic(text: str) -> str:
    """Rule-based Korean intent classifier. Returns intent string."""
    for intent, patterns in _INTENT_RULES_ORDERED:
        for p in patterns:
            if re.search(p, text):
                return intent

    # Broad fallback for transfer: any isolated 보내/이체/송금 verb
    if re.search(r"보내|이체|송금", text):
        return "transfer"

    return "unknown"


def is_confirmation(text: str) -> bool:
    text = text.strip()
    return bool(re.search(r"^(확인|보내|전송|실행|예|응|ㅇ|맞아|ok|yes|보낼게|맞아요|맞습니다|보내줘|보내주세요)$", text, re.I))


def is_cancellation(text: str) -> bool:
    text = text.strip()
    return bool(re.search(r"^(취소|아니|아니오|아니요|싫어|no|그만|중지|stop)$", text, re.I))


# ─────────────────────────────────────────────────────────────────────────────
# Korean slot extractor (deterministic)
# ─────────────────────────────────────────────────────────────────────────────

_RECIPIENT_PATTERNS = [
    r"([가-힣a-zA-Z0-9]+?)(?:에게|한테|께|에게로|한테로)\s",
    r"([가-힣a-zA-Z0-9]+?)(?:한테|에게)\s?(?:보내|송금|이체)",
]

_RECURRING_KEYWORDS = {
    "월세": ["월세"],
    "관리비": ["관리비"],
    "용돈": ["용돈"],
    "적금": ["적금"],
    "보험료": ["보험료", "보험"],
    "공과금": ["공과금", "전기세", "수도세", "가스비"],
    "통신비": ["통신비", "핸드폰비", "휴대폰비"],
}

_LAST_TRANSFER_PATTERNS = [r"지난번처럼", r"저번처럼", r"지난번과.*같이", r"똑같이", r"이전처럼"]


def extract_slots_deterministic(text: str) -> ExtractedSlots:
    """Deterministic slot extraction from Korean text."""
    # Amount
    amount = parse_amount(text)

    # Recipient alias
    alias = None
    for pattern in _RECIPIENT_PATTERNS:
        m = re.search(pattern, text + " ")  # trailing space for lookahead
        if m:
            alias = m.group(1).strip()
            break

    # If no pattern matched, try "X 보내줘" style
    if not alias:
        m = re.search(r"([가-힣]+)\s*(?:한테|에게)?.*?(?:보내|송금|이체)", text)
        if m:
            candidate = m.group(1).strip()
            # Exclude common non-alias words
            excluded = {"지난번", "저번", "이전", "최근", "돈", "돈을", "얼마"}
            if candidate not in excluded:
                alias = candidate

    # Memo: "메모: X" or "메모 X"
    memo = None
    m = re.search(r"메모\s*[:\s]\s*([^\s]+)", text)
    if m:
        memo = m.group(1)

    # Use last transfer
    use_last = any(re.search(p, text) for p in _LAST_TRANSFER_PATTERNS)

    # Recurring hint
    recurring_hint = None
    for key, kws in _RECURRING_KEYWORDS.items():
        for kw in kws:
            if kw in text:
                recurring_hint = key
                break
        if recurring_hint:
            break

    return ExtractedSlots(
        recipient_alias=alias,
        amount=amount,
        memo=memo,
        use_last_transfer=use_last,
        recurring_hint=recurring_hint,
    )


# ─────────────────────────────────────────────────────────────────────────────
# LLM-backed variants (optional, used when provider != "deterministic")
# ─────────────────────────────────────────────────────────────────────────────


def classify_intent_llm(text: str) -> str:
    """Use the configured LLM to classify intent.  Falls back to deterministic."""
    provider = current_app.config.get("LLM_PROVIDER", "deterministic")

    try:
        if provider == "openai":
            return _classify_openai(text)
        elif provider == "anthropic":
            return _classify_anthropic(text)
    except Exception:
        pass

    return classify_intent_deterministic(text)


def extract_slots_llm(text: str) -> ExtractedSlots:
    """Use the configured LLM to extract slots.  Falls back to deterministic."""
    provider = current_app.config.get("LLM_PROVIDER", "deterministic")

    try:
        if provider == "openai":
            return _extract_openai(text)
        elif provider == "anthropic":
            return _extract_anthropic(text)
    except Exception:
        pass

    return extract_slots_deterministic(text)


# ── OpenAI helpers ────────────────────────────────────────────────────────────


def _classify_openai(text: str) -> str:
    from langchain_openai import ChatOpenAI  # type: ignore
    from langchain_core.messages import SystemMessage, HumanMessage
    from src.agents.transfer_agent.prompts.korean_prompts import INTENT_CLASSIFICATION_SYSTEM

    model = current_app.config.get("OPENAI_MODEL", "gpt-4o-mini")
    api_key = current_app.config.get("OPENAI_API_KEY")
    llm = ChatOpenAI(model=model, api_key=api_key, temperature=0)
    resp = llm.invoke([SystemMessage(content=INTENT_CLASSIFICATION_SYSTEM), HumanMessage(content=text)])
    data = json.loads(resp.content)
    return data.get("intent", "unknown")


def _extract_openai(text: str) -> ExtractedSlots:
    from langchain_openai import ChatOpenAI  # type: ignore
    from langchain_core.messages import SystemMessage, HumanMessage
    from src.agents.transfer_agent.prompts.korean_prompts import SLOT_EXTRACTION_SYSTEM

    model = current_app.config.get("OPENAI_MODEL", "gpt-4o-mini")
    api_key = current_app.config.get("OPENAI_API_KEY")
    llm = ChatOpenAI(model=model, api_key=api_key, temperature=0)
    resp = llm.invoke([SystemMessage(content=SLOT_EXTRACTION_SYSTEM), HumanMessage(content=text)])
    data = json.loads(resp.content)
    return ExtractedSlots(**data)


# ── Anthropic helpers ─────────────────────────────────────────────────────────


def _classify_anthropic(text: str) -> str:
    from langchain_anthropic import ChatAnthropic  # type: ignore
    from langchain_core.messages import SystemMessage, HumanMessage
    from src.agents.transfer_agent.prompts.korean_prompts import INTENT_CLASSIFICATION_SYSTEM

    model = current_app.config.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    api_key = current_app.config.get("ANTHROPIC_API_KEY")
    llm = ChatAnthropic(model=model, api_key=api_key, temperature=0)
    resp = llm.invoke([SystemMessage(content=INTENT_CLASSIFICATION_SYSTEM), HumanMessage(content=text)])
    data = json.loads(resp.content)
    return data.get("intent", "unknown")


def _extract_anthropic(text: str) -> ExtractedSlots:
    from langchain_anthropic import ChatAnthropic  # type: ignore
    from langchain_core.messages import SystemMessage, HumanMessage
    from src.agents.transfer_agent.prompts.korean_prompts import SLOT_EXTRACTION_SYSTEM

    model = current_app.config.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    api_key = current_app.config.get("ANTHROPIC_API_KEY")
    llm = ChatAnthropic(model=model, api_key=api_key, temperature=0)
    resp = llm.invoke([SystemMessage(content=SLOT_EXTRACTION_SYSTEM), HumanMessage(content=text)])
    data = json.loads(resp.content)
    return ExtractedSlots(**data)
