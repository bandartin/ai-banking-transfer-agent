"""
노드 실행 추적 — 각 노드의 소요시간/순서를 LangGraph 상태(node_logs, graph_trace)에
누적한다. 상태 기반이므로 Send 병렬 실행에서도 안전하고, 체크포인터에 함께 저장된다.
"""

from __future__ import annotations

import time
from typing import Callable

from langgraph.runtime import Runtime
from langgraph.types import Command

from src.agents.context import BankingContext
from src.awx_runtime.observability import node_span


def traced(agent: str, node: str) -> Callable:
    """Decorator: wrap a (state, runtime) node and append trace/log entries."""

    def deco(fn: Callable) -> Callable:
        def wrapped(state: dict, runtime: Runtime[BankingContext]):
            t0 = time.monotonic()
            with node_span(agent, node, state):
                result = fn(state, runtime)
            duration_ms = max(1, int((time.monotonic() - t0) * 1000))

            log_entry = {"agent": agent, "node": node, "duration_ms": duration_ms}
            trace_entry = f"{agent}.{node}"

            if isinstance(result, Command):
                upd = dict(result.update or {})
                upd["node_logs"] = list(upd.get("node_logs", [])) + [log_entry]
                upd["graph_trace"] = list(upd.get("graph_trace", [])) + [trace_entry]
                return Command(goto=result.goto, update=upd, graph=result.graph)

            result = dict(result or {})
            result["node_logs"] = list(result.get("node_logs", [])) + [log_entry]
            result["graph_trace"] = list(result.get("graph_trace", [])) + [trace_entry]
            return result

        wrapped.__name__ = fn.__name__
        wrapped.__doc__ = fn.__doc__
        # Command[Literal[...]] 반환 어노테이션을 보존해야 LangGraph 가
        # 동적 goto 대상 노드를 그래프 컴파일 시점에 인식한다.
        wrapped.__annotations__ = dict(getattr(fn, "__annotations__", {}))
        return wrapped

    return deco


def activity(agent: str, event: str, detail: dict | None = None) -> dict:
    """agent_activity 이벤트 한 건 — UI 의 '에이전트 활동' 패널에 표시된다."""
    return {
        "agent": agent,
        "event": event,
        "detail": detail or {},
        "ts": time.strftime("%H:%M:%S"),
    }
