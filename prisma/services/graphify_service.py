from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Literal

from watchdog.events import FileSystemEventHandler, FileSystemEvent
from watchdog.observers import Observer

from prisma.services import resource_lock
from prisma.services.vault import VaultService

_log = logging.getLogger("prisma.graphify")

IndexState = Literal["idle", "indexing", "stale"]

# PDFs are extracted to .md by ensure_all_md_formats — no need to index .pdf directly.
DEFAULT_INDEX_EXTENSIONS: tuple[str, ...] = (
    ".md",
    ".png", ".jpg", ".jpeg", ".webp", ".gif",
)


def _die_with_parent() -> None:
    """Linux-only, best-effort: ask the kernel to SIGTERM this subprocess the
    moment its parent (the API process) dies, for any reason — crash, SIGKILL,
    or anything else that skips GraphifyIndexer.stop()'s own cleanup. See the
    identical helper in prisma.server.supervisor for the full rationale;
    duplicated rather than shared so this module doesn't depend on the server
    package, and vice versa."""
    try:
        import ctypes
        PR_SET_PDEATHSIG = 1
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM)
    except Exception:
        pass  # non-Linux, or prctl unavailable — best effort only


class _VaultChangeHandler(FileSystemEventHandler):
    def __init__(self, indexer: "GraphifyIndexer") -> None:
        self._indexer = indexer

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = Path(str(event.src_path))
        if "graphify-out" in path.parts or "streams" in path.parts or path.name.startswith("."):
            return
        if path.suffix in self._indexer.index_extensions:
            self._indexer.mark_stale()


