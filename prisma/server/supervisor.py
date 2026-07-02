"""Prisma process supervisor — see ADR-012.

Deliberately imports nothing beyond the standard library (plus `yaml`, a
small, low-risk dependency already required for config) — no fastapi, no
chromadb, no graphify. This is the "most basic and safe" layer: if every
other dependency in this codebase has a bug, the supervisor should still be
able to report that and attempt recovery.

Spawns and monitors three long-running worker processes:
  - api:    prisma.server.app       (REST + WebSocket)
  - web:    prisma.server.web_app   (serves the built UI at /app)
  - chroma: `chroma run`            (ChromaDB's own server, not embedded)

Exposes a minimal control surface on a loopback-only port:
  GET  /supervisor/status
  POST /supervisor/restart/{name}
  POST /supervisor/resources/acquire
       {"holder": "api", "pid": 12345, "resource": "local_ollama"?, "timeout": 300?, "model": "qwen2.5:7b"?}
       -> {"granted": bool, "resource": str|null, "request_id": str|null}
  POST /supervisor/resources/release
       {"resource": "local_ollama", "request_id": "..."}

Compute-resource locking (GPU/LLM/embeddings): the supervisor has no idea
which actions actually use a GPU, or whether "the LLM" is a local GPU, a
remote Ollama box, or a cloud API — it just holds named, capacity-limited
pool leases (configured via compute_pools in config.yaml; default: one
pool, "default", concurrency 1) and arbitrates them. Any code about to do
LLM/embedding work is responsible for its own acquire -> use -> release
around that work.

Every lease carries the requester's actual PID and an optional timeout, not
just its worker name — a finer-grained safety net than "the whole worker
died": a single task inside api/web/chroma can die, or just hang, without
releasing, independent of whether the process that spawned it is still
alive. Two mechanisms clear an abandoned lease:
  - release_all_held_by(name): fast path, triggered the moment a worker
    dies or is restarted (crash-detected or via POST /restart/{name})
  - reap(): general path, runs every monitor-loop tick — checks every held
    lease's PID (os.kill(pid, 0)) and configured timeout, independent of
    which worker (if any) is still alive
"""
from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

log = logging.getLogger("prisma.supervisor")


def _resolve_vault_root() -> Path:
    try:
        import yaml
        cfg_path = Path.home() / ".config" / "prisma" / "config.yaml"
        cfg = yaml.safe_load(cfg_path.read_text()) or {}
        root = cfg.get("vault_root", "").strip()
        if root:
            return Path(root).expanduser().resolve()
    except Exception:
        pass
    return Path.home() / "prisma-vault"


def _venv_bin(name: str) -> str:
    """Resolve a console script installed in the same venv as this interpreter,
    so we don't depend on PATH."""
    candidate = Path(sys.executable).parent / name
    return str(candidate) if candidate.exists() else name


def _load_compute_pools() -> tuple[dict[str, int], set[str]]:
    """Named compute pools and their concurrency limits, e.g.:

        compute_pools:
          - name: local_ollama       # a single GPU / single Ollama instance
            max_concurrent: 3        # can only hold one model's weights at a time
          - name: gpu1_ollama        # a second GPU, pinned to a different model
            max_concurrent: 2
          - name: cloud_api
            max_concurrent: 4
            model_affinity: false    # auto-scaled/auto-routed — no swap penalty to model

    One pool = one hardware unit that can hold exactly one resident model at
    a time (one GPU, or one Ollama instance bound to one GPU) — that's the
    thing `model_affinity` describes, and it **defaults to true**, because
    that's what real hardware does. If a machine has several GPUs and you
    want them able to hold different models at once (or the same model
    spread across more of them for extra concurrency), declare one pool per
    GPU rather than one lump pool — acquire() already tries every pool with
    no preferred one specified, so it naturally lands same-model requests on
    whichever GPU already has that model loaded (or an idle one), and turns
    away a different model from a busy one until it drains. The only pools
    that should set `model_affinity: false` are ones with no such constraint
    at all — a cloud API that auto-scales/auto-routes across models with no
    reload penalty. Defaults to a single pool ("default", concurrency 1,
    affinity true) if this section is omitted entirely — the common case of
    one machine, one local GPU, one Ollama instance, zero config required.
    See ResourceManager for what `model_affinity` changes about acquire().
    """
    try:
        import yaml
        cfg_path = Path.home() / ".config" / "prisma" / "config.yaml"
        cfg = yaml.safe_load(cfg_path.read_text()) or {}
        pools = cfg.get("compute_pools")
        if pools:
            capacity = {p["name"]: int(p.get("max_concurrent", 1)) for p in pools}
            affinity = {p["name"] for p in pools if p.get("model_affinity", True)}
            return capacity, affinity
    except Exception:
        pass
    return {"default": 1}, {"default"}


