"""Thin HTTP client for the knowledge graph process (see prisma.server.kg_app
and ADR-012's follow-up section).

`KnowledgeGraphService` itself runs in its own supervised "kg" worker
process now, not inside "api" — it owns the sole Kùzu connection (only one
process may ever hold that database open) and does all LLM extraction
there, isolated from api's REST/WebSocket traffic. This client matches
`KnowledgeGraphService`'s public method names/shapes so `app.py`'s call
sites need no changes beyond constructing this instead of that.

`ollama_deep_search()` is the one method with real logic here rather than a
plain HTTP passthrough: merging with ChromaDB's scores has to happen on this
side, since ChromaDB lives in the api process, not the kg process.
"""
from __future__ import annotations

import logging
from typing import Callable, TypeVar

import requests
from pydantic import ValidationError

from prisma.storage.models.kg_models import (
    AuthorSummary,
    DeadLetterEntry,
    EntitiesForFileResponse,
    ExpandNodeResponse,
    GraphQueryResult,
    GraphRelevance,
    KGStatus,
    RankedNode,
    SuggestedQuestion,
    SurprisingConnection,
    TimelineEntry,
    TopEntity,
    VaultHealthResponse,
)
from prisma.storage.models.search_models import DeepSearchCandidate, GraphSearchResult

_log = logging.getLogger("prisma.knowledge_graph_client")

_T = TypeVar("_T")


class KnowledgeGraphClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 8768, timeout: float = 10.0) -> None:
        self._base_url = f"http://{host}:{port}"
        self._timeout = timeout

    # ── Lifecycle — no-ops: the kg worker process owns its own start/stop
    # via kg_app.py's lifespan hook, managed by the supervisor, not by
    # whatever calls this client. Kept so app.py's existing call sites
    # (_indexer.start() / _indexer.stop()) need no changes. ────────────────

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def mark_stale(self, path: str | None = None) -> None:
        self._post("/mark_stale", params={"path": path} if path is not None else None)

    def drop_index(self) -> None:
        self._post("/drop_index")

    def taint_file(self, rel_path: str) -> bool:
        data = self._post("/taint_file", params={"rel": rel_path})
        if data is None:
            return False
        return self._safe(lambda: bool(data.get("tainted")), False)

    def list_dead_letters(self) -> list[DeadLetterEntry]:
        data = self._get("/list_dead_letters") or []
        return self._safe(lambda: [DeadLetterEntry.model_validate(d) for d in data], [])

    def clear_dead_letters(self) -> int:
        data = self._post("/clear_dead_letters")
        if data is None:
            return 0
        return self._safe(lambda: int(data.get("removed", 0)), 0)

    def entities_for_file(self, rel_path: str) -> EntitiesForFileResponse:
        default = EntitiesForFileResponse(entities=[], edges=[])
        data = self._get("/entities_for_file", params={"rel": rel_path})
        if not data:
            return default
        return self._safe(lambda: EntitiesForFileResponse.model_validate(data), default)

    def status(self) -> KGStatus:
        # Polled on every app.py /status request (itself polled by the UI
        # every ~10s with a 3s abort). A restarting/slow kg must not block
        # that whole response for up to self._timeout (10s default) — a
        # short, independent timeout here degrades gracefully to "kg
        # unreachable" instead of making the entire app look offline over
        # one subsystem's restart.
        unreachable = KGStatus(
            state="stale", last_indexed=None, last_error="kg process unreachable",
            sync_total=0, sync_done=0, current_file_chunks_done=0,
            current_file_chunks_total=0, chunk_duration_samples=0,
            dropped_chunks_total=0, dropped_chunks_recent=[],
        )
        data = self._get("/status", timeout=2.0)
        if data is None:
            return unreachable
        return self._safe(lambda: KGStatus.model_validate(data), unreachable)

    def search(self, question: str, top_k: int = 20) -> list[GraphSearchResult]:
        data = self._get("/search", params={"q": question, "top_k": top_k}) or []
        return self._safe(lambda: [GraphSearchResult.model_validate(d) for d in data], [])

    def ranked_nodes(self, question: str, top_k: int = 20) -> list[RankedNode]:
        data = self._get("/ranked_nodes", params={"q": question, "top_k": top_k}) or []
        return self._safe(lambda: [RankedNode.model_validate(d) for d in data], [])

    def query(self, question: str, budget: int = 1500) -> list[GraphQueryResult]:
        data = self._get("/query", params={"q": question, "budget": budget}) or []
        return self._safe(lambda: [GraphQueryResult.model_validate(d) for d in data], [])

    def top_entities(self, limit: int = 15) -> list[TopEntity]:
        # Called synchronously on every chat turn (SessionOrchestrator's
        # vault_overview callable) -- same short-timeout/degrade-fast
        # reasoning as status() above, cached data on the other end so this
        # should normally be fast regardless.
        data = self._get("/top_entities", params={"limit": limit}, timeout=2.0)
        if data is None:
            return []
        return self._safe(lambda: [TopEntity.model_validate(d) for d in data], [])

    # ── Phase A retrieval capabilities (mirror kg_app.py's routes) ─────────

    def expand_node(self, node_id: str, limit: int = 100) -> ExpandNodeResponse:
        default = ExpandNodeResponse(entities=[], edges=[])
        data = self._get("/expand_node", params={"id": node_id, "limit": limit})
        if not data:
            return default
        return self._safe(lambda: ExpandNodeResponse.model_validate(data), default)

    def god_nodes(self, limit: int = 15) -> list[TopEntity]:
        data = self._get("/god_nodes", params={"limit": limit}) or []
        return self._safe(lambda: [TopEntity.model_validate(d) for d in data], [])

    def surprising_connections(self, limit: int = 15) -> list[SurprisingConnection]:
        # Cache-only on the kg side too (KnowledgeGraphService.surprising_
        # connections()) -- same short-timeout reasoning as top_entities()
        # above.
        data = self._get("/surprising_connections", params={"limit": limit}, timeout=2.0)
        if data is None:
            return []
        return self._safe(lambda: [SurprisingConnection.model_validate(d) for d in data], [])

    def authors(self, limit: int = 100) -> list[AuthorSummary]:  # DEFAULT_AUTHORS
        data = self._get("/authors", params={"limit": limit}) or []
        return self._safe(lambda: [AuthorSummary.model_validate(d) for d in data], [])

    def suggest_questions(self, limit: int = 15) -> list[SuggestedQuestion]:
        # Cache-only on the kg side too (KnowledgeGraphService.
        # suggest_questions()) -- same short-timeout reasoning as
        # surprising_connections() above.
        data = self._get("/suggest_questions", params={"limit": limit}, timeout=2.0)
        if data is None:
            return []
        return self._safe(lambda: [SuggestedQuestion.model_validate(d) for d in data], [])

    def graph_relevance(self, texts: list[str]) -> list[GraphRelevance]:
        # Positional correspondence with `texts` must survive a degrade --
        # the caller (a Zotero item listing) zips this back against its own
        # item list, so `[]` here would misalign every item after the first
        # failure instead of just scoring everything zero.
        zero_scores = [GraphRelevance(score=0, matched_entities=[]) for _ in texts]
        data = self._post("/graph_relevance", json={"texts": texts}, timeout=2.0)
        if data is None:
            return zero_scores
        return self._safe(lambda: [GraphRelevance.model_validate(d) for d in data], zero_scores)

    def vault_health(self, limit: int = 500) -> VaultHealthResponse:
        default = VaultHealthResponse(orphans=[], orphan_count=0)
        data = self._get("/vault_health", params={"limit": limit})
        if not data:
            return default
        return self._safe(lambda: VaultHealthResponse.model_validate(data), default)

    def timeline(self, question: str, limit: int = 50) -> list[TimelineEntry]:
        data = self._get("/timeline", params={"q": question, "limit": limit}) or []
        return self._safe(lambda: [TimelineEntry.model_validate(d) for d in data], [])

    def _ollama_ready(self) -> bool:
        # Also polled on every /status request — see status()'s comment.
        data = self._get("/ollama_ready", timeout=2.0)
        if data is None:
            return False
        return self._safe(lambda: bool(data.get("reachable")), False)

    def ollama_deep_search(self, question: str, top_k: int = 10, chroma=None) -> list[DeepSearchCandidate]:
        relevant_nodes = self.ranked_nodes(question, top_k=30)
        max_g = max((n.score for n in relevant_nodes), default=1.0) or 1.0
        file_scores: dict[str, float] = {
            n.source_file: n.score / max_g for n in relevant_nodes if n.source_file
        }
        if chroma is not None:
            for item in chroma.query(question, top_k=top_k * 3):
                file_scores[item.source_file] = max(file_scores.get(item.source_file, 0.0), item.score)
        if not file_scores:
            return []
        ranked = sorted(file_scores.items(), key=lambda x: -x[1])[:top_k]
        return [DeepSearchCandidate(source_file=sf, reason="", score=score) for sf, score in ranked]

    # ── Internal ──────────────────────────────────────────────────────────

    def _safe(self, parse: Callable[[], _T], default: _T) -> _T:
        """Every public method above degrades to some default shape when
        `_get`/`_post` return `None` (network-level failure) -- this covers
        the other half: the kg worker responded, but the body doesn't match
        what this method expected to parse it into (a `ValidationError` from
        `model_validate`, or an `AttributeError`/`TypeError` from `.get()`
        on a response that parsed as JSON but isn't the dict/list shape
        assumed, e.g. during a client/server version mismatch across a
        rolling deploy). Without this, that class of failure propagated as
        an unhandled exception through this client into whatever called it
        -- an unhandled 500 for a route that otherwise documents itself as
        degrading gracefully (caught in review; was previously only handled
        ad hoc in individual methods, inconsistently across the class)."""
        try:
            return parse()
        except (ValidationError, TypeError, KeyError, AttributeError) as exc:
            _log.warning("kg process returned malformed data: %s", exc)
            return default

    def _get(self, path: str, params: dict | None = None, timeout: float | None = None):
        try:
            resp = requests.get(f"{self._base_url}{path}", params=params, timeout=timeout or self._timeout)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            # ValueError also covers resp.json() raising JSONDecodeError on
            # a non-JSON 200 body -- the HTTP call itself succeeded, but the
            # response still isn't usable, same degrade as unreachable.
            _log.warning("kg process unreachable at %s%s: %s", self._base_url, path, exc)
            return None

    def _post(
        self, path: str, params: dict | None = None, json: object | None = None,
        timeout: float | None = None,
    ):
        try:
            resp = requests.post(
                f"{self._base_url}{path}", params=params, json=json, timeout=timeout or self._timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            _log.warning("kg process unreachable at %s%s: %s", self._base_url, path, exc)
            return None
