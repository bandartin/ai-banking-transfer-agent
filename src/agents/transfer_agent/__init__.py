"""
Banking AI Transfer Agent — reusable LangGraph-based transfer orchestration package.

Public surface:

    from src.agents.transfer_agent import run_transfer_agent, build_transfer_graph

- ``run_transfer_agent(user_id, message, session_id)`` — run one conversational
  turn and return a response dict.
- ``build_transfer_graph()`` — return the compiled LangGraph ``CompiledGraph``
  so callers can inspect or extend the graph.
"""

from .graph import build_transfer_graph, run_transfer_agent

__all__ = ["build_transfer_graph", "run_transfer_agent"]
