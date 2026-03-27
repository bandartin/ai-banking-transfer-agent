"""
run_logger.py — per-node execution logging for the transfer agent.

Uses a ContextVar so that each graph invocation has its own isolated log list,
even in a multi-threaded Flask server.

Usage in graph.py:
    from .run_logger import wrap_node, begin_run, end_run

    wrapped = wrap_node("classify_intent", classify_intent_node)

    # inside run_transfer_agent():
    token, entries = begin_run()
    result = graph.invoke(state)
    logs = end_run(token)       # -> list[NodeLogEntry]
"""

from __future__ import annotations

import time
from contextvars import ContextVar
from typing import Any, Callable

# ContextVar holds the list of log entries for the current graph invocation.
_run_entries: ContextVar[list | None] = ContextVar("run_entries", default=None)

# State fields worth capturing on the input side of each node
_INPUT_FIELDS = [
    "current_message",
    "intent",
    "pending_state",
    "recipient_alias",
    "amount",
    "memo",
    "use_last_transfer",
    "recurring_hint",
    "otp_code",
    "resolved_recipient_id",
    "resolved_favorite_id",
    "is_ambiguous",
    "candidate_recipients",
    "validation_passed",
    "validation_errors",
    "validation_warnings",
    "transfer_executed",
    "response_type",
    "response_text",
]


def begin_run() -> tuple:
    """Start a new run log.  Returns (token, entries_list)."""
    entries: list = []
    token = _run_entries.set(entries)
    return token, entries


def end_run(token) -> list:
    """Finish the run log and reset the ContextVar. Returns log entries."""
    entries = _run_entries.get() or []
    _run_entries.reset(token)
    return entries


def wrap_node(name: str, fn: Callable) -> Callable:
    """
    Return a wrapped version of *fn* that appends a NodeLogEntry to the
    current run's log list before returning.
    """

    def wrapped(state: dict) -> dict:
        entries = _run_entries.get()
        t0 = time.monotonic()

        # Snapshot relevant input fields
        input_snap = {
            k: _safe_copy(state.get(k))
            for k in _INPUT_FIELDS
            if state.get(k) not in (None, [], {}, "")
        }

        result = fn(state)

        duration_ms = max(1, int((time.monotonic() - t0) * 1000))

        # Output: the dict returned by the node (= the state updates)
        output_snap = _clean_output(result or {})

        if entries is not None:
            entries.append(
                {
                    "node": name,
                    "order": len(entries) + 1,
                    "input": input_snap,
                    "output": output_snap,
                    "duration_ms": duration_ms,
                }
            )

        return result

    wrapped.__name__ = fn.__name__
    return wrapped


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _safe_copy(v: Any) -> Any:
    """Return a JSON-serialisable copy (truncate large blobs)."""
    if isinstance(v, dict):
        return {k: _safe_copy(val) for k, val in list(v.items())[:20]}
    if isinstance(v, list):
        return [_safe_copy(i) for i in v[:10]]
    if isinstance(v, str) and len(v) > 300:
        return v[:300] + "…"
    return v


def _clean_output(d: dict) -> dict:
    """Remove large/noisy fields from the node output snapshot."""
    _SKIP = {"graph_trace", "debug_info", "response_data", "pending_transfer_data"}
    result = {}
    for k, v in d.items():
        if k in _SKIP:
            continue
        result[k] = _safe_copy(v)
    return result
