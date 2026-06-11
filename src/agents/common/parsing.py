"""
결정론적 한국어 파서 — 금액/인텐트/슬롯. Flask 비의존(순수 함수).

LLM 키가 없을 때의 폴백이자, "LLM은 이해만, 결정은 코드가" 원칙의 기준 구현.
"""

from __future__ import annotations

import re
from typing import List, Optional

from src.agents.common.schemas import ExtractedSlots


# ─────────────────────────────────────────────────────────────────────────────
# Korean amount parser
# ─────────────────────────────────────────────────────────────────────────────


def parse_amount(text: str) -> Optional[int]:
    """Parse a Korean amount expression into an integer KRW value."""
    text = text.replace(" ", "")

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

    # "5만5천원" compound
    m = re.search(r"(\d+)만\s*(\d+)천", text)
    if m:
        return int(m.group(1)) * 10_000 + int(m.group(2)) * 1_000

    m = re.search(r"(\d+(?:\.\d+)?)만", text)
    if m:
        return int(float(m.group(1)) * 10_000)

    m = re.search(r"(\d+(?:\.\d+)?)천", text)
    if m:
        return int(float(m.group(1)) * 1_000)

    m = re.search(r"(\d{1,3}(?:,\d{3})+)", text)
    if m:
        return int(m.group(1).replace(",", ""))

    m = re.search(r"(\d+)원", text)
    if m:
        return int(m.group(1))

    # 한글 수사: "만원", "오만원", "삼십만원", "백만원" …
    m = re.search(r"([일이삼사오육칠팔구십백천만억]+)\s*원", text)
    if m:
        value = _korean_numeral_to_int(m.group(1))
        if value:
            return value

    return None


_KOR_DIGITS = {"일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "칠": 7, "팔": 8, "구": 9}
_KOR_SMALL_UNITS = {"십": 10, "백": 100, "천": 1_000}
_KOR_BIG_UNITS = {"만": 10_000, "억": 100_000_000}


def _korean_numeral_to_int(s: str) -> Optional[int]:
    """한글 수사 → 정수.  예: '만'→10000, '오만'→50000, '삼십만'→300000."""
    total = 0
    section = 0  # 현재 만/억 구간의 합
    num = 0      # 현재 자리 숫자

    for ch in s:
        if ch in _KOR_DIGITS:
            num = _KOR_DIGITS[ch]
        elif ch in _KOR_SMALL_UNITS:
            section += (num or 1) * _KOR_SMALL_UNITS[ch]
            num = 0
        elif ch in _KOR_BIG_UNITS:
            section += num
            total += (section or 1) * _KOR_BIG_UNITS[ch]
            section = 0
            num = 0
        else:
            return None

    total += section + num
    return total if total > 0 else None


# ─────────────────────────────────────────────────────────────────────────────
# Intent detection (multi-intent aware — Supervisor rule planner 가 사용)
# ─────────────────────────────────────────────────────────────────────────────

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
        r"보낼.*만한",
    ]),
    ("recurring_inquiry", [
        r"자동이체", r"정기이체", r"자동.*확인", r"정기.*확인",
    ]),
    ("security_inquiry", [
        r"안전.*이체", r"이체.*안전", r"보안.*점검", r"사기.*의심",
        r"보이스피싱", r"이상.*거래",
    ]),
    # transfer is checked last to avoid matching "보내" inside recommendation phrases
    ("transfer", [
        r"보내줘", r"보내주세요", r"송금", r"계좌이체", r"입금해줘",
        r"부쳐줘", r"쏴줘", r"보내야", r"내야\s*(?:하|되|돼)",
        r"[가-힣]+(?:에게|한테|께).*(?:보내|이체|송금)",
        r"(?:보내|이체|송금).*[가-힣]+(?:에게|한테|께)",
        r"(?:\d+|[가-힣]+)원.*(?:보내|이체|송금)",
        r"(?:보내|이체|송금).*(?:\d+|[가-힣]+)원",
    ]),
]


def classify_intent(text: str) -> str:
    """Rule-based Korean intent classifier — 첫 매칭 인텐트 하나만 반환."""
    for intent, patterns in _INTENT_RULES_ORDERED:
        for p in patterns:
            if re.search(p, text):
                return intent

    if re.search(r"보내|이체|송금", text):
        return "transfer"

    return "unknown"


