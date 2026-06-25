"""Optional AWX/OpenTelemetry observability helpers."""

from __future__ import annotations

import datetime as _dt
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from src.awx_runtime.redaction import redact_text


@dataclass
class LLMCallRecord:
    """Mutable record populated by an LLM call site before logging."""

    operation: str
    model: str
    input_message: str
    output_message: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    token_usage: int | None = None
    status: str = "completed"
    error: str = ""


@contextmanager
def llm_call(ctx: Any, operation: str, input_message: str) -> Iterator[LLMCallRecord]:
    """Best-effort AWX LLMLog context manager."""
    model = str(getattr(ctx, "openai_model", "") or "")
    record = LLMCallRecord(
        operation=operation,
        model=model,
        input_message=redact_text(input_message),
    )
    start = _dt.datetime.now()
    started_at = time.monotonic()
    try:
        yield record
    except Exception as exc:
        record.status = "failed"
        record.error = redact_text(exc)
        raise
    finally:
        finish = _dt.datetime.now()
        elapsed_ms = max(1, int((time.monotonic() - started_at) * 1000))
        _send_llm_log(ctx, record, start, finish, elapsed_ms)


@contextmanager
def node_span(agent: str, node: str, state: dict | None = None) -> Iterator[None]:
    """Create an OTel span when instrumentation is available."""
    span_cm = _start_otel_span(f"banking.{agent}.{node}")
    if span_cm is None:
        yield
        return

    with span_cm as span:
        _safe_set_attribute(span, "agent.name", agent)
        _safe_set_attribute(span, "node.name", node)
        if state:
            _safe_set_attribute(span, "banking.intent", state.get("intent", ""))
            _safe_set_attribute(span, "banking.session.id", state.get("session_id", ""))
            _safe_set_attribute(span, "banking.user.id", state.get("user_id", ""))
        yield


@contextmanager
def manual_span(name: str, attributes: dict[str, Any] | None = None) -> Iterator[None]:
    """Create a lightweight manual OTel span with non-sensitive attributes."""
    span_cm = _start_otel_span(name)
    if span_cm is None:
        yield
        return

    with span_cm as span:
        for key, value in (attributes or {}).items():
            _safe_set_attribute(span, key, value)
        yield


def awx_info(message: str, *args: Any) -> None:
    """Write an info log through AWX Logger when present."""
    logger = _awx_logger()
    try:
        logger.info(message, *args)
    except Exception:
        return


def awx_warning(message: str, *args: Any) -> None:
    """Write a warning log through AWX Logger when present."""
    logger = _awx_logger()
    try:
        logger.warning(message, *args)
    except Exception:
        return


def initialize_langchain_instrumentation() -> None:
    """Best-effort LangChain OpenTelemetry instrumentation.

    The process should still be launched with `opentelemetry-instrument`; this
    helper only wires the LangChain-specific instrumentor when the dependency is
    available.  Prompt/response body capture is controlled by
    TRACELOOP_TRACE_CONTENT, which config.py defaults to false for banking data.
    """
    try:
        from opentelemetry.instrumentation.langchain import LangchainInstrumentor
    except Exception:
        return
    try:
        instrumentor = LangchainInstrumentor()
        if hasattr(instrumentor, "is_instrumented_by_opentelemetry") and instrumentor.is_instrumented_by_opentelemetry:
            return
        instrumentor.instrument()
    except Exception:
        return


def _send_llm_log(
    ctx: Any,
    record: LLMCallRecord,
    start: _dt.datetime,
    finish: _dt.datetime,
    elapsed_ms: int,
) -> None:
    try:
        from awx.observability import LLMLog, LogInput
    except Exception:
        return

    kwargs: dict[str, Any] = {
        "start_time": start.strftime("%Y-%m-%d %H:%M:%S.%f"),
        "finish_time": finish.strftime("%Y-%m-%d %H:%M:%S.%f"),
        "elapsed_time": elapsed_ms,
        "input_message": redact_text(record.input_message),
        "output_message": redact_text(record.output_message or record.error),
        "status": record.status,
        "custom01": f"operation:{record.operation}",
        "custom02": f"model:{record.model}",
    }
    for field in ("input_tokens", "output_tokens", "token_usage"):
        value = getattr(record, field)
        if isinstance(value, int):
            kwargs[field] = value

    try:
        LLMLog().log(LogInput(**kwargs))
    except Exception:
        return


def _start_otel_span(name: str):
    try:
        from opentelemetry import trace
    except Exception:
        return None
    try:
        return trace.get_tracer("ai-banking-transfer-agent").start_as_current_span(name)
    except Exception:
        return None


def _safe_set_attribute(span: Any, key: str, value: Any) -> None:
    try:
        if value is not None:
            span.set_attribute(key, value)
    except Exception:
        return


def _awx_logger() -> Any:
    try:
        from awx.core import Logger

        return Logger("BankingTransferAgent")
    except Exception:
        import logging

        return logging.getLogger("BankingTransferAgent")
