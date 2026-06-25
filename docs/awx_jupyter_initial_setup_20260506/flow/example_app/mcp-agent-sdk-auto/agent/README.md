# Agent Mode

이 Agent는 `awx.resources.Mcp`로 portal MCP 목록을 읽고, 선택된 server에 대해 `list_tools()`를 수행한 뒤 OpenAI tool-calling 루프를 실행합니다.

환경값 원칙:

- portal/user/flow runtime metadata는 AWX runtime + SDK가 처리합니다.
- example `.env.example`에는 local override만 남깁니다.
- local standalone으로 portal metadata 없이 확인할 때만 `MCP_SERVER_URL`을 사용합니다.
- `MCP_SERVER_NAME`은 여러 local target 중 하나를 고를 때만 선택적으로 둡니다.

요약 흐름:

1. `Mcp().get()`
2. target server 선택
3. `list_tools()`
4. OpenAI tool-calling
5. `call_tool()`
6. 최종 응답 반환

중요:

- planner/executor 예제가 아닙니다.
- startup cache 생성은 앱 코드가 아니라 launcher와 상위 `agent/awx-bootstrap.json` 계약이 담당합니다.
- `list_tools()`와 `tools/call`은 OTel span으로도 남깁니다.
- OpenAI API key는 `awx.resources.Credential.get()`으로 조회합니다.

## Bootstrap Spec

Agent startup의 bootstrap spec은 상위 [README](../README.md)에 있는 `agent/awx-bootstrap.json`과 동일합니다.

SDK 호출로 보면 다음과 같습니다.

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
