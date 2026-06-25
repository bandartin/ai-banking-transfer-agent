# LangChain Agent

이 디렉터리는 `awx.resources.Mcp` discovery 결과를 LangChain `StructuredTool`로 감싸서 `create_tool_calling_agent` + `AgentExecutor`로 실행하는 FastAPI Agent를 담고 있습니다.

이 예제의 observability는 SDK/OTel 자동 계측 기준으로 맞춰져 있습니다. 앱 코드에서 별도 span이나 attribute를 직접 추가하지 않습니다.

주요 엔드포인트:

- `POST /chat`
- `GET /mcp/servers`
- `GET /health`

로컬 standalone 테스트 시에는 `.env`에 `MCP_SERVER_URL=http://127.0.0.1:8001/mcp`만 두면 됩니다. OpenAI 키는 `Credential().get()`으로만 조회합니다.
