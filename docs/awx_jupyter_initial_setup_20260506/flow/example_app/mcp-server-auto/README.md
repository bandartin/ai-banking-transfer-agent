# mcp-server-auto

LLM 의존성 없이 calculator MCP server만 가장 작게 보여 주는 예제입니다.

## 이 예제를 먼저 볼 때

- MCP server 최소 형태만 먼저 확인하고 싶을 때
- Agent 없이 `make init`, `make run` 흐름이 되는 server 예제가 필요할 때
- OTel 자동 계측이 붙은 FastMCP HTTP endpoint를 보고 싶을 때

## Quick Start

```bash
cd /home/user/idea-project/container-script/example_awx/flow
make init app=mcp-server-auto
make sync
make run
```

상세 route와 tool 목록은 [server/README.md](./server/README.md)를 보면 됩니다.

## 실제 구동 환경과 로컬 차이

- 실제 구동 기준은 builder/inference runtime이며, collector endpoint와 runtime metadata는 플랫폼이 주입합니다.
- 지금 저장소에서 확인하는 로컬 실행은 `make init`, `make run`, MCP server 프로세스 기동, `/mcp`와 `/health` 준비 여부 확인 범위입니다.
- 이 예제는 수동 env 의존이 작지만, 운영과 동일한 collector/metadata는 로컬 기본값과 다를 수 있습니다.
- 실제 환경 변수가 필요하면 저장소 값에 기대하지 말고 사용자/운영자에게 요청하세요.
