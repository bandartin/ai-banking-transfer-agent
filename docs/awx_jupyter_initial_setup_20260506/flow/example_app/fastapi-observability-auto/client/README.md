# AWX Observability SDK 연동 가이드 (Client 개발자용)

이 문서는 **기존 Agent 앱 코드(FastAPI 기준)** 에 observability SDK를 붙여
OpenTelemetry 데이터를 자동 보강/전송하는 방법을 설명합니다.

즉, 이 문서는 **기존 앱 통합 가이드**이며 SDK 입문 문서는 아닙니다.

## 이 예제를 먼저 볼 때

- 이미 FastAPI 앱이나 Agent 앱이 있고 여기에 AWX SDK observability를 붙이고 싶을 때
- 새 앱을 만드는 것보다 기존 앱 코드에 `instrument_app(app)`를 넣는 패턴이 필요할 때
- `otel_data`, eval, stream 응답 제어를 실제 앱 경계에서 확인하고 싶을 때

## 대상 독자

- 이미 FastAPI 또는 Agent 앱을 가지고 있는 개발자
- SDK 기본 예제는 익혔고, 앱 통합 패턴이 필요한 사용자

입문 단계라면 먼저 다음 문서를 보세요:

- `example_sdk/README.md`

## Quick Start

가장 짧은 적용 순서:

1. `instrument_app(app)`를 추가합니다.
2. 프로세스를 `opentelemetry-instrument`로 기동합니다.
3. `/chat` 같은 최소 엔드포인트에서 응답에 `otel_data`가 포함되는지 확인합니다.

최소 적용 코드는 아래 `2. 최소 적용 코드` 섹션을 따르면 됩니다.

## Bootstrap Spec

이 예제의 startup artifact는 launcher와 `awx-bootstrap.json`에 반영되어 있습니다.

현재 manifest:

```json
{
  "credentials": [
    {
      "service_id": 30,
      "provider_alias": "OpenAI",
      "service_type_name": "LLM"
    }
  ],
  "external_resources": [
    {
      "provider_alias": "OpenAI",
      "solution_id": "BUILDER",
      "service_type_name": "LLM"
    }
  ]
}
```

이 manifest는 launcher에서 아래 SDK 호출과 같은 의미로 해석됩니다.

```python
from awx.resources import bootstrap_portal_runtime

bootstrap_portal_runtime(
    credential_requests=[
        {
            "service_id": 30,
            "provider_alias": "OpenAI",
            "service_type_name": "LLM",
        }
    ],
    external_resource_requests=[
        {
            "provider_alias": "OpenAI",
            "solution_id": "BUILDER",
            "service_type_name": "LLM",
        }
    ],
)
```

## 문서 읽는 법

- `Quick Start`: 가장 적은 코드로 SDK를 붙이는 방법
- `Advanced`: eval, stream, 응답 제어, 커스텀 capture 같은 고급 옵션
- 내부 구현 설명은 참고용이며, 사용자 코드는 공개 API 위주로만 유지하면 됩니다.

전제:
- 이 문서의 독자는 SDK 사용자(앱 개발자)입니다.
- SDK는 실행 환경에 이미 설치되어 있다고 가정합니다.
- SDK 내부 모듈 재배치와 무관하게, 사용자 코드는 `awx.observability.instrumentation.fastapi` 공개 API만 사용합니다.

## 1. 무엇이 자동화되나

기본 자동 수집(OTel):
- `opentelemetry-instrument`가 제공하는 HTTP/라이브러리 span, 기본 메트릭/로그 연동

SDK 추가 자동화(`instrument_app`):
- `X-AWX-Session-Id` 헤더를 span attribute(`awx.session.id`)로 자동 반영
- `X-AWX-OTEL-Include` 단일 헤더(`off|trace|metrics|logs|full`)로 응답 부가정보 제어
- `eval_auto` 설정 시 요청/응답 기반 평가 payload 자동 생성 및 emit

선택적 컨텍스트 주입:
- `awx_context_dependency()`는 세션 컨텍스트를 라우트에 연결합니다.
- 요청 body를 자동으로 읽어 메트릭을 반영하지 않습니다.

즉, **프로세스 자동 계측은 OTel**, **AWX 도메인 보강은 SDK**가 담당합니다.

## 1-1. 현재 예제 내부 구조 (SDK 정렬)

