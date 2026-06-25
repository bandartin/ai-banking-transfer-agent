# vllm-sdk-auto

`vllm-sdk-auto`는 AWX external resource에서 custom model(vLLM) endpoint/model을 읽고, `Credential.get()`으로 secret을 받아 OpenAI-compatible client를 호출하는 AWX Flow 예제입니다.

## 이 예제를 먼저 볼 때

- `Credential.get()`와 `ExternalResource.get()`를 한 앱에서 같이 쓰고 싶을 때
- portal resource를 읽어 custom model(vLLM) endpoint에 연결하는 최소 패턴이 필요할 때
- tool-calling이나 HITL보다 resource integration 예제를 먼저 보고 싶을 때

핵심 포인트:

- FastAPI 단일 서버
- `/chat` 단일 엔드포인트
- `awx.resources.Credential.get()`로 API key 조회
- `awx.resources.ExternalResource.get()`로 vLLM endpoint/model 조회
- `provider_alias="Custom"`, `service_type_name="LLM"` 기준
- `awx.observability.instrumentation.fastapi.instrument_app(app)` 적용
- 프로세스는 `opentelemetry-instrument`로 기동

## Modes

- `server`: `FastAPI + vLLM(OpenAI-compatible) + AWX SDK resource lookup`

## Quick Start

```bash
cd /home/user/idea-project/container-script/example_awx/flow
make init app=vllm-sdk-auto
make sync
make run
```

직접 실행:

```bash
cd /home/user/idea-project/container-script/example_awx/flow/example_app/vllm-sdk-auto
cp .env.example .env
bash run_app.sh 127.0.0.1 8001
```

## Bootstrap Spec

이 예제의 startup artifact는 앱 코드가 아니라 launcher와 `awx-bootstrap.json`에 반영되어 있습니다.

현재 manifest:

```json
{
  "credentials": [
    {
      "service_id": 30,
      "provider_alias": "Custom",
      "service_type_name": "LLM"
    }
  ],
  "external_resources": [
    {
      "provider_alias": "Custom",
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
            "provider_alias": "Custom",
            "service_type_name": "LLM",
        }
    ],
    external_resource_requests=[
        {
            "provider_alias": "Custom",
            "solution_id": "BUILDER",
            "service_type_name": "LLM",
        }
    ],
)
```

## Portal runtime

이 예제는 portal resource를 읽어 custom model(vLLM) endpoint에 붙는 최소 패턴입니다.

- `Credential.get()`으로 API key를 조회합니다.
- `ExternalResource.get()`으로 endpoint/model을 조회합니다.
- 응답 요청마다 lookup 결과를 그대로 사용하고, 앱 코드에서 별도 resource attribute를 조립하지 않습니다.

## Runtime contract

이 예제는 환경 변수에서 직접 `OPENAI_API_KEY`를 받는 예제가 아니라, AWX SDK resource lookup 결과를 그대로 쓰는 예제입니다.

- credential source:
  `Credential.get(service_id=30, provider_alias="Custom", service_type_name="LLM")`
- resource source:
  `ExternalResource.get(provider_alias="Custom", solution_id=<platform_code>, service_type_name="LLM")`
- required resource fields:
  `endpoint` 또는 `baseUrl`, 그리고 `modelAlias` 또는 대체 model 필드
- platform fallback:
  `awx.common.config.PLATFORM_CODE` 우선, 없으면 `MLDL_PLATFORM_CODE` / `PLATFORM_CODE` / `BUILDER`

이 예제에서 사용자가 직접 고를 수 있는 값은 최소화했습니다.

- 요청 body의 `model`이 있으면 resource model 대신 우선 사용
- 그 외 endpoint/model/API key는 AWX SDK lookup 결과를 그대로 사용

## 실제 구동 환경과 로컬 차이

- 실제 구동 기준은 builder/inference runtime이며, Custom credential과 external resource는 Portal/Builder에 등록된 값을 SDK가 조회합니다.
- 지금 저장소에서 확인하는 로컬 실행은 `make init`, `make run`, FastAPI 프로세스 기동, 기본 `/chat` 경로 준비 여부 확인 범위입니다.
- 실제 vLLM endpoint/model 응답까지 보려면 해당 runtime에서 조회 가능한 Custom credential/resource가 준비되어 있어야 합니다.
- 실제 환경 변수가 필요하면 저장소 값에 기대하지 말고 사용자/운영자에게 요청하세요.

## API

- `POST /chat`
- `GET /health`
- `GET /`

`POST /chat` 예시:

```bash
curl -sS -X POST 'http://127.0.0.1:8001/chat' \
  -H 'Content-Type: application/json' \
  -d '{
    "message":"AWX SDK와 vLLM 연동 예시를 한 줄로 설명해줘"
  }'
```

예상 응답:

```json
{
  "trace_id": "0123...",
  "model": "resource model alias",
  "base_url": "http://your-vllm-endpoint/v1",
  "response": "..."
}
```

## OTel Endpoint Resolution

분석환경에서는 별도 OTEL endpoint를 적지 않아도 됩니다. SDK가 런타임에 주입된 collector endpoint를 자동 감지해 표준 exporter env로 bridge합니다.

- 사용자가 collector를 바꾸고 싶을 때만 `OTEL_EXPORTER_OTLP_*` override를 추가합니다.
- `instrument_app(app)`는 AWX 쪽 컨텍스트 보강을 담당합니다.
- `opentelemetry-instrument`는 FastAPI/OpenAI HTTP 호출 span을 전송합니다.
- 응답의 `trace_id`로 collector/Tempo/Grafana에서 추적을 이어서 확인하면 됩니다.
