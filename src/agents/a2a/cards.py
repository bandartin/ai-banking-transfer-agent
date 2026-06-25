"""
A2A Agent Cards — 각 에이전트의 능력 명세.

A2A 프로토콜의 핵심 개념인 Agent Card(에이전트 디스커버리 명세)를 정의한다.
이 카드는 두 곳에서 쓰인다:
  1. 내부: Supervisor 의 Dynamic Prompt 에 "가용 에이전트 목록"으로 주입
     → LLM 플래너가 카드를 보고 호출 대상을 고른다 (A2A discovery 의 내부 적용)
  2. 외부: /.well-known/agent-card.json 및 /api/a2a/* 로 노출
     → 타 시스템 에이전트가 표준 방식으로 발견/호출 가능
"""

from __future__ import annotations

A2A_VERSION = "0.3.0"

AGENT_CARDS: dict[str, dict] = {
    "transfer": {
        "name": "TransferAgent",
        "description": "자연어 이체 실행 에이전트. 슬롯 추출, 수신자 해석(호칭 학습 메모리 포함), 한도/잔액 검증, 확인·OTP 휴먼인더루프, 원장 반영까지 담당한다.",
        "version": "2.0.0",
        "capabilities": {"streaming": False, "pushNotifications": False},
        "skills": [
            {
                "id": "transfer",
                "name": "계좌이체",
                "description": "수신자·금액·메모를 해석해 이체를 준비하고 사용자 확인 후 실행",
                "tags": ["transfer", "payment", "human-in-the-loop"],
                "examples": ["엄마한테 5만원 보내줘", "월세 보내야 하지?", "지난번처럼 보내줘"],
            }
        ],
        "collaborates_with": ["security"],
    },
    "inquiry": {
        "name": "InquiryAgent",
        "description": "계좌/거래 조회 에이전트. 잔액, 이체내역, 자동이체 목록을 조회한다. 읽기 전용.",
        "version": "2.0.0",
        "capabilities": {"streaming": False},
        "skills": [
            {"id": "balance", "name": "잔액 조회", "description": "계좌별 잔액과 오늘의 이체 가능 한도", "tags": ["read-only"], "examples": ["내 잔고 보여줘"]},
            {"id": "history", "name": "이체내역 조회", "description": "최근 이체 기록", "tags": ["read-only"], "examples": ["최근 이체내역 보여줘"]},
            {"id": "recurring", "name": "자동이체 조회", "description": "등록된 정기이체 목록", "tags": ["read-only"], "examples": ["자동이체 뭐 있지?"]},
        ],
    },
    "recommend": {
        "name": "RecommendAgent",
        "description": "이체 패턴 기반 추천 에이전트. 즐겨찾기·이체빈도·자동이체 데이터를 점수화해 보낼 만한 수신자와 금액을 추천한다.",
        "version": "2.0.0",
        "capabilities": {"streaming": False},
        "skills": [
            {"id": "recipients", "name": "수신자 추천", "description": "자주/최근 보낸 수신자 순위와 추천 금액", "tags": ["read-only"], "examples": ["자주 보내는 사람 추천해줘"]},
        ],
    },
    "security": {
        "name": "SecurityAgent",
        "description": "보안/사기탐지 에이전트. 결정론적 룰(심야 고액, 신규 수신자, 단시간 다건 등)로 이체 리스크를 평가하고 OTP 강화 여부를 결정한다. TransferAgent 의 협업 요청을 받아 검증을 수행한다.",
        "version": "2.0.0",
        "capabilities": {"streaming": False},
        "skills": [
            {"id": "assess", "name": "이체 리스크 평가", "description": "이체 1건의 리스크 점수/경고/OTP 강제 여부", "tags": ["fraud-detection", "a2a-collaboration"], "examples": []},
            {"id": "report", "name": "보안 리포트", "description": "최근 7일 이체 패턴 기반 계좌 보안 점검", "tags": ["read-only"], "examples": ["내 계좌 안전한지 점검해줘"]},
        ],
    },
    "menu_search": {
        "name": "MenuSearchAgent",
        "description": "앱/업무 메뉴 위치를 AWX 지식저장소 또는 로컬 지식 catalog에서 검색한다. 고객 잔액·한도 같은 실시간 값은 조회하지 않는다.",
        "version": "1.0.0",
        "capabilities": {"streaming": False},
        "skills": [
            {
                "id": "menu",
                "name": "메뉴 검색",
                "description": "메뉴명, 업무명, 사용자가 하려는 일을 바탕으로 화면 경로를 찾음",
                "tags": ["rag", "read-only", "menu"],
                "examples": ["이체한도 변경 메뉴 어디 있어?", "OTP 재발급은 어디서 해?"],
            },
        ],
    },
    "product_guide": {
        "name": "ProductGuideAgent",
        "description": "상품, 수수료, FAQ, 이용안내를 RAG 기반으로 설명하고 근거 문서 metadata를 반환한다.",
        "version": "1.0.0",
        "capabilities": {"streaming": False},
        "skills": [
            {
                "id": "guide",
                "name": "상품/수수료 안내",
                "description": "상품/수수료/FAQ/규정 문서 기반 설명",
                "tags": ["rag", "read-only", "product", "fee"],
                "examples": ["타행 이체 수수료 알려줘", "정기예금은 어떤 상품이야?"],
            },
        ],
    },
    "financial_calculator": {
        "name": "FinancialCalculatorAgent",
        "description": "예금 이자와 대출 원리금 상환액을 결정론적 코드로 계산한다. 설명은 지식검색과 결합 가능하나 계산값은 LLM이 만들지 않는다.",
        "version": "1.0.0",
        "capabilities": {"streaming": False},
        "skills": [
            {
                "id": "calculate",
                "name": "금융 계산",
                "description": "예금이자, 만기금액, 대출 원리금균등 상환액 계산",
                "tags": ["calculator", "deterministic", "read-only"],
                "examples": ["1,000만원을 연 3.5%로 12개월 예금하면 이자 얼마야?", "1억원을 연 4%로 30년 상환하면 월 얼마야?"],
            },
        ],
    },
}


def render_cards_for_prompt() -> str:
    """Supervisor Dynamic Prompt 에 주입할 에이전트 카드 요약."""
    lines = []
    for key, card in AGENT_CARDS.items():
        skills = ", ".join(f"{s['id']}({s['name']})" for s in card["skills"])
        lines.append(f"- {key} [{card['name']}]: {card['description']}\n  스킬: {skills}")
    return "\n".join(lines)


def public_card(agent_key: str, base_url: str) -> dict:
    """외부 노출용 A2A Agent Card (URL 포함)."""
    card = dict(AGENT_CARDS[agent_key])
    card["protocolVersion"] = A2A_VERSION
    card["url"] = f"{base_url}/api/a2a/agents/{agent_key}/invoke"
    card["preferredTransport"] = "JSONRPC"
    card["defaultInputModes"] = ["text/plain"]
    card["defaultOutputModes"] = ["application/json"]
    return card
