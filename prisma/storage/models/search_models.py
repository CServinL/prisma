"""Shared shapes for the two file-relevance-ranking backends
(ChromaDB semantic search and the knowledge graph's keyword search),
merged together by KnowledgeGraphService.ollama_deep_search().

GraphSearchResult (source_file, score) is kg_models.py's own /search
response shape -- reused here instead of a second, shape-identical model,
since chroma_service.py's query() and knowledge_graph_service.py's search()
represent the exact same "ranked file by relevance score" concept.
"""
from __future__ import annotations

from pydantic import BaseModel

from prisma.storage.models.kg_models import GraphSearchResult

__all__ = ["GraphSearchResult", "DeepSearchCandidate"]


class DeepSearchCandidate(BaseModel):
    source_file: str
    score: float
    reason: str = ""
