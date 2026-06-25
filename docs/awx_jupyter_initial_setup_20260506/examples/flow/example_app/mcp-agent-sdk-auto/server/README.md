# Server Mode

이 서버는 calculator MCP server입니다.

제공 도구:

- `add(a, b)`
- `subtract(a, b)`
- `multiply(a, b)`
- `divide(a, b)`

`divide`는 0으로 나누면 `ValueError`를 발생시켜 Agent가 오류를 관찰할 수 있게 합니다.
