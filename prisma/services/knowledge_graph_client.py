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

    def mark_stale(self) -> None:
        self._post("/mark_stale")

    def drop_index(self) -> None:
        self._post("/drop_index")

    def status(self) -> dict:
        return self._get("/status") or {"state": "stale", "last_indexed": None, "last_error": "kg process unreachable"}

    def search(self, question: str, top_k: int = 20) -> list[dict]:
        return self._get("/search", params={"q": question, "top_k": top_k}) or []

    def ranked_nodes(self, question: str, top_k: int = 20) -> list[dict]:
        return self._get("/ranked_nodes", params={"q": question, "top_k": top_k}) or []

    def query(self, question: str, budget: int = 1500) -> list[dict]:
        return self._get("/query", params={"q": question, "budget": budget}) or []

    def _ollama_ready(self) -> bool:
        data = self._get("/ollama_ready")
        return bool(data.get("reachable")) if data else False

    def ollama_deep_search(self, question: str, top_k: int = 10, chroma=None) -> list[dict]:
        relevant_nodes = self.ranked_nodes(question, top_k=30)
        max_g = max((n["score"] for n in relevant_nodes), default=1.0) or 1.0
        file_scores: dict[str, float] = {
            n["source_file"]: n["score"] / max_g for n in relevant_nodes if n.get("source_file")
        }
        if chroma is not None:
            for item in chroma.query(question, top_k=top_k * 3):
                sf = item["source_file"]
                file_scores[sf] = max(file_scores.get(sf, 0.0), item["score"])
        if not file_scores:
            return []
        ranked = sorted(file_scores.items(), key=lambda x: -x[1])[:top_k]
        return [{"source_file": sf, "reason": "", "score": score} for sf, score in ranked]

    # ── Internal ──────────────────────────────────────────────────────────

    def _get(self, path: str, params: dict | None = None):
        try:
            resp = requests.get(f"{self._base_url}{path}", params=params, timeout=self._timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            _log.warning("kg process unreachable at %s%s: %s", self._base_url, path, exc)
            return None

    def _post(self, path: str) -> None:
        try:
            requests.post(f"{self._base_url}{path}", timeout=self._timeout)
        except requests.RequestException as exc:
            _log.warning("kg process unreachable at %s%s: %s", self._base_url, path, exc)
