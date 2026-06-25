from __future__ import annotations

from opentelemetry import trace


def _trace_id() -> str:
    span_context = trace.get_current_span().get_span_context()
    if span_context is not None and getattr(span_context, "is_valid", False):
        return f"{span_context.trace_id:032x}"
    return ""
