from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

import requests

from prisma.services import resource_lock
from prisma.services.vault import VaultService

_log = logging.getLogger("prisma.chroma")

_RESOURCE_HOLDER = "api"  # must match the worker name supervisor.py restarts, so a crash releases our leases


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
        chroma_host: str = "127.0.0.1",
        chroma_port: int = 8767,
        supervisor_host: str = "127.0.0.1",
        supervisor_port: int | None = None,
    ) -> None:
        self._vault = vault
        self._model = embedding_model
        self._base_url = ollama_base_url
        # ChromaDB runs as its own supervised server process (ADR-012), not
        # embedded — a crash there no longer takes down this process's threads.
        self._chroma_host = chroma_host
        self._chroma_port = chroma_port
        self._supervisor_host = supervisor_host
        self._supervisor_port = supervisor_port if supervisor_port is not None else resource_lock.default_port()
        self._chroma_dir = vault.root / "chromadb"
        self._manifest_path = self._chroma_dir / "manifest.json"
        self._client = None
        self._collection = None
        self._manifest: dict[str, float] = {}
        self._pending: set[Path] = set()
        # What the background thread is doing *right now* — e.g.
        # "embedding notes/foo.md" — so /status answers "what is the server
        # working on" without grepping chroma.log.
        self._current_activity: str | None = None
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
                if any(p in path.parts for p in ("chromadb", "kg-out", "graphify-out", "streams", "chats")):
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
        # Without joining this too, /reload/chroma could start a replacement
        # ChromaIndexer (and its own _loop thread) before this one actually
        # exits — Event.wait() wakes immediately once _stop_event is set, so
        # the common case (thread idle between cycles) joins fast; a thread
        # mid-extraction won't notice until it returns to the loop, so this
        # can still time out — that's surfaced as a warning, not silently
        # ignored, since a thread can't be force-killed from outside.
        if self._thread is not None:
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                _log.warning("chroma indexer thread did not exit within 5s — likely mid-extraction")
        _log.info("chroma stopped")

    def status(self) -> dict:
        try:
            self._ensure_client()
            chunks = self._collection.count()
        except Exception:
            chunks = -1
        with self._lock:
            files = len(self._manifest)
            activity = self._current_activity
        return {"chunks": chunks, "files_indexed": files, "model": self._model, "current_activity": activity}

    def _set_activity(self, activity: str | None) -> None:
        with self._lock:
            self._current_activity = activity

    def taint_file(self, rel_path: str) -> bool:
        """Force one specific file to be re-embedded on the next incremental
        cycle, without touching the rest of the index. Removes its manifest
        entry (an unchanged file's mtime would otherwise still match, and
        _upsert_file skips it) and enqueues it directly rather than waiting
        for a real filesystem event or the next full rescan. Returns False
        if the file doesn't exist in the vault."""
        path = self._vault.root / rel_path
        if not path.exists():
            return False
        with self._lock:
            self._manifest.pop(rel_path, None)
            self._pending.add(path)
        return True

    # ── Query ─────────────────────────────────────────────────────────────────

    def query(self, question: str, top_k: int = 20) -> list[dict]:
        try:
            self._ensure_client()
            total = self._collection.count()
            if total == 0:
                return []
        except Exception:
            return []
        with resource_lock.lease(self._supervisor_host, self._supervisor_port, holder=_RESOURCE_HOLDER, model=self._model) as granted:
            embeddings = _embed_texts([question], self._model, self._base_url) if granted else None
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
            client = chromadb.HttpClient(host=self._chroma_host, port=self._chroma_port)
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
                self._process_incremental(pending)
            self._stop_event.wait(timeout=60)

    def _process_incremental(self, pending: set[Path]) -> None:
        _log.info("chroma incremental update: %d files flagged by watcher", len(pending))
        dirty = False
        upserted = 0
        # Deletions need no Ollama call at all, so they must not be gated
        # behind the embed lease — a deleted file's tracking was previously
        # lost whenever the lease happened to be busy, even though there was
        # never any real contention for it.
        to_embed = []
        for path in pending:
            if path.exists():
                to_embed.append(path)
            else:
                dirty |= self._delete_file(path)
        # One lease covers the whole batch rather than one per file — HTTP
        # round-trips to the supervisor are cheap per-batch, not per-embed.
        granted = True
        if to_embed:
            with resource_lock.lease(self._supervisor_host, self._supervisor_port, holder=_RESOURCE_HOLDER, model=self._model) as granted:
                if granted:
                    for path in to_embed:
                        self._set_activity(f"embedding {path.name}")
                        changed = self._upsert_file(path)
                        dirty |= changed
                        upserted += changed
        if not granted:
            # Re-queue rather than silently dropping — a real bug this
            # closes: files that changed while the pool was busy would
            # otherwise never be retried unless they changed again.
            _log.warning(
                "chroma incremental update: %d file(s) skipped — no compute lease "
                "available, will retry next cycle", len(to_embed),
            )
            with self._lock:
                self._pending.update(to_embed)
        elif upserted == 0 and to_embed:
            # Watchdog fires on any filesystem event, not just real content
            # changes (e.g. a metadata-only touch, common on WSL2) — the
            # mtime-equality guard in _upsert_file correctly no-ops these,
            # but that's silent by default, which looks like a stuck/never-
            # finishing reindex if you're only watching this log.
            _log.info("chroma incremental update: no real content change — watcher false-positive, nothing re-embedded")
        if dirty:
            self._save_manifest()
        self._set_activity(None)

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
        # One lease for the entire pass, not one per file — a full index can touch
        # thousands of files and we don't want thousands of acquire/release round-trips.
        with resource_lock.lease(self._supervisor_host, self._supervisor_port, holder=_RESOURCE_HOLDER, model=self._model) as granted:
            if not granted:
                _log.warning("chroma full index skipped: no compute lease available")
                return
            if not self._probe_model():
                return
            # Chats are excluded from the vault-wide semantic index — unlike the
            # knowledge graph, ChromaDB's metadata has no trust_tier field to
            # filter by at query time, so this is the only place that can keep
            # chat transcripts out of search_vault's results.
            all_files = [
                p for p in self._vault._all_md_files()
                if "chats" not in p.relative_to(self._vault.root).parts
            ]
            _log.info("chroma full index start: %d files total", len(all_files))
            dirty = False
            for i, path in enumerate(all_files):
                self._set_activity(f"scanning file {i + 1}/{len(all_files)}: {path.name}")
                dirty |= self._upsert_file(path)
            if dirty:
                self._save_manifest()
            self._set_activity(None)
            _log.info("chroma full index done: %d files indexed, %d chunks", len(self._manifest), self._collection.count())

    def _upsert_file(self, path: Path) -> bool:
        try:
            mtime = path.stat().st_mtime
            rel = str(path.relative_to(self._vault.root))
        except (OSError, ValueError):
            return False
        # Skip files whose content hasn't changed since the last upsert. Without this,
        # any filesystem event that isn't an actual content change (e.g. a metadata-only
        # touch, common on WSL2's watch layer) would re-embed the file on every
        # incremental cycle forever, since the watchdog handler re-queues on any event.
        if self._manifest.get(rel) == mtime:
            return False
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
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
