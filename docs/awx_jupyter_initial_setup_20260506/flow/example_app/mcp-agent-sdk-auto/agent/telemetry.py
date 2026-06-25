from __future__ import annotations

from opentelemetry import trace


SERVICE_NAME = "mcp-agent-sdk-auto.agent"


def _resolve_service_name() -> str:
    try:
        provider = trace.get_tracer_provider()
        resource = getattr(provider, "resource", None)
        if resource is not None:
            candidate = resource.attributes.get("service.name")
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    except Exception:
        pass
    return SERVICE_NAME


def _trace_id() -> str:
    span = trace.get_current_span()
    context = span.get_span_context()
    return f"{context.trace_id:032x}" if context is not None and context.is_valid else ""


def _trace_mcp_operation(
    operation: str,
    *,
    server_name: str,
    endpoint: str,
    func,
    tool_name: str | None = None,
):
    tracer = trace.get_tracer(SERVICE_NAME)
    with tracer.start_as_current_span(f"awx.sdk.mcp.{operation}") as span:
        if hasattr(span, "set_attribute"):
            span.set_attribute("mcp.operation", operation)
            span.set_attribute("mcp.server.name", server_name)
            span.set_attribute("mcp.server.endpoint", endpoint)
            if tool_name:
                span.set_attribute("mcp.tool.name", tool_name)
        try:
            return func()
        except Exception as exc:
            if hasattr(span, "set_attribute"):
                span.set_attribute("error.type", type(exc).__name__)
                span.set_attribute("error.message", str(exc))
            if hasattr(span, "record_exception"):
                span.record_exception(exc)
            raise
