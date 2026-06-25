# AWX Observability MCP Server

AWX observability 예제의 MCP 서버입니다.

## 1. 실행 방법 (서버)
### Makefile 사용
```bash
cd /home/user/idea-project/container-script/example_awx/flow
make init app=fastapi-observability-auto
make run
```

### 개별 실행
```bash
cd /home/user/idea-project/container-script/example_awx/flow/example_app/fastapi-observability-auto/server
uv sync --inexact
uv run --env-file .env opentelemetry-instrument \
  uvicorn server:app --host 0.0.0.0 --port 8001
```

## 2. 주요 엔드포인트
- MCP SSE: `/mcp/sse`
- MCP 메시지: `/mcp/messages/`

클라이언트에서 기본으로 참조하는 서버 URL 예시:
- `MCP_SERVER_URL=http://127.0.0.1:8001/mcp/sse`

## 3. 환경 변수
`.env` 우선, 없으면 `.env.example` 사용.

권장 항목:
- `OTEL_TRACES_EXPORTER`, `OTEL_METRICS_EXPORTER`, `OTEL_LOGS_EXPORTER`
- custom collector override가 필요할 때만 `OTEL_EXPORTER_OTLP_*_ENDPOINT`

참고:
- `service.name`과 `awx.project.id`는 `.env`에서 직접 넣지 않고 SDK가 실행 환경 메타데이터로 계산합니다.
- 분석환경에서는 OTEL endpoint를 비워 두면 SDK가 collector endpoint를 자동 감지합니다.

`OTEL_LOGS_EXPORTER`는 `custom` 엔트리포인트 미구성 시 실패할 수 있으므로
`console,otlp`를 권장합니다.

## 4. 트러블슈팅
- `could not bind on any address`
  - 포트 점유 또는 실행 환경의 소켓 바인드 정책 문제
- OTLP `UNAVAILABLE`
  - custom collector override를 넣었다면 endpoint/방화벽/포트 확인