def _die_with_parent() -> None:
    """Linux-only, best-effort: ask the kernel to SIGTERM this child the
    moment its parent (the supervisor) dies, for any reason — including
    SIGKILL, a crash, or the supervisor being wrapped by something like
    `timeout` that only kills the process it launched directly.

    start_new_session=True deliberately isolates workers from a signal sent
    to the supervisor's terminal, so stop_all() is normally the only thing
    that stops them — but that means if the supervisor itself dies without
    running stop_all(), nothing else will. This closes that gap: it doesn't
    depend on any Python cleanup code running at all.
    """
    try:
        import ctypes
        PR_SET_PDEATHSIG = 1
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM)
    except Exception:
        pass  # non-Linux, or prctl unavailable — best effort only


class Worker:
    def __init__(self, name: str, cmd: list[str], stop_timeout: float = 5.0,
                 env: dict[str, str] | None = None) -> None:
        self.name = name
        self.cmd = cmd
        self.proc: subprocess.Popen | None = None
        self.restart_count = 0
        self._stop_timeout = stop_timeout
        self._env = {**os.environ, **env} if env else None

    def start(self) -> None:
        # Own session — a signal to the supervisor's terminal doesn't propagate
        # directly to workers; the supervisor terminates them deliberately instead.
        # preexec_fn is the safety net for when that deliberate path never runs.
        self.proc = subprocess.Popen(
            self.cmd, start_new_session=True, preexec_fn=_die_with_parent, env=self._env,
        )
        log.info("started %s (pid=%d): %s", self.name, self.proc.pid, " ".join(self.cmd))

    def is_alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self) -> None:
        if self.proc is None or self.proc.poll() is not None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=self._stop_timeout)
        except subprocess.TimeoutExpired:
            log.warning("%s did not exit within %.0fs — killing", self.name, self._stop_timeout)
            self.proc.kill()

    def restart(self) -> None:
        self.stop()
        self.start()
        self.restart_count += 1


def _configure_logging() -> None:
    """Console + a rotating supervisor.log, so worker restarts, resource
    lease grants/denials, and reaper activity survive after the terminal
    they were started from is gone — previously this only used
    logging.basicConfig (console only), so anything the supervisor logged
    was lost the moment its stdout wasn't being watched live.

    Deliberately not importing prisma.server.log_setup here (which pulls in
    pydantic) — see module docstring: this stays stdlib + yaml only.
    log_setup.paths().supervisor points at the same file, purely as a path
    for the api process's /logs viewer to read; it owns no handler for it.
    """
    import logging.handlers

    base = Path.home() / ".local" / "share" / "prisma" / "logs"
    base.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(name)s] %(levelname)s %(message)s")

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    file_handler = logging.handlers.RotatingFileHandler(
        base / "supervisor.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8",
    )
    file_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(console)
    root.addHandler(file_handler)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just not ours to signal
    except Exception:
        return True  # unknown — fail safe, don't release something we're unsure about


