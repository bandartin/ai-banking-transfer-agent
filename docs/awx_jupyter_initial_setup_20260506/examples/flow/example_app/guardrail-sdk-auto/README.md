# guardrail-sdk-auto

이 예제는 **SDK 입문 다음 단계**의 고급 샘플입니다.

## 이 예제를 먼저 볼 때

- Guardrail 정책을 FastAPI 앱 경계에서 실제로 연결하고 싶을 때
- non-stream과 stream 양쪽에서 `filter -> llm -> filter` 흐름을 보고 싶을 때
- resource integration보다 정책 적용과 응답 제어 예제가 더 필요할 때

`awx.resources` 가드레일과 OpenAI 호출을 실제 FastAPI 앱 경계에서 연결하는 방법을 보여줍니다.

- `filter -> llm -> filter`
- `filter -> llm(stream) -> filter(stream)`

먼저 보면 좋은 기본 예제:

- `../../example_sdk/example_resources/guardrail_example.py`
- `../../example_sdk/example_observability/telemetry_example.py`

## 이 예제로 배우는 것

- `Guardrail.apply(...)`
- `Guardrail.apply_openai_stream(...)`
- OpenAI 응답 stream을 필터에 연결하는 방식
- 응답의 `trace_id`로 추적을 이어서 보는 방법

## 정책 조회 방식

이 예제는 기본적으로 **Portal API에서 필터 정책을 조회**합니다.

- `DLP_RUN_MODE=MODELING` (기본)
- `GENAI_TEXT_FLOW_ID` (기본 `.env` 값 사용)
- `FILTER_POLICY_IDS` (기본 `.env` 값 사용, optional policy 선택용)
- SDK 내부 호출: `/sportal/v3/intapi/llm/flow/{flow_id}/filters`

즉, `params.json`이 아니라 Builder 정책을 그대로 사용합니다.
HTTP request body에서 정책 ID를 받지 않고, 내부 설정값으로만 optional policy를 선택합니다.

실패 시 먼저 확인할 점:

- `GENAI_TEXT_FLOW_ID`가 없거나 잘못되면 정책 조회가 실패합니다.
- `FILTER_POLICY_IDS`는 쉼표로 구분한 양의 정수여야 합니다.
- Builder에 필터 정책이 없으면 guardrail 동작을 확인할 수 없습니다.
- `OPENAI_API_KEY`가 없으면 LLM 호출이 실패합니다.

## 실행

```bash
cd /home/user/idea-project/container-script/example_awx/flow/example_app/guardrail-sdk-auto
export OPENAI_API_KEY=<your_key>
export OPENAI_MODEL=gpt-4o-mini
bash run_app.sh 127.0.0.1 8001
```

`run_app.sh`는 `opentelemetry-instrument`로 실행됩니다.
`service.name`과 `awx.project.id`는 SDK가 실행 환경 메타데이터로 계산합니다.
분석환경에서는 OTEL endpoint를 따로 적지 않아도 SDK가 주입된 collector endpoint를 자동 감지합니다.

## 실제 구동 환경과 로컬 차이

- 실제 구동 기준은 builder/inference runtime이며, Guardrail 정책은 Portal API 또는 platform-provided `params.json` 계약을 통해 해석됩니다.
- 지금 저장소에서 확인하는 로컬 실행은 `make init`, `make run`, FastAPI 프로세스 기동, 샘플 route 응답 확인 범위입니다.
- 로컬에서 end-to-end LLM/guardrail 동작까지 보려면 `OPENAI_API_KEY`, 실제 `GENAI_TEXT_FLOW_ID`, optional policy 선택값이 맞아야 합니다.
- 실제 환경 변수가 필요하면 저장소 값에 기대하지 말고 사용자/운영자에게 요청하세요.

## API

### 1) Non-stream: filter -> llm -> filter

```bash
curl -sS -X POST 'http://127.0.0.1:8001/e2e/filter-llm-filter' \
  -H 'Content-Type: application/json' \
  -d '{
    "message":"주민번호 850505-2345678"
  }'
```

### 2) Stream: filter -> llm(stream) -> filter(stream)

```bash
curl -sS -X POST 'http://127.0.0.1:8001/e2e/filter-llm-stream-filter-stream' \
  -H 'Content-Type: application/json' \
  -d '{
    "message":"휴대전화 010-1234-5678",
    "chunk_size":32,
    "overlap_tokens":8,
    "holdback_tokens":16
  }'
```

기본 `.env` 값은 `FILTER_POLICY_IDS=16`이며, flow `368`의 optional policy 중 `개인정보 필터 정책`을 사용합니다.
필요하면 `.env`에서 `16,18`처럼 바꿔 여러 optional policy를 적용할 수 있습니다.

응답 JSON의 `trace_id`로 Tempo/Grafana에서 trace를 조회하면 됩니다.

## 다음으로 볼 예제

- 기존 FastAPI 앱에 observability를 붙이는 방식:
  `../fastapi-observability-auto/client/README.md`
