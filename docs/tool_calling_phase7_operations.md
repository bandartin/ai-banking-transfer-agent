# Tool Calling Phase 7 Operations Evidence

## Purpose

Phase 7 makes rollout evidence and rollback behavior repeatable.  The goal is
not to add a new agent capability; it is to make the LangChain tool-calling
surface auditable when it moves from local validation to AWX operation.

## Readiness Report Artifact

Generate a sanitized readiness report before rollout and after any production
flag change:

```powershell
uv run --with-requirements requirements.txt python scripts\check_awx_readiness.py --report .awx-evidence\tool_calling_readiness_report.json
```

The report schema is `tool_calling_readiness_report.v1`.  It includes:

- UTC generation time
- git branch, HEAD, and dirty-worktree flag
- safe runtime flag values
- check summary counts
- sanitized check details

The report intentionally omits raw credential values and local Python paths.
`AWX_CREDENTIAL_SERVICE_ID` is represented only as present or missing.

## Evidence Acceptance Criteria

Before enabling transfer-prep tools, attach these artifacts to the deployment
record or release checklist:

- passing Phase 5 regression command output
- sanitized readiness report JSON
- one masked trace sample or trace export showing LangChain/tool spans
- one transfer-prep dry-run transcript that reaches HITL confirmation
- one cancellation or amount-revision transcript from the same path

## Masked Trace Sample

Use `docs/examples/tool_calling_masked_trace_sample.json` as the shape to check
against.  A valid trace export should show graph, LangChain, and tool boundary
spans, but it must not contain full prompts, responses, account numbers,
recipient identifiers, tokens, or secrets.

Expected trace boundaries:

- `banking.graph.node`
- `banking.route.decision`
- `banking.tool.call`
- `banking.hitl.confirmation`
- `banking.hitl.resume`

## Transfer-Prep Rollback Runbook

1. Disable only transfer-prep first:

   ```env
   TOOL_CALLING_TRANSFER_PREP_ENABLED=false
   ```

2. Restart the AWX application process.

3. Confirm read-only tool calling still works and transfer requests route to
   the deterministic `TransferAgent` flow.

4. If the issue is broader than transfer-prep, disable model-selected tools:

   ```env
   TOOL_CALLING_ENABLED=false
   ```

5. If tracing overhead or instrumentation behavior is the suspect, disable
   LangChain instrumentation:

   ```env
   LANGCHAIN_OTEL_INSTRUMENTATION_ENABLED=false
   ```

6. Keep this setting unchanged during the incident:

   ```env
   TRACELOOP_TRACE_CONTENT=false
   ```

7. Capture a new readiness report and the masked `tool_audit_events` from the
   failed request.

8. Re-enable flags in the reverse order only after the failing request has a
   regression test or explicit runbook note.

## MCP And External Tool Boundary Decision

Decision: any future MCP or external tool surface must pass through the same
policy and audit boundary as local registry tools.

Minimum contract for Phase 8:

- every external tool has a declared `side_effect`
- `read` is the only default side effect
- `prepare` requires `TOOL_CALLING_TRANSFER_PREP_ENABLED=true`
- `confirm` and `execute` are not model-callable
- tool arguments and results pass through `redact_tool_payload`
- audit records are emitted with `tool_audit_event`
- external service identifiers are logged, but endpoint secrets and payload
  content are not

Until that wrapper exists, do not expose MCP tools that can move money, mutate
banking state, or reveal customer-specific authoritative values outside the
existing guarded adapters.

## Next Phase

Phase 8 is documented in `docs/tool_calling_phase8_external_tools.md`.  It adds
the external tool wrapper contract and runner entrypoint for
`external_tools=[...]`.

Phase 9 is documented in `docs/tool_calling_phase9_awx_mcp_adapter.md` and
connects a concrete AWX MCP discovery adapter to this boundary.  The next
candidate is Phase 10: operator-facing MCP inspection evidence.
