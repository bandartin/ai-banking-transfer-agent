# fastapi-observability-auto

기존 FastAPI 앱에 AWX observability SDK를 붙이는 `client/server` 예제입니다.

## 이 예제를 먼저 볼 때

- 기존 앱에 `instrument_app(app)`를 붙이는 최소 통합 패턴이 필요할 때
- observability client와 MCP server를 분리해서 실행 흐름을 보고 싶을 때
- `otel_data`, eval, stream 제어를 실제 앱 경계에서 확인하고 싶을 때

## Modes

- `client`: observability가 붙은 FastAPI client 앱
- `server`: observability 예제에서 호출하는 MCP server

## Quick Start

```bash
cd /home/user/idea-project/container-script/example_awx/flow
make init app=fastapi-observability-auto.client
make sync
make run
```

서버를 같이 보려면:

```bash
cd /home/user/idea-project/container-script/example_awx/flow
make init app=fastapi-observability-auto.server
make sync
make run
```

상세 설명은 [client/README.md](./client/README.md), [server/README.md](./server/README.md)를 보면 됩니다.

## 실제 구동 환경과 로컬 차이

- 실제 구동 기준은 builder/inference runtime이며, collector endpoint, runtime metadata, AWX SDK 설치 상태가 플랫폼에서 주입됩니다.
- 지금 저장소에서 확인하는 로컬 실행은 `make init`, `make run`, client/server 프로세스 기동, 기본 observability route 응답 확인 범위입니다.
- 로컬에서 실제 exporter나 eval 결과를 운영과 동일하게 보려면 collector override와 runtime metadata가 따로 필요할 수 있습니다.
- 실제 환경 변수가 필요하면 저장소 값에 기대하지 말고 사용자/운영자에게 요청하세요.
