"""AWX knowledge-store adapter.

The exact AWX knowledge SDK surface can vary by deployed platform package.  This
adapter therefore follows a defensive pattern: try the configured AWX resource
client when present, and fall back to the local mock knowledge base otherwise.
That lets the agent workflow be developed now while leaving one narrow class to
finish once the target AWX collection IDs are known.
"""

from __future__ import annotations

from typing import Any

from .dtos import KnowledgeChunk, KnowledgeSearchResult
from .knowledge_guard import assess_knowledge_query
from .mock_adapter import MockKnowledgeAdapter


class AWXKnowledgeAdapter:
    source_name = "awx-knowledge"

    def __init__(self) -> None:
        self._fallback = MockKnowledgeAdapter()

    def retrieve(
        self,
        query: str,
        *,
        collection: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> KnowledgeSearchResult:
        guard = assess_knowledge_query(query, collection=collection)
        if not guard.allowed:
            return KnowledgeSearchResult(
                query=query,
                collection=collection,
                chunks=[],
                source=self.source_name,
                threshold_met=False,
                error_message=guard.reason,
            )

        result = self._retrieve_from_awx(query, collection=collection, top_k=top_k, filters=filters)
        if result is not None:
            return result
        fallback = self._fallback.retrieve(query, collection=collection, top_k=top_k, filters=filters)
        return KnowledgeSearchResult(
            query=query,
            collection=collection,
            chunks=fallback.chunks,
            source="awx-fallback-mock",
            threshold_met=fallback.threshold_met,
        )

    def _retrieve_from_awx(
        self,
        query: str,
        *,
        collection: str,
        top_k: int,
        filters: dict[str, Any] | None,
    ) -> KnowledgeSearchResult | None:
        try:
            from awx.resources import ExternalResource  # type: ignore
        except Exception:
            return None

        try:
            client = ExternalResource()
            raw = client.search(query=query, collection=collection, top_k=top_k, filters=filters or {})
        except Exception:
            return None

        chunks = normalize_awx_knowledge_response(raw, collection=collection)
        chunks.sort(key=lambda c: c.score, reverse=True)
        return KnowledgeSearchResult(
            query=query,
            collection=collection,
            chunks=chunks[:top_k],
            source=self.source_name,
            threshold_met=bool(chunks and chunks[0].score >= 0.7),
            raw_count=len(chunks),
        )


def normalize_awx_knowledge_response(raw: Any, *, collection: str) -> list[KnowledgeChunk]:
    """Normalize common AWX/vector-search response shapes.

    The final AWX project may expose results as `results`, `documents`,
    `chunks`, `items`, or a plain list.  Keeping this normalizer separate makes
    it easy to add one more payload variant without touching agent code.
    """
    items = _extract_items(raw)
    chunks: list[KnowledgeChunk] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        metadata = _metadata(item)
        content = (
            item.get("content")
            or item.get("text")
            or item.get("page_content")
            or item.get("chunk")
            or metadata.get("content")
            or ""
        )
        chunks.append(
            KnowledgeChunk(
                chunk_id=str(
                    item.get("chunk_id")
                    or item.get("chunkId")
                    or item.get("id")
                    or metadata.get("chunk_id")
                    or f"awx-{i}"
                ),
                title=str(
                    item.get("title")
                    or item.get("document_title")
                    or item.get("documentTitle")
                    or metadata.get("title")
                    or metadata.get("document_title")
                    or "AWX 문서"
                ),
                content=str(content),
                score=_score(item),
                collection=str(item.get("collection") or metadata.get("collection") or collection),
                source_uri=str(
                    item.get("source_uri")
                    or item.get("sourceUri")
                    or item.get("uri")
                    or metadata.get("source_uri")
                    or metadata.get("uri")
                    or ""
                ),
                document_version=str(
                    item.get("version")
                    or item.get("document_version")
                    or item.get("documentVersion")
                    or metadata.get("version")
                    or metadata.get("document_version")
                    or ""
                ),
                updated_at=str(item.get("updated_at") or item.get("updatedAt") or metadata.get("updated_at") or ""),
                metadata=metadata,
            )
        )
    return chunks


def _extract_items(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return raw
    if not isinstance(raw, dict):
        return []
    for key in ("results", "documents", "chunks", "items", "data"):
        value = raw.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _extract_items(value)
            if nested:
                return nested
    return []


def _metadata(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata") or item.get("meta") or {}
    return dict(metadata) if isinstance(metadata, dict) else {}


def _score(item: dict[str, Any]) -> float:
    for key in ("score", "similarity", "relevance_score", "relevanceScore"):
        value = item.get(key)
        try:
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0
