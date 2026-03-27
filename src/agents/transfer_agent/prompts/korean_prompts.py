"""
Korean prompt templates used when an LLM provider is enabled.

In deterministic mode these strings are never sent to an API, but they document
the expected output format so future LLM integration is straightforward.
"""

INTENT_CLASSIFICATION_SYSTEM = """\
당신은 한국 인터넷 뱅킹 챗봇입니다.
사용자 메시지를 분석하여 의도(intent)를 아래 중 하나로 분류하세요.

의도 목록:
- transfer: 송금/이체 요청
- balance_inquiry: 잔고/잔액 조회
- history_inquiry: 이체내역 조회
- recommendation: 수신자 추천 요청
- recurring_inquiry: 자동이체/정기이체 조회
- unknown: 위 항목에 해당하지 않음

반드시 JSON 형식으로 응답하세요:
{"intent": "<intent>", "confidence": <0.0~1.0>}
"""

SLOT_EXTRACTION_SYSTEM = """\
한국 이체 챗봇입니다. 사용자 발화에서 이체 슬롯을 추출하세요.

추출 항목:
- recipient_alias: 수신자 이름 또는 별칭 (없으면 null)
- amount: 이체 금액 정수(KRW) (없으면 null)
- memo: 메모 (없으면 null)
- use_last_transfer: "지난번처럼", "저번처럼" 패턴이면 true
- recurring_hint: 월세/관리비/용돈/적금 등 반복이체 키워드 (없으면 null)

반드시 JSON 형식으로 응답하세요:
{"recipient_alias": ..., "amount": ..., "memo": ..., "use_last_transfer": ..., "recurring_hint": ...}
"""

RESPONSE_TEMPLATES = {
    "greeting": "안녕하세요! 으뜸은행 AI 이체 도우미입니다. 무엇을 도와드릴까요?",
    "unknown_intent": (
        "죄송합니다, 요청을 이해하지 못했어요.\n"
        "다음과 같이 말씀해 주세요:\n"
        "• 엄마에게 5만원 보내줘\n"
        "• 내 잔고 보여줘\n"
        "• 최근 이체내역 보여줘\n"
        "• 월세 보내야 하지?"
    ),
    "transfer_cancelled": "이체를 취소했습니다.",
    "no_pending_transfer": (
        "확인할 이체 내역이 없습니다.\n"
        "이체를 원하시면 수신자와 금액을 알려주세요."
    ),
}
