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

import requests

from prisma.storage.models.kg_models import (
    DeadLetterEntry,
    EntitiesForFileResponse,
    GraphQueryResult,
    KGStatus,
    RankedNode,
)
from prisma.storage.models.search_models import DeepSearchCandidate, GraphSearchResult

_log = logging.getLogger("prisma.knowledge_graph_client")


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
        return bool(data.get("tainted")) if data else False

    def list_dead_letters(self) -> list[DeadLetterEntry]:
        data = self._get("/list_dead_letters") or []
        return [DeadLetterEntry.model_validate(d) for d in data]

    def clear_dead_letters(self) -> int:
        data = self._post("/clear_dead_letters")
        return int(data.get("removed", 0)) if data else 0

    def entities_for_file(self, rel_path: str) -> EntitiesForFileResponse:
        data = self._get("/entities_for_file", params={"rel": rel_path})
        return EntitiesForFileResponse.model_validate(data) if data else EntitiesForFileResponse(entities=[], edges=[])

    def status(self) -> KGStatus:
        # Polled on every app.py /status request (itself polled by the UI
        # every ~10s with a 3s abort). A restarting/slow kg must not block
        # that whole response for up to self._timeout (10s default) — a
        # short, independent timeout here degrades gracefully to "kg
        # unreachable" instead of making the entire app look offline over
        # one subsystem's restart.
        data = self._get("/status", timeout=2.0)
        if data is None:
            return KGStatus(
                state="stale", last_indexed=None, last_error="kg process unreachable",
                sync_total=0, sync_done=0, current_file_chunks_done=0,
                current_file_chunks_total=0, chunk_duration_samples=0,
                dropped_chunks_total=0, dropped_chunks_recent=[],
            )
        return KGStatus.model_validate(data)

    def search(self, question: str, top_k: int = 20) -> list[GraphSearchResult]:
        data = self._get("/search", params={"q": question, "top_k": top_k}) or []
        return [GraphSearchResult.model_validate(d) for d in data]

    def ranked_nodes(self, question: str, top_k: int = 20) -> list[RankedNode]:
        data = self._get("/ranked_nodes", params={"q": question, "top_k": top_k}) or []
        return [RankedNode.model_validate(d) for d in data]

    def query(self, question: str, budget: int = 1500) -> list[GraphQueryResult]:
        data = self._get("/query", params={"q": question, "budget": budget}) or []
        return [GraphQueryResult.model_validate(d) for d in data]

    def _ollama_ready(self) -> bool:
        # Also polled on every /status request — see status()'s comment.
        data = self._get("/ollama_ready", timeout=2.0)
        return bool(data.get("reachable")) if data else False

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

    def _get(self, path: str, params: dict | None = None, timeout: float | None = None):
        try:
            resp = requests.get(f"{self._base_url}{path}", params=params, timeout=timeout or self._timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            _log.warning("kg process unreachable at %s%s: %s", self._base_url, path, exc)
            return None

    def _post(self, path: str, params: dict | None = None, timeout: float | None = None):
        try:
            resp = requests.post(f"{self._base_url}{path}", params=params, timeout=timeout or self._timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            _log.warning("kg process unreachable at %s%s: %s", self._base_url, path, exc)
            return None
