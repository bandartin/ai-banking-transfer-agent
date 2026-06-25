# Slot 추출 고도화 작업 보고서

## 1. 작업 목적

이체 Agent의 핵심 입력 단계인 Slot 추출을 고도화하여 자연어 이해 범위를 넓히고, LLM 사용 시에도 금융 실행 안전성을 유지하도록 개선했다.

## 2. 주요 개선 내용

1. Slot 스키마 확장
   - `raw_amount_text`, `recipient_text`, `source_account_hint`, `confidence`, `ambiguous_fields`, `missing_fields`, `evidence`, `extraction_method`를 추가했다.
   - 추출 결과가 단순 값이 아니라 근거와 불확실성을 함께 남기도록 했다.

2. Rule parser 보강
   - 원문 금액 표현, 은행 힌트, 출금계좌 힌트, 누락 필드를 추출한다.
   - Rule parser는 LLM fallback이자 LLM 결과 교차검증 기준으로 사용된다.

3. LLM-Rule 교차검증
   - LLM Slot 추출 결과와 Rule parser 결과를 병합한다.
   - 금액이 충돌하면 Rule 값을 우선하고, 충돌 내역은 `ambiguous_fields`와 `evidence`에 기록한다.
   - LLM이 Rule로 확인되지 않은 금액을 제시하면 `amount`를 확인 필요 필드로 표시한다.

4. Follow-up memory 프롬프트 주입
   - 직전 추천 결과, 이체내역, 잔액/한도 요약을 Slot extraction prompt에 주입한다.
   - “1번한테 보내줘”, “그 사람한테”, “가능한 만큼” 같은 후속 발화를 더 잘 해석할 수 있다.

5. Slot 활용 범위 확대
   - `bank_hint`는 동명이인 후보를 은행명으로 좁히는 데 사용한다.
   - `source_account_hint`는 실제 출금 계좌 선택에 반영한다.
   - 존재하지 않는 출금계좌 힌트는 주계좌로 임의 대체하지 않고 오류로 중단한다.

## 3. 테스트 보강

- Rule Slot metadata 추출 테스트 추가
- 누락 필드 감지 테스트 추가
- LLM-Rule 금액 충돌 교차검증 테스트 추가
- 은행 힌트 기반 동명이인 해소 테스트 추가
- 출금계좌 힌트 반영 테스트 추가

## 4. 검증 결과

- `git diff --check` 통과
- 현재 작업 환경에서는 `python.exe`가 Windows Store stub로 연결되어 `pytest` 실행은 불가했다.
- Python 런타임 연결 후 `python -m pytest tests/test_parsing.py tests/test_agent.py -q` 실행이 필요하다.

## 5. 기대 효과

- LLM 기반 Slot 추출의 표현 이해력이 향상된다.
- Rule parser가 안전 기준으로 남아 금액 등 핵심 필드의 오인식 위험을 낮춘다.
- Slot 추출 결과의 근거와 불확실성을 로그/디버그 화면에서 확인할 수 있어 운영 점검성이 좋아진다.
