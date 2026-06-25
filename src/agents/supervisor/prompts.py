"""
Dynamic Prompting — 프롬프트를 정적 문자열이 아니라
Runtime Context(나이/등급/리스크) + State 를 조합해 호출 시점에 동적 조립한다.

두 계층으로 동작한다:
  1. LLM 모드  : build_*_prompt() 가 상황 맞춤 시스템 프롬프트를 생성
  2. 결정론 모드: apply_tone() 이 동일한 말투 정책을 템플릿 수준에서 적용
                  (LLM 키가 없어도 나이 맞춤 말투가 시연됨)
"""

from __future__ import annotations

from src.agents.context import BankingContext


# ─────────────────────────────────────────────────────────────────────────────
# 말투 프로필 (나이 기반)
# ─────────────────────────────────────────────────────────────────────────────

TONE_GUIDES = {
    "young": (
        "고객은 20~30대입니다. 간결하고 친근한 존댓말을 쓰세요. "
        "불필요한 설명은 생략하고 핵심만 전달하며, 가벼운 이모지를 한두 개 사용해도 좋습니다."
    ),
    "standard": (
        "고객은 30~50대입니다. 정중하고 명확한 표준 존댓말을 쓰세요. "
        "군더더기 없이 필요한 정보를 정확히 전달하세요."
    ),
    "senior": (
        "고객은 60대 이상입니다. 천천히, 차분하고 공손하게 설명하세요. "
        "금융 용어(수수료, 한도, OTP 등)는 반드시 쉬운 말로 풀어서 안내하고, "
        "다음에 무엇을 하면 되는지 한 단계씩 알려주세요. 이모지는 쓰지 마세요."
    ),
}


def _customer_block(ctx: BankingContext) -> str:
    """모든 동적 프롬프트에 들어가는 고객 컨텍스트 블록."""
    parts = [
        f"고객명: {ctx.display_name or '고객'}",
        f"나이: {ctx.age if ctx.age else '미상'}세",
        f"등급: {'VIP' if ctx.customer_tier == 'vip' else '일반'}",
    ]
    if ctx.risk_profile == "high":
        parts.append("주의: 최근 이상거래 이력이 있는 보안 강화 대상 고객")
    return " / ".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Supervisor planner prompt
# ─────────────────────────────────────────────────────────────────────────────


def build_planner_prompt(ctx: BankingContext, agent_cards: str) -> str:
    prompt = f"""당신은 으뜸은행 AI 뱅킹의 Supervisor(리더) 에이전트입니다.
사용자 메시지를 분석해 어떤 하위 에이전트를 어떤 순서로 호출할지 계획(ExecutionPlan)을 세우세요.

[고객 정보]
{_customer_block(ctx)}

[가용 하위 에이전트]
{agent_cards}

[계획 규칙]
1. 이체 요청이 포함되면 steps 는 transfer 하나만 넣으세요 (이체 플로우가 보안 검증을 자체 협업으로 수행합니다).
2. 조회성 요청(잔액/내역/자동이체/추천/보안점검/메뉴검색/상품안내)이 여러 개면 parallel=true 로 동시에 실행하세요.
3. 금융 계산 요청은 financial_calculator 로 보내세요. 계산 숫자는 코드가 산출하고, LLM은 표현만 다듬습니다.
4. 고객 잔액, 한도, 계좌상태, 인증결과, 이체실행 여부를 RAG/지식검색으로 판단하지 마세요.
5. 어떤 에이전트에도 해당하지 않으면 steps 를 비우고 primary_intent="unknown" 으로 두세요.
6. 각 step 의 reason 에 선택 이유를 한국어 한 문장으로 쓰세요 (사용자에게 표시됩니다).
"""
    if ctx.risk_profile == "high":
        prompt += "\n7. 이 고객은 보안 강화 대상입니다. 조회 계획에도 security(report) 단계를 추가하는 것을 고려하세요.\n"
    return prompt


# ─────────────────────────────────────────────────────────────────────────────
# Slot extraction prompt
# ─────────────────────────────────────────────────────────────────────────────


