from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

import requests

from prisma.services.vault import VaultService

_log = logging.getLogger("prisma.chroma")


def _embed_texts(texts: list[str], model: str, base_url: str = "http://localhost:11434") -> list[list[float]] | None:
    try:
        resp = requests.post(
            f"{base_url}/api/embed",
            json={"model": model, "input": texts},
            timeout=60,
        )
        if resp.status_code != 200:
            _log.warning("embed failed: status=%d", resp.status_code)
            return None
        return resp.json().get("embeddings")
    except Exception as exc:
        _log.warning("embed error: %s", exc)
        return None


def _chunk_markdown(text: str, max_chunk: int = 800) -> list[str]:
    import re
    sections = re.split(r"(?m)^#{1,2} ", text)
    chunks: list[str] = []
    step = max_chunk - 50
    for section in sections:
        section = section.strip()
        if not section:
            continue
        if len(section) <= max_chunk:
            chunks.append(section)
        else:
            for i in range(0, len(section), step):
                chunk = section[i : i + max_chunk].strip()
                if chunk:
                    chunks.append(chunk)
    return chunks or [text[:max_chunk]]


class ChromaIndexer:
    def __init__(
        self,
        vault: VaultService,
        embedding_model: str = "nomic-embed-text",
        ollama_base_url: str = "http://localhost:11434",
    ) -> None:
        self._vault = vault
        self._model = embedding_model
        self._base_url = ollama_base_url
        self._chroma_dir = vault.root / "chromadb"
        self._manifest_path = self._chroma_dir / "manifest.json"
        self._client = None
        self._collection = None
        self._manifest: dict[str, float] = {}
        self._pending: set[Path] = set()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._observer = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        from watchdog.events import FileSystemEventHandler, FileSystemEvent
        from watchdog.observers import Observer

        indexer = self

        class _Handler(FileSystemEventHandler):
            def on_any_event(self, event: FileSystemEvent) -> None:
                if event.is_directory:
                    return
                path = Path(str(event.src_path))
                if any(p in path.parts for p in ("chromadb", "graphify-out", "streams")):
                    return
                if path.name.startswith("."):
                    return
                if path.suffix == ".md":
                    with indexer._lock:
                        indexer._pending.add(path)

        self._vault.ensure_dirs()
        self._observer = Observer()
        self._observer.schedule(_Handler(), str(self._vault.root), recursive=True)
        self._observer.start()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="chroma-indexer")
        self._thread.start()
        _log.info("chroma started: model=%s vault=%s", self._model, self._vault.root)

    def stop(self) -> None:
        self._stop_event.set()
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=2)
        _log.info("chroma stopped")

    def status(self) -> dict:
        try:
            self._ensure_client()
            chunks = self._collection.count()
        except Exception:
            chunks = -1
        with self._lock:
            files = len(self._manifest)
        return {"chunks": chunks, "files_indexed": files, "model": self._model}

    # ── Query ─────────────────────────────────────────────────────────────────

    def query(self, question: str, top_k: int = 20) -> list[dict]:
        try:
            self._ensure_client()
            total = self._collection.count()
            if total == 0:
                return []
        except Exception:
            return []
        embeddings = _embed_texts([question], self._model, self._base_url)
        if not embeddings:
            _log.warning("chroma query: embedding failed for question, skipping")
            return []
        try:
            results = self._collection.query(
                query_embeddings=embeddings,
                n_results=min(top_k * 3, total),
                include=["metadatas", "distances"],
            )
        except Exception as exc:
            _log.warning("chroma query failed: %s", exc)
            return []
        # Aggregate chunk-level distances to file-level scores (best chunk wins)
        file_scores: dict[str, float] = {}
        for meta, dist in zip(results["metadatas"][0], results["distances"][0]):
            path = meta.get("path", "")
            if not path:
                continue
            score = max(0.0, 1.0 - dist)  # cosine distance: 0=identical → score=1
            if score > file_scores.get(path, 0.0):
                file_scores[path] = score
        ranked = sorted(file_scores.items(), key=lambda x: -x[1])[:top_k]
        _log.info("chroma query: q=%r chunks_searched=%d files_returned=%d", question[:60], total, len(ranked))
        return [{"source_file": sf, "score": score} for sf, score in ranked]

    # ── Internal ──────────────────────────────────────────────────────────────

    def _ensure_client(self) -> None:
        if self._collection is not None:
            return
        import chromadb
        self._chroma_dir.mkdir(parents=True, exist_ok=True)
        try:
            client = chromadb.PersistentClient(path=str(self._chroma_dir))
            collection = client.get_or_create_collection(
                "vault", metadata={"hnsw:space": "cosine"}
            )
        except Exception:
            self._client = None
            self._collection = None
            raise
        self._client = client
        self._collection = collection
        if self._manifest_path.exists():
            try:
                self._manifest = json.loads(self._manifest_path.read_text(encoding="utf-8"))
            except Exception:
                self._manifest = {}

    def _loop(self) -> None:
        self._stop_event.wait(timeout=20)
        self._full_index()
        while not self._stop_event.is_set():
            with self._lock:
                pending = self._pending.copy()
                self._pending.clear()
            if pending:
                _log.info("chroma incremental update: %d files changed", len(pending))
                dirty = False
                for path in pending:
                    if path.exists():
                        dirty |= self._upsert_file(path)
                    else:
                        dirty |= self._delete_file(path)
                if dirty:
                    self._save_manifest()
            self._stop_event.wait(timeout=60)

    def _probe_model(self) -> bool:
        """Return False and log an actionable warning if the embedding model is not available."""
        result = _embed_texts(["test"], self._model, self._base_url)
        if result is None:
            _log.error(
                "chroma: embedding model %r not available — run: ollama pull %s",
                self._model, self._model,
            )
            return False
        return True

    def _full_index(self) -> None:
        try:
            self._ensure_client()
        except Exception as exc:
            _log.error("chroma init failed: %s", exc)
            return
        if not self._probe_model():
            return
        all_files = list(self._vault._all_md_files())
        stale = [
            p for p in all_files
            if not (lambda rel, mtime: self._manifest.get(rel) == mtime)(
                str(p.relative_to(self._vault.root)),
                p.stat().st_mtime if p.exists() else 0,
            )
        ]
        _log.info("chroma full index start: %d files total, %d stale", len(all_files), len(stale))
        dirty = False
        for path in all_files:
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            rel = str(path.relative_to(self._vault.root))
            if self._manifest.get(rel) == mtime:
                continue
            dirty |= self._upsert_file(path)
        if dirty:
            self._save_manifest()
        _log.info("chroma full index done: %d files indexed, %d chunks", len(self._manifest), self._collection.count())

    def _upsert_file(self, path: Path) -> bool:
        try:
            mtime = path.stat().st_mtime
            text = path.read_text(encoding="utf-8", errors="replace")
            rel = str(path.relative_to(self._vault.root))
        except (OSError, ValueError):
            return False
        chunks = _chunk_markdown(text)
        embeddings = _embed_texts(chunks, self._model, self._base_url)
        if embeddings is None or len(embeddings) != len(chunks):
            _log.warning("chroma: embedding failed for %s — skipping", rel)
            return False
        ids = [f"{rel}#{i}" for i in range(len(chunks))]
        metadatas = [{"path": rel, "chunk": i} for i in range(len(chunks))]
        self._collection.upsert(ids=ids, embeddings=embeddings, metadatas=metadatas, documents=chunks)
        with self._lock:
            self._manifest[rel] = mtime
        _log.info("chroma upserted: %s (%d chunks)", rel, len(chunks))
        return True

    def _delete_file(self, path: Path) -> bool:
        try:
            rel = str(path.relative_to(self._vault.root))
        except ValueError:
            return False
        try:
            self._ensure_client()
            self._collection.delete(where={"path": rel})
            with self._lock:
                self._manifest.pop(rel, None)
            return True
        except Exception as exc:
            _log.warning("chroma delete failed for %s: %s", rel, exc)
            return False

    def _save_manifest(self) -> None:
        with self._lock:
            data = dict(self._manifest)
        try:
            self._manifest_path.write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            pass
