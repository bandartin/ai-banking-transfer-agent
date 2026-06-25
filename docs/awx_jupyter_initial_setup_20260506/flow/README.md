# AWX Flow Examples

This directory contains two kinds of AWX learning materials:

- `example_sdk/`: beginner-first guides for using the AWX SDK itself
- `example_app/`: AWX SDK + OpenTelemetry instrumentation integration examples built with supported frameworks such as LangChain, LangGraph, MCP, FastAPI, and HITL patterns

## Usage

The workflow is managed via `make` commands.

### 1. Initialize an App
Select an app and optional mode (default: `server`).

```bash
# Initialize Server (Default) - Positional Argument Supported
make init guardrail-sdk-auto
# Or explicit argument
make init app=mcp-agent-sdk-auto.server

# Initialize Agent (Specific Mode)
make init mcp-agent-sdk-auto.agent
# Initialize Named App Mode
make init mcp-agent-sdk-auto.server
```

This sets the context in `.app_env`. No files are copied.

### 2. Check Current App
To see which app is currently initialized:
```bash
make which
# Output:
# APP_NAME=guardrail-sdk-auto
# APP_MODE=server
```

### 3. Sync Dependencies
Install dependencies for the selected app.

```bash
make sync
```

### 3. Run Application
Run the initialized app/mode.

```bash
make run
```

### OTel Endpoint Handling

In the analysis environment, example apps can leave `OTEL_EXPORTER_OTLP_*` empty. The SDK runtime bridge detects the injected collector endpoint automatically.
Set `OTEL_EXPORTER_OTLP_*` only when you want to override the collector explicitly.

---

## Metrics & Modes
- **Server Mode**: Runs the application backend (usually Port 8001).
- **Client Mode**: Runs the example client (usually Port 8000).

## Proxy Support (Swagger UI / Docs)
The platform automatically detects if you are running in a proxy environment (Code Server, JupyterHub) and configures the application to serve Swagger UI (`/docs`) correctly.

- **Auto-Detection**:
    - **VS Code**: Detects `VSCODE_PROXY_URI`.
    - **Jupyter**: Detects `JUPYTERHUB_SERVICE_PREFIX`.
- **Manual Configuration**:
    - You can manually override the proxy path by setting the directory:
      ```bash
      export ROOT_PATH="/proxy/8001"
      make run
      ```

## Recommended Learning Path

입문 경로:

1. `example_sdk/README.md`
2. `example_sdk/example_core/basic_core_usage.py`
3. `example_sdk/example_resources/credentials_example.py`
4. `example_sdk/example_resources/portal_bootstrap_example.py`
5. `example_sdk/example_observability/telemetry_example.py`
6. `example_sdk/example_resources/full_llm_app_example.py`

프레임워크 통합 예제:

1. `example_app/guardrail-sdk-auto`
2. `example_app/fastapi-credential-sdk-auto`
3. `example_app/vllm-sdk-auto`
4. `example_app/fastapi-observability-auto`
5. `example_app/langchain-agent-sdk-auto`
6. `example_app/mcp-agent-sdk-auto`
7. `example_app/langgraph-hitl-auto`

## Choose By Goal

목적별로 고르면 아래 기준이 가장 빠릅니다.

- Resource integration:
  `fastapi-credential-sdk-auto`, `vllm-sdk-auto`, `guardrail-sdk-auto`
- Observability:
  `example_sdk/example_observability/telemetry_example.py`, `example_sdk/example_observability/late_span_example.py`, `fastapi-observability-auto`
- Tool-calling agents:
  `langchain-agent-sdk-auto`, `mcp-agent-sdk-auto`
- Human in the loop:
  `langgraph-hitl-auto`
- MCP server minimum:
  `mcp-server-auto`

현재 저장소 문서는 `flow/example_sdk`, `flow/example_app` 구조를 기준으로 정리되어 있습니다. Confluence의 catalog/projects 분리 TO-BE와는 아직 동일하지 않으므로, 이 README는 현재 repo에서 무엇을 먼저 볼지 안내하는 문서로 읽으면 됩니다.

## Available Apps

| App Name | Description | Modes |
|----------|-------------|-------|
| `mcp-server-auto` | Minimal MCP server with OTel auto instrumentation (no LLM) | `server` |
| `fastapi-credential-sdk-auto` | Minimal FastAPI example that resolves AWX credential metadata safely | `server` |
| `fastapi-observability-auto` | FastAPI observability integration example | `server`, `client` |
| `langchain-agent-sdk-auto` | AWX SDK MCP discovery + LangChain tool-calling Agent + calculator MCP server | `agent`, `server` |
| `mcp-agent-sdk-auto` | AWX SDK MCP discovery + OpenAI tool-calling Agent + calculator MCP server | `agent`, `server` |
| `guardrail-sdk-auto` | Minimal guardrail SDK server example | `server` |
| `vllm-sdk-auto` | Minimal custom model(vLLM) + AWX SDK + OTel example | `server` |
| `langgraph-hitl-auto` | LangGraph question-based HITL chat UI with same-trace resume, steer, reasoning summary, file attachments, and model selection | `server` |

## Directory Structure
- `example_sdk/`: beginner-first learning path for public SDK APIs.
- `example_app/`: runnable application examples and integration references.
- `run-application.sh`: Main launcher script.
- `Makefile`: workflow orchestrator.

## Concurrent Execution
You can run multiple apps simultaneously by overriding arguments directly in the `make` command, bypassing the global `.app_env` context.

```bash
# Run 'fastapi-observability-auto' on port 8002
make run app=fastapi-observability-auto port=8002

# Run 'mcp-agent-sdk-auto' agent on port 8003
make run app=mcp-agent-sdk-auto mode=agent port=8003
```