class ResourceManager:
    """Tracks named compute pools — one pool per hardware unit that can hold
    exactly one resident model at a time ("local GPU, 3 concurrent calls",
    "a second local GPU pinned to a different model", "cloud API, 4
    concurrent inferences, no model constraint at all") — and arbitrates
    capacity-limited access. The supervisor doesn't know or care what a pool
    actually is, only its configured concurrency and how many callers
    currently hold a lease in it.
    Any code about to do LLM/embedding/AI work is responsible for its own
    acquire -> use -> release around that work.

    Every lease carries the requesting process's actual PID (not just its
    worker name) and an optional timeout, so a task that dies — or just
    hangs — without releasing doesn't wedge a pool's capacity forever:
    reap() actively checks both and clears anything abandoned. This is more
    precise than only reacting to a whole worker process dying, since a
    single task inside api/web/chroma can die (or wedge) independently of
    the process that spawned it.

    `model_affinity` pools (e.g. a single local GPU that can only hold one
    model's weights at a time) additionally track which model is currently
    resident: concurrent leases are only granted for that same model, up to
    `max_concurrent`. A request for a different model is denied — same as
    "pool full" — until every existing lease for the current model has been
    released and the pool goes idle, at which point the next request's model
    becomes the new resident one. This is what makes "3 concurrent calls to
    the same model" and "2 tasks that use different models" both correct:
    the former batches, the latter serializes, without the caller needing to
    know which situation it's in.
    """

    def __init__(self, pools: dict[str, int], model_affinity: set[str] = frozenset()) -> None:
        self._lock = threading.Lock()
        self._capacity = dict(pools)
        self._model_affinity = set(model_affinity)
        # pool -> {request_id: {holder, pid, model, acquired_at, timeout}}
        self._leases: dict[str, dict[str, dict]] = {name: {} for name in pools}
        self._active_model: dict[str, str | None] = {name: None for name in pools}
        # Cumulative since supervisor start — answers "why is the server
        # busy" without grepping logs for 409s: how often has this pool
        # actually granted vs. turned work away, and why (full vs. busy with
        # a different model). See status().
        self._stats: dict[str, dict[str, int]] = {
            name: {"granted": 0, "denied_capacity": 0, "denied_model_busy": 0} for name in pools
        }

    def acquire(
        self, holder: str, pid: int, pool: str | None = None, timeout: float | None = None,
        model: str | None = None,
    ) -> tuple[str | None, str | None]:
        """Acquire a slot in `pool`, or the first pool with free capacity if
        not specified. Returns (pool_name, request_id), both None if no
        capacity is available anywhere (including: a model_affinity pool is
        busy with a different model)."""
        with self._lock:
            candidates = [pool] if pool else list(self._capacity)
            for name in candidates:
                if name not in self._capacity:
                    continue
                if name in self._model_affinity:
                    active = self._active_model[name]
                    if active is not None and active != model:
                        self._stats[name]["denied_model_busy"] += 1
                        continue  # busy with a different model — must drain first
                if len(self._leases[name]) < self._capacity[name]:
                    request_id = f"{holder}-{pid}-{uuid.uuid4().hex[:8]}"
                    self._leases[name][request_id] = {
                        "holder": holder, "pid": pid, "model": model,
                        "acquired_at": time.monotonic(), "timeout": timeout,
                    }
                    if name in self._model_affinity:
                        self._active_model[name] = model
                    self._stats[name]["granted"] += 1
                    return name, request_id
                self._stats[name]["denied_capacity"] += 1
        return None, None

    def _clear_active_model_if_idle(self, pool: str) -> None:
        if pool in self._model_affinity and not self._leases.get(pool):
            self._active_model[pool] = None

    def release(self, pool: str, request_id: str) -> None:
        with self._lock:
            self._leases.get(pool, {}).pop(request_id, None)
            self._clear_active_model_if_idle(pool)

    def release_all_held_by(self, holder: str) -> None:
        with self._lock:
            for name, leases in self._leases.items():
                for rid in [rid for rid, l in leases.items() if l["holder"] == holder]:
                    del leases[rid]
                self._clear_active_model_if_idle(name)

    def reap(self) -> None:
        """Actively release leases whose process has died or whose configured
        timeout has elapsed. Called periodically from the supervisor's
        monitor loop — this is the general safety net; release_all_held_by
        (triggered on a worker restart) is the faster-reacting special case
        for the common failure (the whole worker died)."""
        now = time.monotonic()
        with self._lock:
            for name, leases in self._leases.items():
                dead = []
                for rid, l in leases.items():
                    if not _pid_alive(l["pid"]):
                        log.warning("lease %s in pool %r (pid=%d, holder=%s) is dead — releasing",
                                    rid, name, l["pid"], l["holder"])
                        dead.append(rid)
                    elif l["timeout"] is not None and (now - l["acquired_at"]) > l["timeout"]:
                        log.warning("lease %s in pool %r exceeded its %.0fs timeout — releasing",
                                    rid, name, l["timeout"])
                        dead.append(rid)
                for rid in dead:
                    del leases[rid]
                self._clear_active_model_if_idle(name)

    def status(self) -> dict:
        with self._lock:
            now = time.monotonic()
            return {
                name: {
                    "capacity": self._capacity[name],
                    "in_use": len(leases),
                    "active_model": self._active_model[name] if name in self._model_affinity else None,
                    "stats": dict(self._stats[name]),
                    "leases": [
                        {
                            "request_id": rid,
                            "holder": l["holder"],
                            "pid": l["pid"],
                            "model": l["model"],
                            "held_for_s": round(now - l["acquired_at"], 1),
                            "timeout": l["timeout"],
                        }
                        for rid, l in leases.items()
                    ],
                }
                for name, leases in self._leases.items()
            }


