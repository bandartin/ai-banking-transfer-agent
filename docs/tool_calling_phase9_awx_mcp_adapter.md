# Tool Calling Phase 9 AWX MCP Adapter

## Purpose

Phase 9 connects the Phase 8 external-tool boundary to the AWX MCP discovery
pattern used in the local AWX examples:

```text
Mcp().get()
  -> selected_server.get_client()
  -> client.list_tools()
  -> client.call_tool(name=..., arguments=...)
```

The adapter is disabled by default and fails closed.  MCP tool descriptions do
not decide side effects.  Application-owned allowlist configuration decides
which tools can be exposed and whether each tool is `read` or `prepare`.

## Runtime Flow

```text
tool_agent
  -> build_awx_mcp_external_tools(ctx)
  -> parse TOOL_CALLING_AWX_MCP_ALLOWLIST
  -> discover/select AWX MCP server
  -> list MCP tool schemas
  -> wrap allowlisted tools with external_tool_to_agent_tool
  -> run_langchain_tool_agent(..., external_tools=[...])
  -> _compose_model_tools
  -> _build_langchain_tools
  -> enforce_tool_policy + tool_audit_event + redact_tool_payload
```

If the AWX SDK is unavailable and the adapter is enabled, no MCP tools are
added.  If configuration is unsafe, such as an `execute` allowlist entry or a
missing selected server, the tool-agent path falls back to deterministic
handling instead of exposing the tool.

## Configuration

Keep disabled until the MCP server, tool list, and side effects are reviewed:

```env
TOOL_CALLING_AWX_MCP_ENABLED=false
TOOL_CALLING_AWX_MCP_ALLOWLIST=
```

Allowlist forms:

```env
TOOL_CALLING_AWX_MCP_ALLOWLIST={"awx_lookup_balance":"read"}
TOOL_CALLING_AWX_MCP_ALLOWLIST=awx_lookup_balance:read,awx_prepare_case:prepare
```

When several MCP servers are visible, select one explicitly:

```env
AWX_MCP_SERVER_NAME=banking-mcp
AWX_MCP_SERVICE_ID=svc-123
```

Server-prefixed allowlist keys are supported after selection:

```env
TOOL_CALLING_AWX_MCP_ALLOWLIST=banking-mcp.awx_lookup_balance:read
```

Only `read` and `prepare` are accepted.  `confirm` and `execute` are rejected
before LangChain sees the tool.

## AWX Bootstrap

For AWX rollout, set `prefetch_mcp=true` in `awx/awx-bootstrap.json` after the
MCP binding is approved.  The readiness script warns when the adapter is
enabled but the bootstrap manifest does not prefetch MCP metadata.

## Readiness

Run:

```powershell
uv run --with-requirements requirements.txt python scripts\check_awx_readiness.py --report .awx-evidence\tool_calling_readiness_report.json
```

The readiness check validates:

- `TOOL_CALLING_AWX_MCP_ENABLED`
- non-empty allowlist when enabled
- allowlist side effects limited to `read` and `prepare`
- AWX bootstrap MCP prefetch warning
- safe report output with allowlist count, not raw allowlist content

## Observability

Phase 9 adds manual spans around the AWX MCP boundary:

- `banking.awx_mcp.discovery`
- `banking.awx_mcp.tools.list`
- `banking.awx_mcp.tool.call`

Span attributes are limited to non-sensitive values such as allowlist count,
server id/name, and tool name.  Tool arguments and results continue to be
recorded only through masked `tool_audit_event` records.

## Verification

Run:

```powershell
uv run --with-requirements requirements.txt python -m pytest tests\test_tool_calling_phase9.py tests\test_integration_readiness.py -q
```

The tests use a fake AWX MCP resource and client to verify discovery, server
selection, allowlist parsing, LangChain execution, audit redaction, and disabled
mode behavior without requiring the real AWX SDK.

## Next Phase Candidate

Phase 10 should add operator-facing MCP inspection evidence:

- a command or endpoint that lists discovered MCP servers and allowlisted tools
- sanitized discovery output for release review
- explicit denial reasons for skipped MCP tools
- optional manual span attributes for MCP server id, tool name, and side effect
