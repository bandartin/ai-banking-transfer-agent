# Calculator MCP Server

이 디렉터리는 `langchain-agent-sdk-auto` 예제에서 사용하는 calculator MCP server를 담고 있습니다.

제공 도구:

- `add`
- `subtract`
- `multiply`
- `divide`

FastMCP HTTP endpoint는 `/mcp`이고, trailing slash 없이도 `/mcp/` 요청을 허용하도록 canonical path middleware를 둡니다.
