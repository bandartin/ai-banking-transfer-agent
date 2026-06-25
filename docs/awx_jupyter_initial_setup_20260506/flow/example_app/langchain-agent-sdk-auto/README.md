# langchain-agent-sdk-auto

`langchain-agent-sdk-auto`는 `mcp-agent-sdk-auto`와 같은 `agent/server` 포맷을 유지하면서, Agent 구현만 LangChain tool-calling으로 바꾼 AWX Flow 예제입니다.

## 이 예제를 먼저 볼 때

- MCP 기반 agent를 좀 더 일반적인 library 패턴으로 보고 싶을 때
- `StructuredTool`, `create_tool_calling_agent`, `AgentExecutor` 조합이 필요할 때
- `mcp-agent-sdk-auto`의 raw loop보다 LangChain wrapper 흐름이 더 익숙할 때

핵심 포인트:

- Agent는 `awx.resources.Mcp`를 사용해 `Mcp().get()`으로 portal의 MCP 목록을 읽습니다.
- startup artifact 준비는 앱 lifespan이 아니라 flow launcher와 `agent/awx-bootstrap.json` 계약이 담당합니다.
- 선택된 MCP server에 대해 `list_tools()`를 먼저 호출한 뒤, LangChain `StructuredTool`로 감쌉니다.
- Agent 실행은 `create_tool_calling_agent`와 `AgentExecutor`를 사용합니다.
- 이 예제는 planner flow가 아니라 실제 LangChain `tool-calling` 흐름입니다.
- Agent와 Server 모두 `awx.observability.instrumentation.fastapi.instrument_app(app)`를 적용하고, 프로세스는 `opentelemetry-instrument`로 기동합니다.
- MCP 호출 관측은 SDK/OTel 자동 계측에 맡기고, 예제 앱 코드는 별도 span/attribute를 직접 세팅하지 않습니다.

## Modes

- `agent`: `LangChain + OpenAI + AWX SDK` 기반 FastAPI Agent
- `server`: calculator MCP server (`add`, `subtract`, `multiply`, `divide`)

## Quick Start

서버:

```bash
cd example_awx/flow
make init app=langchain-agent-sdk-auto.server
make sync
make run
```

에이전트:

```bash
cd example_awx/flow
make init app=langchain-agent-sdk-auto.agent
make sync
make run
```

Agent API:

- `POST /chat`
- `GET /mcp/servers`
- `GET /health`

## Bootstrap Spec

이 예제의 startup artifact는 launcher와 `agent/awx-bootstrap.json`에 반영되어 있습니다.

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
  "prefetch_mcp": true,
  "mcp_env_fallback": true
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
    prefetch_mcp=True,
)
```

`mcp_env_fallback`은 launcher가 `MCP_SERVER_URL` 기반 local fallback cache 생성까지 같이 처리한다는 뜻입니다.

## Portal runtime

권장 경로는 portal-managed runtime에서 Agent가 `awx.resources.Mcp`로 available MCP 목록을 읽는 것입니다.

- portal/user/flow 같은 platform runtime 메타데이터는 AWX runtime과 SDK가 해석하는 컨텍스트입니다.
- SDK 사용자용 예제에서는 이 값을 `.env.example`에 다시 노출하지 않습니다.
- example app이 직접 받는 값은 app-level override만 남깁니다.

이 상태에서 Agent는 `Mcp().get()` 결과를 그대로 사용하고, `list_tools()`를 호출한 뒤 LangChain tool-calling Agent를 시작합니다.

## Local standalone

로컬에서 portal metadata 없이 빠르게 확인하고 싶다면 Agent `.env`에 아래 값만 넣으면 됩니다.

```bash
MCP_SERVER_URL=http://127.0.0.1:8001/mcp
```

이 경우 Agent는 SDK MCP cache path에 `mcp_info.json`을 만들고, 다시 `Mcp().get(force_refresh=True)`를 호출합니다. 단, 추론환경처럼 파일시스템이 read-only이면 파일 생성은 건너뛰고 portal discovery 경로만 사용합니다.

이 fallback 경로에서는 `MCP_SERVER_NAME`이 없어도 SDK가 기본 local 이름을 합성합니다. 여러 MCP server가 보이는 환경에서 특정 server를 고르고 싶을 때만 root `.env`에 `MCP_SERVER_NAME`을 둡니다.

## 실제 구동 환경과 로컬 차이

- 실제 구동 기준은 builder/inference runtime이며, Agent는 portal-managed MCP metadata와 AWX credential/resource lookup을 사용합니다.
- 지금 저장소에서 확인하는 로컬 실행은 `make init`, `make run`, agent/server 프로세스 기동, 기본 `/health`·`/chat` 경로 준비 여부 확인 범위입니다.
- 로컬 standalone 확인은 `MCP_SERVER_URL` 같은 fallback override를 쓰지만, 실제 환경에서는 portal metadata가 우선입니다.
- 실제 환경 변수가 필요하면 저장소 값에 기대하지 말고 사용자/운영자에게 요청하세요.

## OpenAI Credential

Agent의 OpenAI 키는 요청 시 `Credential().get()`으로 조회하고, startup cache 생성은 launcher manifest가 처리합니다.

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
    prefetch_mcp=True,
)
```

## LangChain 구성

- MCP `inputSchema`를 LangChain `StructuredTool`의 `args_schema`로 변환합니다.
- `create_tool_calling_agent`가 tool selection을 맡고, `AgentExecutor`가 intermediate step을 수집합니다.
- 응답 payload는 최소화하고, MCP 실행 상세는 trace에서 확인합니다.

## OTel 확인 포인트

- Agent HTTP request span
- `awx.sdk.mcp.tools.list` span
- `awx.sdk.mcp.tools.call` span
- OpenAI / LangChain span
- MCP Server FastAPI request span

이 예제에서 `awx.sdk.mcp.*` span은 앱 코드가 직접 만드는 것이 아니라 SDK observability 계층의 자동 패치/계측 결과입니다.

## OTel Endpoint Resolution

분석환경에서는 별도 OTEL endpoint를 적지 않아도 됩니다. SDK가 런타임에 주입된 collector endpoint를 자동으로 감지해 표준 exporter env로 bridge합니다.

- 사용자가 직접 collector를 바꾸고 싶을 때만 별도 override를 추가하면 됩니다.
- 표준 값이 이미 있으면 SDK는 그 값을 그대로 유지합니다.

상세 실행/환경 예시는 [agent/README.md](./agent/README.md), [server/README.md](./server/README.md)를 보면 됩니다.
