# fastapi-credential-sdk-auto

이 예제는 `Credential.get()`으로 OpenAI credential을 해석하고 `/chat`에서 실제 LLM 호출까지 붙여 보는 FastAPI 샘플입니다.

## 이 예제를 먼저 볼 때

- AWX credential lookup을 FastAPI 앱에서 가장 작게 시작하고 싶을 때
- `ExternalResource`, MCP, guardrail 없이 credential만 먼저 확인하고 싶을 때
- secret 값 자체는 노출하지 않고 credential summary와 실제 chat 호출을 함께 확인하고 싶을 때
- startup cache 생성은 앱 코드가 아니라 flow launcher의 `make init` / `make run` 계약으로 맡기고 싶을 때

핵심 포인트:

- FastAPI 단일 서버
- `awx.resources.Credential.get()` 사용
- launcher가 `awx-bootstrap.json`을 보고 SDK credential cache artifact를 bootstrap
- `Credential.extract_secret_value()`로 secret 해석 여부만 확인
- `/chat`은 해석된 secret으로 OpenAI `chat.completions.create()` 호출
- 응답에는 secret 원문을 절대 포함하지 않음
- FastAPI 앱은 `awx.observability.instrumentation.fastapi.instrument_app(app)`로 계측
- 프로세스는 AWX SDK instrumentation이 반영된 상태에서 `opentelemetry-instrument`로 기동

## Quick Start

```bash
cd /home/user/idea-project/container-script/example_awx/flow
make init app=fastapi-credential-sdk-auto
make sync
make run
```

직접 실행:

```bash
cd /home/user/idea-project/container-script/example_awx/flow/example_app/fastapi-credential-sdk-auto
bash run_app.sh 127.0.0.1 8001
```

## Portal Bootstrap Example

이 예제의 startup artifact는 앱 코드가 아니라 launcher와 `awx-bootstrap.json`에 반영되어 있습니다.

현재 manifest:

```json
{
  "credentials": [
    {
      "service_id": 30,
      "provider_alias": "OpenAI",
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
    ]
)
```

즉, startup bootstrap 예제는 [portal_bootstrap_example.py](../../example_sdk/example_resources/portal_bootstrap_example.py)와 같은 SDK API를 쓰고, `example_app`에서는 그 스펙을 `awx-bootstrap.json`으로 선언하는 구조입니다.

## Runtime contract

이 예제는 credential summary 조회와 LLM chat 호출을 제공합니다.

- 기본 요청 값:
  - `service_id=30`
  - `provider_alias=OpenAI`
  - `service_type_name=LLM`
  - `model=gpt-4o-mini` (`OPENAI_MODEL` env로 override 가능)
- 필요하면 request body에서 다른 값을 넘길 수 있습니다.
- `/credential/summary` 응답은 선택된 credential의 id, tag, variable 이름 목록, secret 해석 성공 여부만 돌려줍니다.
- `/chat`은 선택된 credential secret으로 실제 LLM 응답 텍스트를 반환합니다.
- secret 원문은 응답에 포함하지 않습니다.
- `make init` 또는 `make run`이 먼저 실행되면 dev runtime에서는 SDK 기본 경로에 credential cache materialization이 먼저 일어날 수 있습니다.
- FastAPI 기동 시 AWX SDK `instrument_app(app)`를 적용합니다.
- 실행 스크립트는 `opentelemetry-instrument`로 프로세스를 시작합니다.

개발 환경에서는 `MLDL_USER_ID`, `MLDL_PROJ_ID` 같은 기본 런타임 메타데이터가 필요할 수 있습니다.

## 실제 구동 환경과 로컬 차이

- 실제 구동 기준은 builder/inference runtime이며, Portal runtime metadata와 AWX SDK 설치 상태가 함께 주입됩니다.
- 지금 저장소에서 확인하는 로컬 실행은 `make init`, `make run`, FastAPI 프로세스 기동, 기본 API 응답 확인 범위입니다.
- 실제 credential 선택 결과는 Builder/Portal에 등록된 credential, runtime metadata, service 매핑에 따라 달라집니다.
- 실제 환경 변수가 필요하면 저장소 값에 기대하지 말고 사용자/운영자에게 요청하세요.

## API

- `GET /`
- `GET /health`
- `POST /credential/summary`
- `POST /chat`

예시:

```bash
curl -sS -X POST 'http://127.0.0.1:8001/credential/summary' \
  -H 'Content-Type: application/json' \
  -d '{
    "service_id": 30,
    "provider_alias": "OpenAI",
    "service_type_name": "LLM",
    "tag": "gpt-4o-mini"
  }'
```

예상 응답:

```json
{
  "trace_id": "0123...",
  "service_id": 30,
  "provider_alias": "OpenAI",
  "service_type_name": "LLM",
  "credential_count": 1,
  "selected_credential_id": "7",
  "selected_tag": "gpt-4o-mini",
  "variable_names": ["OPENAI_API_KEY", "BASE_URL"],
  "secret_resolved": true
}
```

채팅 예시:

```bash
curl -sS -X POST 'http://127.0.0.1:8001/chat' \
  -H 'Content-Type: application/json' \
  -d '{
    "message": "안녕하세요. 한 줄로 자기소개해줘",
    "model": "gpt-4o-mini"
  }'
```

예상 응답:

```json
{
  "trace_id": "0123...",
  "assistant_message": "안녕하세요. 저는 간결하게 답하는 한국어 AI 도우미입니다.",
  "model": "gpt-4o-mini"
}
```