- LLM 호출은 `openai.AsyncOpenAI` 기반 어댑터(`OpenAIChatCompletionsAdapter`)를 통해 수행합니다.
- 채팅 오케스트레이션은 OpenAI SDK 네이밍에 맞춘 `ChatCompletionsService.create()`에서 처리합니다.
- AWX 연동은 `awx.resources.Credential.get()`(API key fallback), `awx.observability.session.get_session_id()`(MCP/stream 헤더) 중심으로 유지됩니다.
- startup resource cache는 앱 lifespan이 아니라 launcher와 `awx-bootstrap.json` manifest 계약이 준비합니다.
- OTel span 경계는 `chat_service`, `planner`, `llm_service`에 명시적으로 두어 추적 흐름이 SDK 구조와 맞게 드러납니다.

## 2. 최소 적용 코드 (사용자 앱)

아래 설정만으로 기본 자동화가 동작합니다.

```python
from fastapi import FastAPI
from pydantic import BaseModel

from awx.observability.instrumentation.fastapi import instrument_app

app = FastAPI()
# SDK 자동화 설정 (eval_dump/eval_auto는 from_env 기본값 사용)
instrument_app(app)

class ChatRequest(BaseModel):
    message: str
    stream: bool = False

@app.post("/chat")
async def chat(request: ChatRequest):
    return {"response": f"echo: {request.message}", "stream": request.stream}
```

핵심:
- SDK 사용자는 수동으로 span JSON을 조립할 필요가 없습니다.
- 앱 로직은 비즈니스 처리에 집중하고, 세션/평가 payload 생성은 SDK가 자동 처리합니다.
- `gen_ai.*` 비표준 보강은 필요할 때 SDK 함수로 명시적으로 적용합니다.

기존 OpenAI SDK 앱에 붙일 때(권장):
```python
from openai import AsyncOpenAI
from llm_service import configure_openai_client

openai_client = AsyncOpenAI(api_key="...")
configure_openai_client(client=openai_client, model="gpt-4o-mini")
```
- 이렇게 등록하면 AWX 예제 로직이 별도 API key 조회 코드 없이 기존 OpenAI client를 재사용합니다.
- `opentelemetry-instrumentation-openai`가 활성화된 프로세스에서 같은 `AsyncOpenAI`를 쓰면, OTel span/metric 수집 경로와 AWX 경로가 자연스럽게 정렬됩니다.

## 3. 실행 방식

프로세스는 반드시 `opentelemetry-instrument`로 기동합니다.

예:
```bash
uv run --env-file .env opentelemetry-instrument \
  uvicorn client:app --host 0.0.0.0 --port 8000
```

`instrument_app`는 OTel 자동 계측을 대체하지 않습니다. 둘 다 필요합니다.

`example_awx/flow` 기준 `make` 흐름:
```bash
cd /home/user/idea-project/container-script/example_awx/flow
make init app=fastapi-observability-auto.client
make test
make run
```

## 4. OTel JSON을 응답에 포함하는 방법

## Advanced

요청 헤더:
- `X-AWX-OTEL-Include: off|trace|metrics|logs|full`
- `trace/full`: 응답 `otel_data` + `captured_ended_spans` 포함
- `metrics/full`: 응답 `otel_data.captured_metrics`에 span 기반 메트릭 요약 포함
- `logs/full`: 응답 `otel_data.captured_logs`에 span event/status 기반 로그 요약 포함
- exporter 원본 payload(collector 전송본)와 응답 요약은 1:1 동일하지 않을 수 있음

예:
```bash
curl -X POST 'http://127.0.0.1:8000/chat' \
  -H 'Content-Type: application/json' \
  -H 'X-AWX-Session-Id: s-123' \
  -H 'X-AWX-OTEL-Include: trace' \
  -d '{"message":"hello"}'
```

그러면 응답에 `otel_data`가 포함됩니다.

### 평가 데이터 응답/파일 전달 (추가)

요청 헤더(기본):
- `X-AWX-Eval-Include: 0|1` (기본값 `0`, `1`이면 응답에 `evaluation_data` 포함)

요청 헤더(고급 override):
- `X-AWX-Eval-Dataset-Id: <dataset id>` (옵션)
- `X-AWX-OTEL-Include: off|trace|metrics|logs|full` (옵션, eval include on 시 기본 full)

