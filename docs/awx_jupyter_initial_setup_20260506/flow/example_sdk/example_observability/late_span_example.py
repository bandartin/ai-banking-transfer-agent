"""
Learn a late-span trace continuity pattern.
Prerequisite: basic OpenTelemetry concepts.
This example stores a root trace/span id and appends a later child span.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, HTTPException
from opentelemetry import trace
from opentelemetry.trace import (
    NonRecordingSpan,
    SpanContext,
    TraceFlags,
    TraceState,
    set_span_in_context,
)
from pydantic import BaseModel


TRACER = trace.get_tracer(__name__)


def _trace_id_hex(span_context: SpanContext) -> str:
    return f"{span_context.trace_id:032x}"


def _span_id_hex(span_context: SpanContext) -> str:
    return f"{span_context.span_id:016x}"


def _context_from_saved_ids(trace_id: str, span_id: str) -> Any:
    parent = SpanContext(
        trace_id=int(trace_id, 16),
        span_id=int(span_id, 16),
        is_remote=True,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
        trace_state=TraceState(),
    )
    return set_span_in_context(NonRecordingSpan(parent))


@dataclass
class StoredTrace:
    session_id: str
    trace_id: str
    root_span_id: str
    events: list[dict[str, str]] = field(default_factory=list)


class StartTraceRequest(BaseModel):
    session_id: str
    label: str = "start"


class AddLateSpanRequest(BaseModel):
    session_id: str
    label: str = "late-span"


app = FastAPI(title="OTel Late Span Example")
TRACE_STORE: dict[str, StoredTrace] = {}


def _instrument_app() -> None:
    try:
        from awx.observability.instrumentation.fastapi import instrument_app

        instrument_app(app)
    except Exception:
        pass


@app.post("/trace/start")
async def start_trace(request: StartTraceRequest) -> dict[str, str]:
    with TRACER.start_as_current_span("otel.late_span.root") as span:
        span_context = span.get_span_context()
        trace_id = _trace_id_hex(span_context)
        root_span_id = _span_id_hex(span_context)
        span.set_attribute("late_span.session_id", request.session_id)
        span.set_attribute("late_span.step", "root")
        span.add_event("trace.started", {"label": request.label})
        TRACE_STORE[request.session_id] = StoredTrace(
            session_id=request.session_id,
            trace_id=trace_id,
            root_span_id=root_span_id,
            events=[
                {
                    "kind": "start",
                    "label": request.label,
                    "trace_id": trace_id,
                    "span_id": root_span_id,
                }
            ],
        )
        return {
            "session_id": request.session_id,
            "trace_id": trace_id,
            "root_span_id": root_span_id,
            "label": request.label,
        }


@app.post("/trace/add-span")
async def add_late_span(request: AddLateSpanRequest) -> dict[str, str]:
    stored = TRACE_STORE.get(request.session_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="session_id not found")

    parent_context = _context_from_saved_ids(stored.trace_id, stored.root_span_id)
    with TRACER.start_as_current_span("otel.late_span.followup", context=parent_context) as span:
        span_context = span.get_span_context()
        span_id = _span_id_hex(span_context)
        span.set_attribute("late_span.session_id", request.session_id)
        span.set_attribute("late_span.step", "followup")
        span.set_attribute("late_span.parent_span_id", stored.root_span_id)
        span.add_event("trace.followup_added", {"label": request.label})
        event = {
            "kind": "late_span",
            "label": request.label,
            "trace_id": stored.trace_id,
            "span_id": span_id,
            "linked_parent_span_id": stored.root_span_id,
        }
        stored.events.append(event)
        return {
            "session_id": request.session_id,
            "trace_id": stored.trace_id,
            "span_id": span_id,
            "linked_parent_span_id": stored.root_span_id,
            "label": request.label,
        }


@app.get("/trace/state/{session_id}")
async def get_trace_state(session_id: str) -> dict[str, Any]:
    stored = TRACE_STORE.get(session_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="session_id not found")
    return {
        "session_id": stored.session_id,
        "trace_id": stored.trace_id,
        "root_span_id": stored.root_span_id,
        "events": list(stored.events),
    }


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Store a trace id and add a late span later."}


def main() -> None:
    print("=== AWX Observability - Late Span Example ===")
    print("Run this module with a FastAPI server or import its handlers in tests.")
    print("Endpoints: /trace/start, /trace/add-span, /trace/state/{session_id}")


_instrument_app()


if __name__ == "__main__":
    main()
