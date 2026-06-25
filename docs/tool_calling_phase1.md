# OpenAI Tool Calling Phase 1

## Scope

Phase 1 adds a LangChain tool-calling `tool_agent` for read-only banking work.
The default LLM path uses `langchain_openai.ChatOpenAI`, LangChain
`StructuredTool`, and `langchain.agents.create_agent`.  It can call:

- `get_balance_summary`
- `get_transfer_history`
- `get_recurring_transfers`
- `get_recipient_recommendations`
- `search_menu_catalog`
- `search_product_guide`
- `calculate_finance`

Transfer execution remains excluded.  Confirmation, OTP, and execution still run
through `TransferAgent` and its existing Human-in-the-Loop guardrails.

## Phase 2 Preview

Phase 2 adds transfer-preparation tools behind an explicit feature flag:

- `resolve_transfer_recipient`
- `prepare_transfer_summary`

These tools can resolve a registered recipient and build a pre-validated
transfer summary for human confirmation.  They cannot execute a transfer, and
`execute_transfer` is not registered as a model-callable tool.

## Phase 3 Handoff

Phase 3 connects a ready transfer-preparation result to the existing HITL path.
When `prepare_transfer_summary` returns `ready_for_confirmation`, `tool_agent`
does not answer as if the transfer is done.  It hands off to the parent
`transfer` node with:

- `sub_intent=confirm_prepared_transfer`
- `pending_transfer_data=<prepared summary>`
- `risk_assessment=<prepared risk assessment>`
- resolved recipient/favorite metadata for the execution request

The `TransferAgent` entry node detects this state and routes directly to the
existing `confirm` node.  The confirmation card, cancellation handling, amount
revision, OTP gate, idempotency key, and final execution stay owned by
`TransferAgent`.

## Phase 4 Policy And Audit

Phase 4 adds a small policy layer around every model-selected tool call:

- Active policy allows only `read` tools by default.
- When `TOOL_CALLING_TRANSFER_PREP_ENABLED=true`, policy also allows `prepare`
  tools.
- Tools with `confirm` or `execute` side effects are blocked even if a model
  asks for them.
- Tool-call records stored in graph state are audit-safe: account fields,
  recipient/favorite/source ids, tokens, and secrets are redacted.
- Full tool output is still sent back to the LangChain agent, but
  persisted/debug-facing `tool_calls` are masked records.

## Phase 4.5 LangChain And OTel Alignment

The team standard is now reflected in code:

- LangGraph node LLM calls use LangChain `ChatOpenAI` by default.
- `tool_agent` uses LangChain `StructuredTool` wrappers and `create_agent`.
- Raw OpenAI Responses API code remains available only as
  `run_openai_responses_tool_agent`, an adapter for exceptional cases.
- `opentelemetry-instrumentation-langchain` is installed and initialized on a
  best-effort basis when `LANGCHAIN_OTEL_INSTRUMENTATION_ENABLED=true`.
- `TRACELOOP_TRACE_CONTENT=false` is the default because banking prompts,
  responses, and tool outputs may contain account, recipient, or memo data.
- AWX execution continues to start with `opentelemetry-instrument` through
  `awx/run-application.sh`.

## Phase 5 Regression Harness

Phase 5 adds API-free regression coverage for the LangChain tool-calling path.
The tests use a fake LangChain chat model that supports `bind_tools`, so
`create_agent` can exercise real `StructuredTool` execution without calling
OpenAI.  The covered scenarios are:

- read-only balance tool call
- transfer-preparation happy path and HITL handoff
- transfer-preparation validation failure with no handoff
- audit event masking and side-effect policy behavior
- OTel content-capture default: `TRACELOOP_TRACE_CONTENT=false`

## Phase 6 Rollout Gate

Phase 6 turns the implementation into an operational rollout checklist.  The
readiness script now verifies the LangChain/OTel dependency pins,
`opentelemetry-instrument` AWX entrypoint, safe trace-content policy, and
transfer-prep rollout flags.  The detailed runbook lives in
`docs/tool_calling_phase6_rollout.md`.

## Phase 7 Operations Evidence

Phase 7 adds a sanitized readiness report artifact and operations runbook.
`scripts/check_awx_readiness.py --report <path>` writes
`tool_calling_readiness_report.v1` without raw credential values or local Python
paths.  The detailed runbook lives in
`docs/tool_calling_phase7_operations.md`, with a masked trace sample in
`docs/examples/tool_calling_masked_trace_sample.json`.

## Phase 8 External Tool Boundary

Phase 8 adds the safe adapter contract for AWX MCP or other external tools.
External tool metadata is converted into local `AgentTool` objects with
`external_tool_to_agent_tool`, and the runner accepts them through
`external_tools=[...]`.  Duplicate names, loose schemas, and `confirm` or
`execute` side effects fail closed before LangChain binding.  The detailed
contract lives in `docs/tool_calling_phase8_external_tools.md`.

## Phase 9 AWX MCP Adapter

Phase 9 connects the external tool boundary to AWX MCP discovery.  The
`tool_agent` calls `build_awx_mcp_external_tools(ctx)` and passes allowlisted MCP
tools into `run_langchain_tool_agent(..., external_tools=[...])`.  The adapter
is disabled by default, requires `TOOL_CALLING_AWX_MCP_ALLOWLIST`, and accepts
only `read` or `prepare` side effects.  The detailed runbook lives in
`docs/tool_calling_phase9_awx_mcp_adapter.md`.

## Runtime Flow

1. Supervisor creates its normal plan.
2. If every planned step is a Phase 1 read-only agent and OpenAI credentials are
   available, the plan is collapsed into one `tool_agent` step.
3. `tool_agent` wraps registry tools as LangChain `StructuredTool` objects.
4. The model selects tool calls.
5. Server code validates and executes the selected local tool handlers.
6. The policy layer blocks out-of-scope side effects and creates a masked audit
   event for each tool call.
7. Tool outputs are returned through LangChain for the final Korean answer.
8. If LangChain, credentials, or API calls fail, `tool_agent` falls back to the
   deterministic rule-plan/sub-agent path.
9. If a transfer-preparation tool result is ready for confirmation, `tool_agent`
   hands off to `TransferAgent.confirm` instead of producing a final answer.

## AWX Style Notes

The implementation follows the local AWX example tone:

- small runtime wrappers instead of large framework rewrites
- explicit credential/fallback boundaries
- no live side effects in the first tool-calling surface
- tool execution metadata is returned through `agent_activity`
- OpenTelemetry is added through `opentelemetry-instrument` plus targeted
  manual spans at graph and tool boundaries

## Configuration

```env
TOOL_CALLING_ENABLED=true
TOOL_CALLING_TRANSFER_PREP_ENABLED=false
OPENAI_TOOL_MODEL=gpt-4o-mini
TOOL_CALLING_MAX_STEPS=4
LANGCHAIN_OTEL_INSTRUMENTATION_ENABLED=true
TRACELOOP_TRACE_CONTENT=false
```

Tool calling only activates when `LLM_PROVIDER=openai` and a usable OpenAI
credential is resolved through AWX credentials or local environment fallback.
Transfer-preparation tool calling only activates when
`TOOL_CALLING_TRANSFER_PREP_ENABLED=true`.  Keep it disabled in production until
the transfer-prep HITL path has passed rollout checks.
