# mcp-server-auto

Minimal MCP server example without any LLM dependency.

## Run (`make` workflow)

From `example_awx/flow`:

```bash
make init mcp-server-auto
make run
```

Default bind: `0.0.0.0:8000`

## Endpoints (default)

- MCP Streamable HTTP: `/mcp`
- Health: `/health`
- Swagger: `/docs`

## Tools

- `add(a: float, b: float) -> float`
- `subtract(a: float, b: float) -> float`
- `multiply(a: float, b: float) -> float`
- `divide(a: float, b: float) -> float`

## OTel

`run_server.sh` starts with `opentelemetry-instrument`.
In the analysis environment, you can leave `OTEL_EXPORTER_OTLP_*` empty and let the SDK detect the collector endpoint automatically.