class Supervisor:
    _POLL_INTERVAL = 2.0
    _MAX_BACKOFF = 30.0

    def __init__(self, workers: dict[str, Worker], resources: ResourceManager) -> None:
        self.workers = workers
        self.resources = resources
        self._stop_event = threading.Event()

    def start_all(self) -> None:
        for w in self.workers.values():
            w.start()

    def stop_all(self) -> None:
        # Ensures a full `kill <supervisor-pid>` (not just Ctrl+C) still tears
        # down every worker (and, transitively, anything they spawned, like a
        # graphify run) instead of leaving them orphaned — see main()'s signal
        # handling, which routes both SIGINT and SIGTERM through this method.
        self._stop_event.set()
        for w in self.workers.values():
            w.stop()

    def monitor_loop(self) -> None:
        backoff = {name: 1.0 for name in self.workers}
        while not self._stop_event.is_set():
            for name, w in self.workers.items():
                if self._stop_event.is_set():
                    break
                if w.is_alive():
                    backoff[name] = 1.0
                    continue
                delay = backoff[name]
                log.warning("%s died unexpectedly — restarting in %.0fs", name, delay)
                if self._stop_event.wait(timeout=delay):
                    break
                w.restart()
                backoff[name] = min(delay * 2, self._MAX_BACKOFF)
                # Whatever that worker was doing (including any resource lease
                # it held) is gone now that it's restarted — release its leases
                # so a legitimately new request isn't blocked forever by one
                # that no longer exists.
                self.resources.release_all_held_by(name)
            self.resources.reap()
            self._stop_event.wait(timeout=self._POLL_INTERVAL)


