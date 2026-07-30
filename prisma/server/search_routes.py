"""Vault search endpoints (/search, /search/deep).

Built via a factory (`build_search_router`) taking getter callables rather
than raw objects, same reasoning as sync_routes.py's `build_sync_router`:
app.py's `/reload`-style endpoints rebind its `_vault`/`_indexer`/`_chroma`
module globals at runtime, so a router that captured them by value at
include_router() time would keep talking to a stale, replaced instance
after a reload.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from fastapi import APIRouter, Query
from pydantic import BaseModel

from prisma.services.chroma_service import ChromaIndexer
from prisma.services.knowledge_graph_client import KnowledgeGraphClient
from prisma.services.vault import VaultService
from prisma.storage.models.search_models import DeepSearchCandidate
from prisma.utils.text import significant_words as _significant_words


class SearchResult(BaseModel):
    slug: str
    title: str
    excerpt: str
    score: float = 1.0


class DeepSearchResult(BaseModel):
    slug: str
    title: str
    excerpt: str
    score: float
    reason: str = ""


class _SearchIndex:
    """In-memory full-text index over vault files, keyed by absolute path.
    Rebuilt lazily on each search: only re-reads files whose mtime changed."""

    def __init__(self, get_vault: Callable[[], VaultService]) -> None:
        self._get_vault = get_vault
        # (mtime, slug, title, lower_text, lines)
        self._entries: dict[str, tuple[float, str, str, str, list[str]]] = {}
        self._lock = threading.Lock()

    def _refresh(self) -> None:
        vault = self._get_vault()
        with self._lock:
            seen: set[str] = set()
            for path in vault.iter_files():
                key = str(path)
                seen.add(key)
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    continue
                cached = self._entries.get(key)
                if cached and cached[0] == mtime:
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                slug = path.stem
                title = slug
                try:
                    node = vault.get_any(slug)
                    title = node.title
                except Exception:
                    pass
                self._entries[key] = (mtime, slug, title, text.lower(), text.splitlines())
            # Drop deleted files
            for key in list(self._entries):
                if key not in seen:
                    del self._entries[key]

    def search(self, q: str, top_k: int = 30) -> list[SearchResult]:
        terms = [t.lower().strip('"') for t in q.split() if t.strip('"')]
        if not terms:
            return []

        # Expand terms with stems so "learning" also matches "learned", "learns", etc.
        query_stems = _significant_words(q)

        self._refresh()

        results: list[tuple[float, str, str, str]] = []
        with self._lock:
            entries = list(self._entries.values())

        for _mtime, slug, title, lower, lines in entries:
            hits = sum(1 for t in terms if t in lower)
            title_lower = title.lower()
            score = hits * 1.0
            for t in terms:
                if t in title_lower:
                    score += 4.0
            if hits == len(terms):
                score += 3.0

            # Stem-overlap bonus — rewards documents that share many stem roots with the query
            doc_stems = _significant_words(title + " " + lower[:500])
            stem_overlap = len(query_stems & doc_stems)
            score += stem_overlap * 0.5

            if score == 0:
                continue

            excerpt = ""
            for line in lines:
                ll = line.lower().strip()
                if ll and any(t in ll for t in terms):
                    excerpt = line.strip()[:200]
                    break
            results.append((score, slug, title, excerpt))

        results.sort(key=lambda x: -x[0])
        return [
            SearchResult(slug=slug, title=title, excerpt=excerpt, score=score)
            for score, slug, title, excerpt in results[:top_k]
        ]


def build_search_router(
    get_vault: Callable[[], VaultService],
    get_indexer: Callable[[], KnowledgeGraphClient],
    get_chroma: Callable[[], ChromaIndexer],
) -> APIRouter:
    router = APIRouter(prefix="/search", tags=["search"])
    index = _SearchIndex(get_vault)

    def _resolve_source_files(
        items: list[DeepSearchCandidate], query_stems: frozenset | None = None,
    ) -> list[DeepSearchResult]:
        """Map DeepSearchCandidate(source_file, score, reason) to DeepSearchResult, resolving slugs."""
        vault = get_vault()
        vault_root = str(vault.root)
        seen: set[str] = set()
        out: list[tuple[float, str, str, str, str]] = []
        for item in items:
            src = item.source_file
            if not src:
                continue
            slug = Path(vault_root, src).stem
            if slug in seen:
                continue
            seen.add(slug)
            try:
                node = vault.get_any(slug)
                title = node.title
                body = node.body if hasattr(node, "body") else ""
            except Exception:
                title = slug
                body = ""
            excerpt = body[:200].replace("\n", " ").strip() if body else ""
            score = item.score
            if query_stems:
                doc_stems = _significant_words(title + " " + (body[:500] if body else ""))
                score += len(query_stems & doc_stems) * 0.05
            out.append((score, slug, title, excerpt, item.reason))
        out.sort(key=lambda x: -x[0])
        return [DeepSearchResult(slug=sl, title=ti, excerpt=ex, score=sc, reason=re)
                for sc, sl, ti, ex, re in out]

    @router.get("")
    def search(q: str = Query(..., min_length=1)) -> list[SearchResult]:
        return index.search(q)

    @router.get("/deep")
    def deep_search(q: str = Query(..., min_length=1)) -> list[DeepSearchResult]:
        """Semantic search: Ollama reasons over the knowledge graph, falls back to graph scoring."""
        query_stems = _significant_words(q)
        indexer = get_indexer()
        ollama_results = indexer.ollama_deep_search(q, top_k=15, chroma=get_chroma())
        if ollama_results:
            return _resolve_source_files(ollama_results, query_stems=query_stems)

        # Fallback: graph scoring aggregated by file
        graph_nodes = indexer.ranked_nodes(q, top_k=30)
        if graph_nodes:
            items = [DeepSearchCandidate(source_file=n.source_file, score=n.score, reason=n.label)
                     for n in graph_nodes if n.source_file]
            results = _resolve_source_files(items, query_stems=query_stems)
            # Pad with text search for coverage
            seen = {r.slug for r in results}
            for r in index.search(q, top_k=10):
                if r.slug not in seen:
                    results.append(DeepSearchResult(slug=r.slug, title=r.title,
                                                    excerpt=r.excerpt, score=r.score * 0.3))
            results.sort(key=lambda x: -x.score)
            return results[:20]

        # Graph not built — text only
        return [DeepSearchResult(slug=r.slug, title=r.title, excerpt=r.excerpt, score=r.score)
                for r in index.search(q, top_k=20)]

    return router
