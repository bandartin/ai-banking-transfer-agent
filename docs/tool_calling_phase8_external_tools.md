# Tool Calling Phase 8 External Tool Boundary

## Purpose

Phase 8 adds the boundary for AWX MCP or other external tools.  External tools
are not passed directly to LangChain.  They are first converted into the local
`AgentTool` contract by `external_tool_to_agent_tool`, then the existing runner
applies side-effect policy, audit events, and redaction.

This keeps one model-callable tool path:

```text
external metadata or MCP tool
  -> ExternalToolSpec
  -> external_tool_to_agent_tool
  -> AgentTool
  -> run_langchain_tool_agent(..., external_tools=[...])
  -> _compose_model_tools
  -> _build_langchain_tools
  -> enforce_tool_policy + tool_audit_event + redact_tool_payload
```

## Contract

Every external tool must declare:

- `name`: 1-64 letters, numbers, underscores, or hyphens
- `description`: non-empty model-facing description
- `parameters`: JSON object schema with `additionalProperties=false`
- `side_effect`: one of `read`, `prepare`, `confirm`, `execute`
- `source`: non-secret source label such as `awx_mcp`

Only `read` and `prepare` can become model-callable.  `confirm` and `execute`
are rejected before exposure.  `prepare` tools are included only when
`TOOL_CALLING_TRANSFER_PREP_ENABLED=true` and the runner is called with
`allow_transfer_prep=True`.

## Example

```python
from src.agents.tool_calling.external import ExternalToolSpec, external_tool_to_agent_tool

tool = external_tool_to_agent_tool(
    ExternalToolSpec(
        name="awx-mcp-balance",
        description="Read a masked balance view from an external service.",
        source="awx_mcp",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "lookup key"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    lambda runtime, args: {
        "kind": "external_balance",
        "text": "external lookup complete",
        "data": {"customer_account": "111-222-3333", "available_amount": 100000},
        "source_agent": "awx_mcp",
    },
)
```

The raw tool result can still be returned to the model, but persisted audit
records pass through `redact_tool_payload`.  Account, recipient, token, secret,
and password-like fields are masked before they appear in graph state or UI
metadata.

## Failure Behavior

The wrapper fails closed:

- unsupported names are rejected
- empty descriptions are rejected
- loose schemas with `additionalProperties=true` are rejected
- unknown side-effect values are rejected
- `confirm` and `execute` side effects are rejected before LangChain binding
- duplicate tool names are rejected by the runner

If an external `prepare` tool is configured while transfer-prep is disabled, it
is omitted from the model-callable tool list.  This mirrors the local transfer
preparation tools, which are absent unless the explicit feature flag is enabled.

## AWX MCP Integration Notes

Phase 8 defined the safe adapter surface.  Phase 9 connects that surface to AWX
MCP discovery in `src/agents/tool_calling/awx_mcp.py`:

1. discover MCP metadata through the AWX runtime or cached startup artifact
2. map each approved MCP tool to `ExternalToolSpec`
3. assign a side-effect from an allowlist maintained in application code
4. wrap the MCP client call as the `caller`
5. pass wrapped tools to `run_langchain_tool_agent(..., external_tools=tools)`

Do not infer side effects from model text.  The application must own the
side-effect allowlist, especially for banking workflows.

## Verification

Run:

```powershell
uv run --with-requirements requirements.txt python -m pytest tests\test_tool_calling_phase8.py -q
```

The test suite verifies read-tool execution, audit masking, execute-tool
rejection, transfer-prep gating, duplicate-name rejection, and strict schema
enforcement.

## Next Phase

Phase 9 is documented in `docs/tool_calling_phase9_awx_mcp_adapter.md`.  The
next implementation candidate is Phase 10: add operator-facing MCP inspection
evidence for discovered servers, allowlisted tools, and skipped-tool denial
reasons.
