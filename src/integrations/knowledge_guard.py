"""Guardrails for knowledge/RAG style retrieval.

RAG is appropriate for menu paths, product explanations, fee-policy documents,
FAQ, and operation manuals.  It is not an authoritative source for customer
balances, account status, authentication, or transfer execution results.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class KnowledgeGuardDecision:
    allowed: bool
    reason: str = ""


_CUSTOMER_VALUE_PATTERNS = [
    r"내\s*(?:잔액|잔고|한도)",
    r"잔액\s*(?:얼마|조회|보여|알려)",
    r"잔고\s*(?:얼마|조회|보여|알려)",
    r"한도\s*(?:얼마|남았|조회|보여|알려)",
    r"계좌\s*(?:상태|정지|사고|번호)",
    r"이체\s*(?:결과|완료|실패|처리\s*됐|됐는지|내역)",
    r"송금\s*(?:결과|완료|실패|됐는지)",
    r"(?:OTP|오티피|인증)\s*(?:결과|실패|성공|확인)",
]

_MENU_OR_GUIDE_PATTERNS = [
    r"메뉴",
    r"화면",
    r"경로",
    r"어디(?:서|에)",
    r"찾",
    r"방법",
    r"안내",
]


def assess_knowledge_query(query: str, *, collection: str = "") -> KnowledgeGuardDecision:
    """Return whether a query can be answered via knowledge retrieval.

    A phrase such as "이체한도 변경 메뉴 어디 있어?" is allowed because the user
    is asking for a menu path, not their personal remaining limit.  A phrase such
    as "내 한도 얼마 남았어?" is blocked and must go to InquiryAgent.
    """
    text = query or ""
    if _looks_like_menu_or_guide(text):
        return KnowledgeGuardDecision(True)
    for pattern in _CUSTOMER_VALUE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return KnowledgeGuardDecision(
                False,
                "고객별 잔액, 한도, 계좌상태, 인증, 이체결과는 RAG가 아니라 실시간 은행 연계로 조회해야 합니다.",
            )
    return KnowledgeGuardDecision(True)


def _looks_like_menu_or_guide(text: str) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in _MENU_OR_GUIDE_PATTERNS)

