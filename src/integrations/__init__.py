"""Integration boundary for real-bank, batch, and AWX/RAG adapters.

The agents should not know whether data came from the demo SQLite schema,
IBK core APIs, an ESB/MCI facade, or an AWX knowledge store.  This package is
the seam that keeps those runtime choices outside of the LangGraph workflow.
"""

from .factory import get_banking_adapter, get_knowledge_adapter

__all__ = ["get_banking_adapter", "get_knowledge_adapter"]