`eval_auto`가 활성화되어 있고 dataset id가 결정되면(헤더 우선, 미지정 시 `AWX_EVAL_DATASET_ID`)
SDK가 평가 payload를 자동 생성/emit합니다.

`X-AWX-Eval-Dataset-Id` 또는 `AWX_EVAL_DATASET_ID`가 주어지면 SDK eval dump(`AWX_OTEL_EVAL_MODE=1`)에
평가 레코드가 `eval.jsonl`(`split_by_trace=1`이면 `eval/<trace_id>.jsonl`)로 기록됩니다.

`X-AWX-Eval-Include: 1` 또는 `AWX_EVAL_INCLUDE=1`이면 `/chat` 응답에 아래 필드가 추가됩니다:
- `evaluation_data.dataset_id`
- `evaluation_data.trace_id`
- `evaluation_data.trace_input` (사용자 입력)
- `evaluation_data.trace_output` (최종 출력)
- `evaluation_data.tool_usage` (tool 실행 step 목록)

추가 동작:
- eval include가 on이면(`X-AWX-Eval-Include=1` 또는 `AWX_EVAL_INCLUDE=1`)
  `X-AWX-OTEL-Include`를 따로 주지 않아도 SDK가 `full` 모드로 처리합니다.
- 기본 동작을 끄려면 `AWX_EVAL_FORCE_OTEL_FULL=0`을 설정합니다.

### Stream 응답 제어 (추가)

요청 바디 필드:
- `stream: true|false` (기본값 `false`)
- `true`이면 `/chat`은 OpenAI 스타일 SSE(`text/event-stream`) 응답을 반환합니다.
- SDK 예제는 `X-AWX-Eval-Include`, `X-AWX-OTEL-Include`를 자동으로 덮어쓰지 않습니다.
- 이 헤더 값은 사용자 요청/환경 설정을 그대로 따릅니다.
- `false`이면 기존 JSON 응답(`response`, `otel_data`, `evaluation_data`)을 반환합니다.

예:
```bash
curl -N -X POST 'http://127.0.0.1:8000/chat' \
  -H 'Content-Type: application/json' \
  -H 'X-AWX-Session-Id: s-123' \
  -H 'X-AWX-Eval-Include: 1' \
  -H 'X-AWX-Eval-Dataset-Id: ds-demo' \
  -d '{"message":"hello","stream":true}'
```

Stream + eval 동작 요약:
- stream(`stream=true`) + `X-AWX-Eval-Include=0`:
  - 응답은 실시간 `text/event-stream`(OpenAI chunk) stream
  - dataset id가 있으면 eval dump 파일 기록 가능
- stream(`stream=true`) + `X-AWX-Eval-Include=1`:
  - eval include 처리 때문에 응답 path가 버퍼링될 수 있음(실시간성 저하)
  - 응답이 SSE이므로 `evaluation_data` JSON 본문 주입은 불가
  - eval dump 파일 기록은 가능

### EvalAuto 커스텀 (권장)

앱의 요청/응답 스키마가 기본 경로(`message|trace_input|input`, `response|trace_output|output`)와 다르면
`EvalAutoConfig`를 커스텀해서 정확도를 높이세요.

```python
from dataclasses import replace
from awx.observability.instrumentation.fastapi import instrument_app, EvalAutoConfig
from awx.observability.instrumentation.eval_dump import EvalDumpConfig

base = EvalAutoConfig.from_env()
custom = replace(
    base,
    request_input_paths=("prompt", "question", "message", "trace_input"),
    response_output_paths=("answer", "result.text", "response", "trace_output"),
    response_tool_paths=("tools", "tool_execution", "tool_usage"),
    max_capture_bytes=512 * 1024,  # 기본 128KB
    max_text_chars=32 * 1024,      # 기본 8KB
)

instrument_app(
    app,
    eval_dump=EvalDumpConfig.from_env(),
    eval_auto=custom,
)
```

주의:
- 키 경로 미스매치 시 `trace_input/trace_output`이 raw body로 폴백될 수 있습니다.
- `max_capture_bytes`/`max_text_chars`를 넘으면 `...(truncated)`로 잘립니다.
- `logs` dump는 span event/status 기반 추출이므로, 이벤트가 없으면 로그 파일이 비거나 생성되지 않을 수 있습니다.