def build_slot_prompt(ctx: BankingContext, known_aliases: list[str], followup_memory: dict | None = None) -> str:
    alias_hint = ", ".join(known_aliases[:20]) if known_aliases else "(없음)"
    memory_block = _slot_memory_block(followup_memory or {})
    return f"""한국 개인뱅킹 이체 도우미입니다. 사용자 발화에서 이체 슬롯을 추출하세요.

[고객 정보] {_customer_block(ctx)}
[고객이 쓰는 수신자 호칭 예시] {alias_hint}
{memory_block}

추출 항목:
- raw_amount_text: 원문 금액 표현. 없으면 null
- recipient_text: 원문 수신자 표현. 없으면 null
- recipient_alias: 수신자 이름/별칭/호칭 (엄마, 여친, 민수 등. 없으면 null)
- amount: 이체 금액 정수(KRW). "5만원"→50000 (없으면 null)
- memo: 이체 메모. "밥값이라고 적어줘" → "밥값" (없으면 null)
- use_last_transfer: "지난번처럼/저번처럼" 패턴이면 true
- recurring_hint: 월세/관리비/용돈/적금 등 반복이체 키워드 (없으면 null)
- bank_hint: 수신 은행 힌트. "한빛은행 엄마한테" → "한빛은행" (없으면 null)
- source_account_hint: 출금 계좌 힌트. "월급통장에서" → "월급통장" (없으면 null)
- confidence: 0.0~1.0 사이 신뢰도
- ambiguous_fields: 애매하거나 추정이 필요한 필드명 목록
- missing_fields: 이체 진행에 필요한데 누락된 필드명 목록
- evidence: 각 슬롯의 근거가 된 원문 조각

호칭("여친", "우리 큰딸")도 recipient_alias 로 추출하세요. 호칭 해석은 코드가 합니다.
없는 정보는 추정하지 말고 null 또는 missing_fields/ambiguous_fields 로 표시하세요.
금액은 반드시 KRW 정수로 출력하세요.
"""


def _slot_memory_block(memory: dict) -> str:
    lines = []

    recs = memory.get("last_recommendations") or []
    if recs:
        lines.append("[직전 추천 결과]")
        for r in recs[:5]:
            label = r.get("alias") or r.get("name")
            amount = f", 추천금액 {r.get('suggested_amount'):,}원" if r.get("suggested_amount") else ""
            lines.append(f"{r.get('rank')}. {label} ({r.get('name')}, {r.get('bank_name')}{amount})")

    history = memory.get("last_history_items") or []
    if history:
        lines.append("[직전 이체내역]")
        for i, h in enumerate(history[:5], start=1):
            label = h.get("alias") or h.get("name")
            lines.append(f"{i}. {label} ({h.get('name')}, {h.get('bank_name')}) {h.get('amount'):,}원")

    balance = memory.get("last_balance_summary") or {}
    if balance:
        lines.append("[직전 잔액/한도]")
        lines.append(
            f"남은 일일 한도 {balance.get('daily_remaining', 0):,}원, "
            f"1회 한도 {balance.get('single_transfer_limit', 0):,}원"
        )

    if not lines:
        return ""
    return "\n" + "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Response polish prompt (말투 다듬기)
# ─────────────────────────────────────────────────────────────────────────────


def build_polish_prompt(ctx: BankingContext) -> str:
    tone = TONE_GUIDES.get(ctx.tone, TONE_GUIDES["standard"])
    return f"""당신은 으뜸은행 AI 이체 도우미의 응답 편집자입니다.
아래 초안의 **사실(금액, 계좌번호, 수신자, 잔액, 횟수)은 절대 바꾸지 말고** 말투만 다듬으세요.

[고객 정보] {_customer_block(ctx)}
[말투 지침] {tone}

목록/표 구조와 줄바꿈은 유지하세요. 다듬은 본문만 출력하세요.
"""


# ─────────────────────────────────────────────────────────────────────────────
# 결정론 모드 말투 적용 (LLM 없이도 Dynamic Prompting 효과 시연)
# ─────────────────────────────────────────────────────────────────────────────

_SENIOR_GLOSSARY = [
    ("수수료", "수수료(은행에 내는 부가 비용)"),
    ("OTP", "OTP(일회용 비밀번호)"),
    ("일일 한도", "일일 한도(하루에 보낼 수 있는 최대 금액)"),
]


def apply_tone(ctx: BankingContext, text: str, response_type: str = "message") -> str:
    """결정론적 말투 보정 — 나이 프로필에 따라 호칭/설명 수준을 조정한다."""
    if not text:
        return text

    tone = ctx.tone
    name = ctx.display_name or "고객"

    if tone == "senior":
        # 금융 용어 풀어쓰기 (첫 등장 1회만)
        for term, gloss in _SENIOR_GLOSSARY:
            if term in text and gloss not in text:
                text = text.replace(term, gloss, 1)
        if response_type == "success":
            text += f"\n\n{name}님, 이체가 잘 끝났습니다. 더 도와드릴 일이 있으면 천천히 말씀해 주세요."
        elif response_type == "confirmation":
            text += "\n\n내용을 천천히 확인하시고, 맞으면 '확인'이라고 말씀해 주세요. 잘못되었으면 '취소'라고 하시면 됩니다."
    elif tone == "young":
        if response_type == "success":
            text += " 🎉"
    return text