class GraphifyIndexer:
    def __init__(self, vault: VaultService, interval_minutes: int = 10,
                 ollama_model: str = "qwen2.5-graphify:7b",
                 index_extensions: tuple[str, ...] = DEFAULT_INDEX_EXTENSIONS,
                 supervisor_host: str = "127.0.0.1", supervisor_port: int = 8760) -> None:
        self._vault = vault
        self._interval = interval_minutes * 60
        self._ollama_model = ollama_model
        self.index_extensions = index_extensions
        self._supervisor_host = supervisor_host
        self._supervisor_port = supervisor_port
        self._out_dir = vault.root / "graphify-out"
        self._graph_json = self._out_dir / "graph.json"
        self._state: IndexState = "stale" if not self._graph_json.exists() else "idle"
        self._last_indexed: datetime | None = None
        self._last_error: str | None = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._observer: Observer | None = None
        self._current_proc: subprocess.Popen | None = None

    def start(self) -> None:
        self._vault.ensure_dirs()
        self._observer = Observer()
        self._observer.schedule(_VaultChangeHandler(self), str(self._vault.root), recursive=True)
        self._observer.start()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="graphify-indexer")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=2)
        # The subprocess runs in its own session (see _run_graphify), so it doesn't
        # receive the terminal's Ctrl+C directly — terminate it here instead, so an
        # in-flight LLM call gets a clean SIGTERM rather than being killed mid-request
        # by an inherited signal.
        with self._lock:
            proc = self._current_proc
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    def mark_stale(self) -> None:
        with self._lock:
            if self._state != "indexing":
                self._state = "stale"

    def drop_index(self) -> None:
        for name in ("graph.json", "manifest.json"):
            p = self._out_dir / name
            if p.exists():
                p.unlink()
        with self._lock:
            self._state = "stale"
            self._last_indexed = None
            self._last_error = None

    def status(self) -> dict:
        with self._lock:
            return {
                "state": self._state,
                "last_indexed": self._last_indexed.isoformat() if self._last_indexed else None,
                "last_error": self._last_error,
            }

    # ── Graph query methods ───────────────────────────────────────────────────

    def query(self, question: str, budget: int = 1500) -> list[dict]:
        if not self._graph_json.exists():
            return []
        try:
            from graphify.serve import _query_graph_text
            G = self._load_graph()
            text = _query_graph_text(G, question, token_budget=budget)
            return [{"text": text}]
        except Exception:
            return []

    def ranked_nodes(self, question: str, top_k: int = 20) -> list[dict]:
        if not self._graph_json.exists():
            return []
        try:
            from graphify.serve import _score_nodes, _query_terms

            G = self._load_graph()
            terms = _query_terms(question)
            if not terms:
                return []

            if len(terms) >= 2:
                seed_scores: dict[str, float] = {nid: s for s, nid in _score_nodes(G, [terms[0]])}
                seeds = {nid for nid, s in seed_scores.items() if s > 0}

                expanded: set[str] = set(seeds)
                for nid in seeds:
                    expanded.update(G.neighbors(nid))

                remaining: dict[str, float] = {nid: s for s, nid in _score_nodes(G, terms[1:])}
                node_scores: dict[str, float] = {}
                for nid in expanded:
                    rs = remaining.get(nid, 0.0)
                    if rs > 0:
                        proximity = 1.0 if nid in seeds else 0.5
                        node_scores[nid] = rs * proximity + seed_scores.get(nid, 0.0) * 0.3

                if not node_scores:
                    node_scores = {nid: s for s, nid in _score_nodes(G, terms)}
            else:
                node_scores = {nid: s for s, nid in _score_nodes(G, terms)}

            neighbor_bonus: dict[str, float] = {}
            for nid, score in node_scores.items():
                for nb in G.neighbors(nid):
                    if nb not in node_scores:
                        neighbor_bonus[nb] = max(neighbor_bonus.get(nb, 0.0), score * 0.3)
            for nb, bonus in neighbor_bonus.items():
                node_scores[nb] = node_scores.get(nb, 0.0) + bonus

            file_scores: dict[str, float] = {}
            file_label: dict[str, str] = {}
            for nid, score in node_scores.items():
                data = G.nodes[nid]
                sf = data.get("source_file", "")
                if not sf:
                    continue
                file_scores[sf] = file_scores.get(sf, 0.0) + score
                if sf not in file_label:
                    file_label[sf] = data.get("label", nid)

            ranked = sorted(file_scores.items(), key=lambda x: -x[1])[:top_k]
            return [{"source_file": sf, "label": file_label.get(sf, ""), "score": score}
                    for sf, score in ranked]
        except Exception:
            return []

    def ollama_deep_search(self, question: str, top_k: int = 10, chroma=None) -> list[dict]:
        if not self._graph_json.exists() and chroma is None:
            return []
        context_results = self.query(question, budget=4000) if self._graph_json.exists() else []
        graph_text = context_results[0].get("text", "") if context_results else ""

        relevant_nodes = self.ranked_nodes(question, top_k=30) if self._graph_json.exists() else []

        # Normalize graphify scores to [0, 1]
        max_g = max((n["score"] for n in relevant_nodes), default=1.0) or 1.0
        file_scores: dict[str, float] = {
            n["source_file"]: n["score"] / max_g
            for n in relevant_nodes if n.get("source_file")
        }

        # Merge with ChromaDB scores (take max per file)
        if chroma is not None:
            for item in chroma.query(question, top_k=top_k * 3):
                sf = item["source_file"]
                file_scores[sf] = max(file_scores.get(sf, 0.0), item["score"])

        if not file_scores:
            return []

        source_files = sorted(file_scores.keys(), key=lambda sf: -file_scores[sf])[:20]
        seen_sf: set[str] = set(source_files)

        sources_list = "\n".join(f"- {sf}" for sf in source_files)
        prompt = (
            f'Query: "{question}"\n\n'
            f"Knowledge graph context (most relevant nodes and relationships):\n{graph_text}\n\n"
            f"Source documents found in graph:\n{sources_list}\n\n"
            f'Rank these source documents by relevance to "{question}". '
            f"Return JSON:\n"
            f'{{"results": [{{"source_file": "exact path from list above", '
            f'"reason": "one-sentence explanation", "score": 0.0}}]}}\n\n'
            f"Return at most {top_k} results. Only include genuinely relevant docs. "
            f"Valid JSON only, no other text."
        )
        try:
            from openai import OpenAI
            client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
            resp = client.chat.completions.create(
                model=self._ollama_model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
            data = json.loads(resp.choices[0].message.content)
            results = data.get("results", [])
            return [r for r in results if r.get("source_file", "") in seen_sf]
        except Exception as exc:
            _log.warning("ollama_deep_search failed: %s", exc)
            return []

    # ── Graph helper ──────────────────────────────────────────────────────────

    def _load_graph(self):
        from networkx.readwrite import json_graph
        raw = json.loads(self._graph_json.read_text(encoding="utf-8"))
        if "edges" not in raw and "links" in raw:
            raw = dict(raw, edges=raw["links"])
        return json_graph.node_link_graph(raw)

    # ── Subprocess wrapper ────────────────────────────────────────────────────

    # Per-chunk LLM timeout (seconds).
    _CHUNK_TIMEOUT = 120
    # 2-hour hard ceiling; normal runs finish in minutes.
    _PROC_TIMEOUT = 7200

    # Holder is the worker name ("api"), not a task label — release_all_held_by
    # (the fast path, triggered the instant that worker dies/restarts) matches
    # on this. The finer-grained safety net (a single hung/dead task, worker
    # otherwise fine) is PID- and lease-timeout-based instead — see
    # resource_lock.acquire() and Supervisor.ResourceManager.reap().
    _RESOURCE_HOLDER = "api"

    def _run_graphify(self, input_path: Path) -> bool:
        # Ask the supervisor for permission before spawning — graphify makes
        # sustained, concurrent-hostile calls to Ollama, and it's not the only
        # thing that might (chroma's embeddings, chat, later). See ADR-012 and
        # prisma.services.resource_lock. Fails open if the supervisor isn't
        # running at all (e.g. direct `uvicorn` for local dev).
        with resource_lock.lease(
            self._supervisor_host, self._supervisor_port,
            holder=self._RESOURCE_HOLDER,
            # Matches the hard ceiling _run_graphify_locked itself enforces
            # (plus margin), so the reaper never races a legitimately still-
            # running extraction — it only catches one that's truly wedged.
            lease_timeout=self._PROC_TIMEOUT + 60,
            model=self._ollama_model,
        ) as granted:
            if not granted:
                _log.info("graphify: no free GPU/LLM compute pool right now — skipping this cycle")
                return False
            return self._run_graphify_locked(input_path)

    def _run_graphify_locked(self, input_path: Path) -> bool:
        import sys
        # token_budget matches num_ctx minus headroom for output + system prompt.
        token_budget = 8000
        env = {**os.environ}
        if not env.get("OLLAMA_API_KEY"):
            env["OLLAMA_API_KEY"] = "ollama"
        stderr_lines: list[str] = []
        proc: subprocess.Popen | None = None
        try:
            # Holding the lock across spawn-and-register closes a race with stop():
            # without it, stop() could read self._current_proc in the gap between
            # Popen() returning and the assignment below, see a stale/None value,
            # and terminate nothing — silently orphaning this subprocess to keep
            # running (and hammering Ollama) even after the indexer was told to stop.
            with self._lock:
                if self._stop_event.is_set():
                    return False
                proc = subprocess.Popen(
                    [sys.executable, "-m", "graphify", str(input_path),
                     "--backend", "ollama", "--model", self._ollama_model,
                     "--token-budget", str(token_budget),
                     "--api-timeout", str(self._CHUNK_TIMEOUT)],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    # Own session so a terminal Ctrl+C (SIGINT to the foreground process
                    # group) doesn't kill this mid-request — the server's own shutdown
                    # path (stop()) terminates it deliberately instead.
                    start_new_session=True,
                    # Last-resort backstop: if the API process itself dies without
                    # running that shutdown path (crash, SIGKILL), the kernel still
                    # tells this subprocess to exit rather than leaving it orphaned.
                    preexec_fn=_die_with_parent,
                )
                self._current_proc = proc
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip()
                if not line:
                    continue
                stderr_lines.append(line)
                if "error" in line.lower() or "warning" in line.lower():
                    _log.warning("graphify: %s", line)
                else:
                    _log.info("graphify: %s", line)
            proc.wait(timeout=self._PROC_TIMEOUT)
            if proc.returncode == 0:
                return True
            err = next((l for l in reversed(stderr_lines) if "error" in l.lower()),
                       stderr_lines[-1] if stderr_lines else f"exit {proc.returncode}")
            _log.error("graphify failed (exit %d): %s", proc.returncode, err)
            with self._lock:
                self._last_error = err
            return False
        except subprocess.TimeoutExpired:
            _log.error("graphify subprocess exceeded %ds hard ceiling — killing", self._PROC_TIMEOUT)
            proc.kill()
            with self._lock:
                self._last_error = "subprocess timeout"
            return False
        except Exception as exc:
            _log.exception("graphify exception: %s", exc)
            with self._lock:
                self._last_error = str(exc)
            return False
        finally:
            with self._lock:
                if self._current_proc is proc:
                    self._current_proc = None

    # ── Index loop ────────────────────────────────────────────────────────────

    def _ollama_ready(self) -> bool:
        import socket
        try:
            with socket.create_connection(("127.0.0.1", 11434), timeout=3):
                return True
        except OSError:
            return False

    def _loop(self) -> None:
        self._stop_event.wait(timeout=15)
        while not self._stop_event.is_set():
            with self._lock:
                needs_run = self._state == "stale"
            if needs_run:
                if self._ollama_ready():
                    self._run_index()
                else:
                    self._stop_event.wait(timeout=60)
                    continue
            self._stop_event.wait(timeout=self._interval)

    def _run_index(self) -> None:
        with self._lock:
            self._state = "indexing"

        self._vault.ensure_dirs()
        self._out_dir.mkdir(parents=True, exist_ok=True)
        self._vault.ensure_all_md_formats()

        success = self._run_graphify(self._vault.root)
        with self._lock:
            if success:
                self._state = "idle"
                self._last_indexed = datetime.now()
                self._last_error = None
            else:
                self._state = "stale"
        if success:
            _log.info("graphify index complete")