def detect_intents(text: str) -> List[str]:
    """복합 발화에서 매칭되는 *모든* 인텐트 — Supervisor 병렬 계획의 근거.

    예: "잔고 보여주고 보낼 만한 사람도 추천해줘"
        → ["balance_inquiry", "recommendation"]
    """
    found: List[str] = []
    for intent, patterns in _INTENT_RULES_ORDERED:
        for p in patterns:
            if re.search(p, text):
                found.append(intent)
                break

    # transfer 가 다른 조회 인텐트의 패턴과 함께 잡힌 경우:
    # 이체 요청이 있으면 이체가 우선 (조회는 transfer 플로우가 단독 처리)
    if not found and re.search(r"보내|이체|송금", text):
        found.append("transfer")
    return found or ["unknown"]


def is_confirmation(text: str) -> bool:
    text = text.strip()
    return bool(re.search(
        r"^(확인|보내|전송|실행|예|응|ㅇ|네|넵|네네|그래|좋아|맞아|ok|yes|보낼게|맞아요|맞습니다|보내줘|보내주세요|진행해줘?|해줘)$",
        text, re.I,
    ))


def is_cancellation(text: str) -> bool:
    text = text.strip()
    return bool(re.search(r"^(취소|아니|아니오|아니요|싫어|no|그만|중지|stop|안\s?보낼래|취소해줘?)$", text, re.I))


# ─────────────────────────────────────────────────────────────────────────────
# Slot extraction
# ─────────────────────────────────────────────────────────────────────────────

_RECIPIENT_PATTERNS = [
    r"([가-힣a-zA-Z0-9]+?)(?:에게|한테|께|에게로|한테로)\s",
    r"([가-힣a-zA-Z0-9]+?)(?:한테|에게)\s?(?:보내|송금|이체|부쳐|쏴)",
]

_RECURRING_KEYWORDS = {
    "월세": ["월세"],
    "관리비": ["관리비"],
    "용돈": ["용돈"],
    "적금": ["적금"],
    "보험료": ["보험료", "보험"],
    "공과금": ["공과금", "전기세", "수도세", "가스비"],
    "통신비": ["통신비", "핸드폰비", "휴대폰비"],
    "회비": ["회비", "모임비"],
}

_LAST_TRANSFER_PATTERNS = [r"지난번처럼", r"저번처럼", r"지난번과.*같이", r"똑같이", r"이전처럼", r"지난번\s*만큼"]

# 수신자 별칭이 될 수 없는 일반 명사
_EXCLUDED_ALIASES = {
    "지난번", "저번", "이전", "최근", "돈", "돈을", "얼마", "오늘", "내일",
    "그냥", "빨리", "지금", "바로", "이체", "송금", "계좌",
}


def extract_slots(text: str) -> ExtractedSlots:
    """Deterministic slot extraction from Korean text."""
    amount = parse_amount(text)

    alias = None
    for pattern in _RECIPIENT_PATTERNS:
        m = re.search(pattern, text + " ")  # trailing space for lookahead
        if m:
            candidate = m.group(1).strip()
            if candidate not in _EXCLUDED_ALIASES:
                alias = candidate
                break

    if not alias:
        m = re.search(r"([가-힣]+)\s*(?:한테|에게)?.*?(?:보내|송금|이체|부쳐|쏴)", text)
        if m:
            candidate = m.group(1).strip()
            if candidate not in _EXCLUDED_ALIASES:
                alias = candidate

    memo = None
    m = re.search(r"메모\s*[:\s]\s*([^\s]+)", text)
    if m:
        memo = m.group(1)
    else:
        # 카카오뱅크 스타일: "~라고 적어서 / ~라고 메모해서" 자연어 메모
        m = re.search(r"['\"]?([가-힣a-zA-Z0-9]+?)['\"]?(?:이라고|라고)\s*(?:적어|메모|남겨)", text)
        if m:
            memo = m.group(1).strip()

    use_last = any(re.search(p, text) for p in _LAST_TRANSFER_PATTERNS)

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