## 5. `gen_ai.*` 자동/수동 보강

자동 계측(OpenTelemetry instrumentations)에서 주로 들어오는 토큰 속성:
- `gen_ai.usage.input_tokens`
- `gen_ai.usage.output_tokens`
- `gen_ai.usage.total_tokens` (없을 수 있음)

SDK 응답(`captured_metrics`)에서는 토큰 타입 구분 키를 추가로 제공합니다:
- `gen_ai.client.token.usage.input`
- `gen_ai.client.token.usage.output`
- `gen_ai.client.token.usage.total`
- `gen_ai.client.token.usage` (호환용 total)

자동 계측에서 누락되는 항목은 사용자가 SDK 함수로 직접 보강합니다.

```python
from awx.observability.metrics import apply_user_metrics

apply_user_metrics(
    {
        "gen_ai.client.token.usage": 128,
        "gen_ai.client.operation.duration": 0.42,
    }
)
```

## 6. `instrument_app` vs `opentelemetry-instrument` 차이

`opentelemetry-instrument` 단독:
- 표준 자동 계측(span/metric/log) 중심
- AWX 도메인 헤더/요청 규약(`X-AWX-Session-Id`, `X-AWX-OTEL-Include`) 처리 없음

`instrument_app` 추가:
- AWX 규약 자동 반영(session id, 응답 내 `otel_data` 포함)
- `eval_auto`로 평가 payload 자동 생성/emit
- `awx_context_dependency()`로 세션 컨텍스트를 라우트에 연결(선택)
- 앱 코드에서 반복적인 수동 `set_attribute`/응답 조립 코드 감소

## 7. 자동 메트릭(`gen_ai.*`) 범위와 한계

대상 필드:
- `gen_ai.client.token.usage`
- `gen_ai.client.operation.duration`
- `gen_ai.server.time_to_first_token`
- `gen_ai.server.time_per_output_token`

원리(범용):
- 자동 계측 span attribute(`gen_ai.*`, `llm.usage.*`)를 기반으로 응답 메트릭을 집계
- token input/output/total은 자동 계측 값에서 파생하여 응답에 노출

한계:
- 공급자별 이벤트/토큰 필드가 다르면 TTFT/TPOT 정확도 편차가 발생할 수 있음
- 완전 자동 100% 보장은 불가하며, 모델/SDK 조합별 보정이 필요할 수 있음

## 8. Guardrail / Credential 메타데이터

SDK는 resource attributes에 안정적인 환경/서비스 식별자만 자동 반영합니다.

- `awx.service.id`
- `awx.project.id`
- `awx.env.type`
- `awx.platform.code`
- `awx.framework.type`

주의:
- `awx.credential.id`, `awx.ext.provider.id`, `awx.ext.service.id`, `awx.ext.service.type`는
  단일 trace/request 내에서도 호출별로 달라질 수 있으므로 resource attributes에 고정하지 않습니다.
  해당 값은 호출 단위 span/metric attribute로 다뤄야 합니다.

`awx.guardrail.filter.ids` 형식:
- JSON array string (예: `["2","6","10002","2","6","10002"]`)
- 정렬 없음, 원본 등장 순서 유지, 중복 유지

검색 가이드:
- 키 존재 검색: `awx.guardrail.filter.ids`
- 값 검색: 특정 `filterId` 포함 여부로 조회 (백엔드/도구 문법에 맞춰 contains 계열 연산 사용)

동작 방식:
- 추론(`DLP_RUN_MODE=INFER_ENV`): `PATH_MLDL_HOME/params/params.json` 파일 기반
- 개발: 포털 API 기반
  - `/sportal/v4/intapi/builder/flow/{flow_id}/filters`
  - `/sportal/v4/intapi/foundation/external_resources`

하위호환 API:

```python
from awx.observability.instrumentation import set_resource_lookup_options

set_resource_lookup_options(
    flow_id="40",
    user_id="1000001",
    provider_alias="OpenAI",
    service_type="SERVICE_TYPE_01",
)
```

현재 `set_resource_lookup_options()`와 `clear_resource_lookup_options()`는 deprecated no-op 입니다.
동적 guardrail/credential 값은 resource attribute가 아니라 span/metric attribute로 처리되므로,
새 코드에서는 이 API에 의존하지 않는 것이 맞습니다.