def _make_handler(supervisor: Supervisor):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            log.info("http: " + fmt, *args)

        def _json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json_body(self) -> dict:
            length = int(self.headers.get("Content-Length", 0) or 0)
            if length == 0:
                return {}
            try:
                return json.loads(self.rfile.read(length))
            except Exception:
                return {}

        def do_GET(self) -> None:
            if self.path == "/supervisor/status":
                status = {
                    name: {
                        "pid": w.proc.pid if w.proc else None,
                        "alive": w.is_alive(),
                        "restart_count": w.restart_count,
                    }
                    for name, w in supervisor.workers.items()
                }
                status["resources"] = supervisor.resources.status()
                self._json(200, status)
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self) -> None:
            if self.path.startswith("/supervisor/restart/"):
                name = self.path.rsplit("/", 1)[-1]
                w = supervisor.workers.get(name)
                if w is None:
                    self._json(404, {"error": f"unknown worker: {name!r}"})
                    return
                w.restart()
                supervisor.resources.release_all_held_by(name)
                self._json(200, {"status": "restarted", "worker": name})
            elif self.path == "/supervisor/resources/acquire":
                body = self._read_json_body()
                holder, pid = body.get("holder"), body.get("pid")
                if not holder or not pid:
                    self._json(400, {"error": "missing 'holder' or 'pid'"})
                    return
                resource, request_id = supervisor.resources.acquire(
                    holder, pid, body.get("resource"), body.get("timeout"), body.get("model"),
                )
                self._json(200 if resource else 409, {
                    "granted": resource is not None, "resource": resource, "request_id": request_id,
                })
            elif self.path == "/supervisor/resources/release":
                body = self._read_json_body()
                resource, request_id = body.get("resource"), body.get("request_id")
                if not resource or not request_id:
                    self._json(400, {"error": "missing 'resource' or 'request_id'"})
                    return
                supervisor.resources.release(resource, request_id)
                self._json(200, {"status": "released"})
            else:
                self._json(404, {"error": "not found"})

    return Handler


def main(
    host: str = "127.0.0.1",
    api_port: int = 8765,
    web_port: int = 8766,
    chroma_port: int = 8767,
    supervisor_port: int = 8760,
    reload: bool = False,
) -> None:
    _configure_logging()

    vault_root = _resolve_vault_root()
    chroma_dir = vault_root / "chromadb"
    chroma_dir.mkdir(parents=True, exist_ok=True)

    api_cmd = [_venv_bin("uvicorn"), "prisma.server.app:app", "--host", host, "--port", str(api_port)]
    if reload:
        api_cmd.append("--reload")

    workers = {
        # Longer stop_timeout: the api process's own graceful shutdown cascades
        # through several steps (stream scheduler, chroma indexer, graphify
        # indexer — which itself waits up to 5s to terminate a subprocess) before
        # uvicorn actually exits. A short outer timeout here would SIGKILL it
        # before that finishes, orphaning whatever it was still cleaning up.
        "api": Worker("api", api_cmd, stop_timeout=10.0,
                      env={"PRISMA_SUPERVISOR_PORT": str(supervisor_port)}),
        "web": Worker("web", [_venv_bin("uvicorn"), "prisma.server.web_app:app", "--host", host, "--port", str(web_port)]),
        "chroma": Worker("chroma", [
            _venv_bin("chroma"), "run",
            "--path", str(chroma_dir),
            "--host", "127.0.0.1",  # loopback only, regardless of the API/Web bind host
            "--port", str(chroma_port),
        ]),
    }
    resources = ResourceManager(*_load_compute_pools())

    supervisor = Supervisor(workers, resources)
    supervisor.start_all()

    http_server = ThreadingHTTPServer(("127.0.0.1", supervisor_port), _make_handler(supervisor))
    http_thread = threading.Thread(target=http_server.serve_forever, daemon=True, name="supervisor-http")
    http_thread.start()
    log.info("control API on http://127.0.0.1:%d", supervisor_port)
    log.info("API on http://%s:%d  Web on http://%s:%d", host, api_port, host, web_port)

    # A plain `kill <pid>` sends SIGTERM, which Python does not turn into a
    # catchable KeyboardInterrupt by default — without this handler, only
    # Ctrl+C would trigger stop_all(), and SIGTERM would skip cleanup entirely,
    # orphaning every worker (and transitively their own children, like a
    # graphify run). preexec_fn's PR_SET_PDEATHSIG is the last-resort backstop
    # for the even-more-abrupt SIGKILL case, which no signal handler can catch.
    def _handle_sigterm(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _handle_sigterm)

    try:
        supervisor.monitor_loop()
    except KeyboardInterrupt:
        pass
    finally:
        log.info("shutting down")
        http_server.shutdown()
        supervisor.stop_all()


if __name__ == "__main__":
    main()
