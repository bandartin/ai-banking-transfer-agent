# AWX SDK Examples

이 디렉터리는 AWX SDK를 처음 접하는 사용자를 위한 입문 경로입니다. 앱 전체를 띄우기 전에, 공개 SDK API를 짧은 예제로 먼저 익히는 것을 목표로 합니다.

`example_sdk`는 SDK 사용법 자체를 설명하고, `example_app`는 그 SDK를 LangChain, LangGraph, MCP, FastAPI, OpenTelemetry instrumentation 같은 프레임워크와 함께 통합하는 예제를 담당합니다.

## Quick Start

가장 빠른 추천 순서:

1. `python example_core/basic_core_usage.py`
2. `python example_resources/credentials_example.py`
3. `python example_resources/portal_bootstrap_example.py`
4. `python example_resources/prompt_example.py`
5. `python example_observability/telemetry_example.py`
6. `python example_resources/full_llm_app_example.py`

## 언제 example_app 로 넘어가나

아래 질문에 해당하면 `example_sdk` 다음 단계로 `example_app`를 보면 됩니다.

- 공개 SDK API 설명보다 실제 FastAPI 앱 통합 예제가 필요한가
- OpenTelemetry instrumentation과 함께 동작하는 전체 실행 예제가 필요한가
- LangChain, LangGraph, MCP, HITL 같은 framework 위에서 AWX SDK를 쓰는 패턴이 필요한가

## Example Categories

### Core Basics

- `example_core/basic_core_usage.py`

배우는 것:
- `awx.core.Logger`
- `awx.core.Config`

### Resource Basics

- `example_resources/credentials_example.py`
- `example_resources/prompt_example.py`
- `example_resources/external_resources_example.py`
- `example_resources/portal_bootstrap_example.py`
- `example_resources/guardrail_example.py`
- `example_resources/mcp_example.py`

배우는 것:
- `Credential.get(...)`
- `Prompt.list()`
- `ExternalResource.get(...)`
- `bootstrap_portal_runtime(...)`
- `Guardrail.get_policies()`, `Guardrail.apply(...)`, `Guardrail.check(...)`
- `Mcp.get()`, `McpWrapper.find(...)`

### Observability Basics

- `example_observability/telemetry_example.py`
- `example_observability/metering_example.py`
- `example_observability/llm_log_example.py`
- `example_observability/example_infer_collector.py`
- `example_observability/late_span_example.py`

배우는 것:
- `Tracer.trace(...)`
- `Metering.collect(...)`
- `LLMLog.log(...)`
- `InferenceCollector` callback pattern
- `trace_id` / `root span_id` 저장 후 later child span 추가

### End-to-End Minimal

- `example_resources/full_llm_app_example.py`

이 파일이 대표 통합 예제입니다. `core + resources + observability`를 하나의 흐름에서 보여줍니다.
runtime/config 기본값을 우선 사용하도록 구성되어 있으므로, 복사 시작점으로도 적합합니다.

### Advanced / App Integration

- `example_resources/filter_sdk_observability_example.py`
- `../example_app/guardrail-sdk-auto`
- `../example_app/vllm-sdk-auto`
- `../example_app/fastapi-observability-auto`
- `../example_app/langchain-agent-sdk-auto`
- `../example_app/mcp-agent-sdk-auto`
- `../example_app/langgraph-hitl-auto`

이 경로는 입문 다음 단계입니다. 단일 SDK API 설명보다 프레임워크 통합, 스트림 필터링, OTel 연동, agent/HITL 패턴에 초점을 둡니다.

## Environment Notes

- 일부 resources 예제는 개발 모드에서 `MLDL_USER_ID`, `MLDL_PROJ_ID`가 필요합니다.
- 일부 observability 예제는 collector가 없어도 실행되지만, 실제 전송은 실패하거나 no-op일 수 있습니다.
- `example_app/` 계열은 분석환경에서 `OTEL_EXPORTER_OTLP_*`를 비워 두면 SDK가 collector endpoint를 자동 감지합니다.
- `guardrail-sdk-auto` 앱 예제는 `OPENAI_API_KEY`가 필요합니다.
- `vllm-sdk-auto` 앱 예제는 `VLLM_BASE_URL`과 `VLLM_MODEL`이 필요합니다.

## Common Failures

- `userId is mandatory`:
  `MLDL_USER_ID`가 빠졌습니다.
- `project_id` 또는 prompt 조회 실패:
  `MLDL_PROJ_ID` 또는 프로젝트 접근 권한을 확인하세요.
- guardrail 정책 조회 실패:
  `GENAI_TEXT_FLOW_ID`와 Builder 정책 접근을 확인하세요.
- MCP 목록이 비어 있음:
  flow에 MCP가 연결되지 않았거나 inference cache가 없습니다.

## What To Read Next

목적별 추천:

- Resource integration:
  `../example_app/vllm-sdk-auto/README.md`
- Observability:
  `example_observability/telemetry_example.py`, `example_observability/late_span_example.md`, `../example_app/fastapi-observability-auto/client/README.md`
- Tool-calling agents:
  `../example_app/langchain-agent-sdk-auto/README.md`, `../example_app/mcp-agent-sdk-auto/README.md`
- Human in the loop:
  `../example_app/langgraph-hitl-auto/README.md`

- 스트림 guardrail과 trace 경계:
  `../example_app/guardrail-sdk-auto/README.md`
- custom model(vLLM) + AWX SDK + OTel 최소 연동:
  `../example_app/vllm-sdk-auto/README.md`
- 기존 FastAPI 앱에 observability 붙이기:
  `../example_app/fastapi-observability-auto/client/README.md`
- `awx.resources.Mcp`로 portal MCP 목록을 읽고 `list_tools()` 결과를 LangChain `StructuredTool`로 감싸 `create_tool_calling_agent` + `AgentExecutor`를 붙이는 예제:
  `../example_app/langchain-agent-sdk-auto/README.md`
- `awx.resources.Mcp`로 portal MCP 목록을 읽고 `list_tools()`를 추적한 뒤 OpenAI tool-calling Agent를 붙이는 예제:
  `../example_app/mcp-agent-sdk-auto/README.md`
- `trace_id`와 `root span_id`를 저장해 두었다가 나중에 late span 추가:
  `example_observability/late_span_example.py`, `example_observability/late_span_example.md`
- LangGraph 질문형 Human-in-the-Loop, same-trace resume, steer, reasoning summary, file/model UI 확인:
  `../example_app/langgraph-hitl-auto/README.md`