## 9. 필수/권장 환경 변수

필수:
- `awx.resources.Credential.get()`로 조회 가능한 OpenAI credential

### Service Name 정책

- 추론(`DLP_RUN_MODE=INFER_ENV`): `params.json`의 `infer_svc_id`가 기본값입니다.
- `OTEL_SERVICE_NAME`은 **`AWX_OTEL_SERVICE_NAME_OVERRIDE=1`일 때만** 허용됩니다.
- `OTEL_SERVICE_NAME`만 설정하고 override를 켜지 않으면 경고가 출력되며 무시됩니다.
- 개발 환경 기본값은 `MLDL_DEV_ID → APP_NAME` 순서로 사용됩니다.
- 개발에서도 `OTEL_SERVICE_NAME`은 override 없이 무시됩니다.
- 어떤 경로로도 service name을 얻지 못하면 에러가 발생합니다.

권장(OTLP 전송):
- 분석환경에서는 `OTEL_EXPORTER_OTLP_*`를 비워 두고 SDK 자동 감지를 사용
- custom collector override가 필요할 때만 `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`
- custom collector override가 필요할 때만 `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT`
- custom collector override가 필요할 때만 `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT`
- `OTEL_TRACES_EXPORTER=console,otlp`
- `OTEL_METRICS_EXPORTER=console,otlp`
- `OTEL_LOGS_EXPORTER=console,otlp`

주의:
- `OTEL_LOGS_EXPORTER=...,custom`은 custom exporter entry point가 없으면 실패할 수 있습니다.

평가용 원본 trace 덤프(선택, SDK):
- `AWX_OTEL_EVAL_MODE=1`
- `AWX_OTEL_EVAL_DUMP_DIR=/tmp/awx-otel-dump` (기본값)
- `AWX_OTEL_EVAL_SPLIT_BY_TRACE=1` 이면 trace_id별 파일 분리

평가 payload 자동화(선택, SDK):
- `AWX_EVAL_AUTO_MODE=1` (기본값: 활성, `0`이면 비활성)
- `AWX_EVAL_DATASET_ID=<dataset id>` (`X-AWX-Eval-Dataset-Id` 미지정 시 사용)
- `AWX_EVAL_INCLUDE=1` (`X-AWX-Eval-Include` 미지정 시 응답 포함 기본값으로 사용)
- `AWX_EVAL_FORCE_OTEL_FULL=1` (기본값: 활성, eval include on 시 `X-AWX-OTEL-Include=full` 강제)

덤프 파일 형식:
- 기본: `/tmp/awx-otel-dump/traces.jsonl`
- 기본: `/tmp/awx-otel-dump/metrics.jsonl`
- 기본: `/tmp/awx-otel-dump/logs.jsonl`
- 기본: `/tmp/awx-otel-dump/eval.jsonl`
- 분리 모드: `/tmp/awx-otel-dump/traces/<trace_id>.jsonl`
- 분리 모드: `/tmp/awx-otel-dump/metrics/<trace_id>.jsonl`
- 분리 모드: `/tmp/awx-otel-dump/logs/<trace_id>.jsonl`
- 분리 모드: `/tmp/awx-otel-dump/eval/<trace_id>.jsonl`
- 각 JSONL row에 `trace_id`, `session_id`, `payload` 포함
- `traces`는 `span.to_json` 계열 원본, `metrics/logs`는 span 기반 추출 요약입니다.

## 10. 자주 발생하는 오류

`ModuleNotFoundError: No module named 'awx'`
- 실행 venv에서 observability SDK가 제거된 상태입니다.
- `uv sync` 정책(특히 lock 기반)으로 preinstalled 패키지가 제거될 수 있으니 실행 정책을 점검하세요.

`OPENAI_API_KEY_MISSING`
- credential에서 키를 찾지 못하면 LLM 경로는 실패하도록 설계되어 있습니다.
- 의도된 실패이며, `awx.resources.Credential.get()` 경로를 설정해야 합니다.

## 11. 적용 체크리스트

- `instrument_app(app)` 적용
- Swagger 노출이 필요하면 `X-AWX-*` 헤더 파라미터 선언
- 프로세스를 `opentelemetry-instrument`로 기동
- 필요한 경우에만 OTLP endpoint override 설정
- 키/credential 설정 확인
