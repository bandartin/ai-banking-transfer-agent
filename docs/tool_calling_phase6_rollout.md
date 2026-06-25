# Tool Calling Phase 6 Rollout Checklist

## Purpose

Phase 6 is the operational rollout gate for the LangChain tool-calling path.
The code path is already guarded by policy, audit masking, and HITL handoff.
This phase makes the rollout repeatable before AWX or production execution.

The operating style follows the AWX examples in
`docs/awx_jupyter_initial_setup_20260506/examples`:

- start the process with `opentelemetry-instrument`
- keep framework instrumentation explicit and small
- add manual spans around app-specific boundaries
- keep credential and fallback paths visible
- disable prompt/response content capture for banking data

## Required Defaults

```env
TOOL_CALLING_ENABLED=true
TOOL_CALLING_TRANSFER_PREP_ENABLED=false
TOOL_CALLING_MAX_STEPS=4
LANGCHAIN_OTEL_INSTRUMENTATION_ENABLED=true
TRACELOOP_TRACE_CONTENT=false
LLM_PROVIDER=openai
```

`TRACELOOP_TRACE_CONTENT=false` is mandatory for normal banking operation.
LangChain instrumentation can record prompt, response, and tool payload fields
when content capture is enabled, so content capture must stay disabled unless a
separate masked test environment is approved.

## Preflight Commands

Run the regression harness before changing rollout flags:

```powershell
uv run --with-requirements requirements.txt python -m pytest tests\test_agent.py tests\test_integration_readiness.py tests\test_tool_calling_phase1.py tests\test_tool_calling_phase5.py -q
```

Run the AWX readiness check:

```powershell
uv run --with-requirements requirements.txt python scripts\check_awx_readiness.py
```

Use strict mode for release gates when local AWX SDK availability is expected:

```powershell
uv run --with-requirements requirements.txt python scripts\check_awx_readiness.py --strict
```

## Rollout Stages

1. Baseline deterministic route
   - `TOOL_CALLING_ENABLED=false`
   - Confirm the existing supervisor, transfer HITL, OTP, and execution paths
     still work without any model-selected tools.

2. Read-only tool calling
   - `TOOL_CALLING_ENABLED=true`
   - `TOOL_CALLING_TRANSFER_PREP_ENABLED=false`
   - Validate read tools such as balance, transfer history, recurring transfer,
     product guide, and menu catalog search.
   - Confirm `agent_activity` contains masked tool-call audit records.

3. Transfer-prep dry run
   - `TOOL_CALLING_TRANSFER_PREP_ENABLED=true`
   - Keep `TRANSFER_EXECUTION_MODE=mock` or `dry_run`.
   - Validate that ready transfer-prep results hand off to
     `TransferAgent.confirm` and never answer as if money was sent.
   - Validate cancellation, amount revision, OTP, and idempotency behavior.

4. Restricted production
   - Keep transfer-prep enabled only after Phase 5 tests and dry-run HITL sign-off.
   - Keep `TRACELOOP_TRACE_CONTENT=false`.
   - Verify live mode uses `BANKING_ADAPTER=ibk` and valid AWX credential
     metadata.

## Observability Checks

Confirm these traces without storing prompt or response content:

- process entry from `awx/run-application.sh` through `opentelemetry-instrument`
- LangChain model/tool spans from `ChatOpenAI` and `StructuredTool`
- graph node spans for supervisor and sub-agent routing
- route decision spans for tool-agent fallback and transfer handoff
- HITL resume spans for confirmation and OTP continuation
- tool-call audit events with account, recipient, favorite, token, and secret
  fields redacted

## Fallback Switches

Use these flags in order when a rollout issue appears:

```env
TOOL_CALLING_TRANSFER_PREP_ENABLED=false
TOOL_CALLING_ENABLED=false
LANGCHAIN_OTEL_INSTRUMENTATION_ENABLED=false
```

Keep `TRACELOOP_TRACE_CONTENT=false` during fallback.  If raw OpenAI access is
ever needed for an exceptional case, use the adapter path only and keep the
LangChain `ChatOpenAI` path as the default graph LLM surface.

## Next Phase

Phase 7 is documented in `docs/tool_calling_phase7_operations.md` and focuses
on operator evidence:

- capture a sanitized AWX readiness report artifact
- add an example masked trace screenshot or exported trace payload
- add a small runbook for transfer-prep rollback and incident triage
- decide whether MCP/tool server boundaries need the same policy and audit
  wrappers as local registry tools

Phase 8 is documented in `docs/tool_calling_phase8_external_tools.md`, and
Phase 9 is documented in `docs/tool_calling_phase9_awx_mcp_adapter.md`.  The
next implementation candidate is Phase 10: operator-facing MCP inspection
evidence.
