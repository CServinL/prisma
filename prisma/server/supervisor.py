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
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
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


class Worker:
    def __init__(self, name: str, cmd: list[str]) -> None:
        self.name = name
        self.cmd = cmd
        self.proc: subprocess.Popen | None = None
        self.restart_count = 0

    def start(self) -> None:
        # Own session — a signal to the supervisor's terminal doesn't propagate
        # directly to workers; the supervisor terminates them deliberately instead.
        self.proc = subprocess.Popen(self.cmd, start_new_session=True)
        log.info("started %s (pid=%d): %s", self.name, self.proc.pid, " ".join(self.cmd))

    def is_alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self, timeout: float = 5.0) -> None:
        if self.proc is None or self.proc.poll() is not None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    def restart(self) -> None:
        self.stop()
        self.start()
        self.restart_count += 1


class Supervisor:
    _POLL_INTERVAL = 2.0
    _MAX_BACKOFF = 30.0

    def __init__(self, workers: dict[str, Worker]) -> None:
        self.workers = workers
        self._stop_event = threading.Event()

    def start_all(self) -> None:
        for w in self.workers.values():
            w.start()

    def stop_all(self) -> None:
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
                self._json(200, {"status": "restarted", "worker": name})
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
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")

    vault_root = _resolve_vault_root()
    chroma_dir = vault_root / "chromadb"
    chroma_dir.mkdir(parents=True, exist_ok=True)

    api_cmd = [_venv_bin("uvicorn"), "prisma.server.app:app", "--host", host, "--port", str(api_port)]
    if reload:
        api_cmd.append("--reload")

    workers = {
        "api": Worker("api", api_cmd),
        "web": Worker("web", [_venv_bin("uvicorn"), "prisma.server.web_app:app", "--host", host, "--port", str(web_port)]),
        "chroma": Worker("chroma", [
            _venv_bin("chroma"), "run",
            "--path", str(chroma_dir),
            "--host", "127.0.0.1",  # loopback only, regardless of the API/Web bind host
            "--port", str(chroma_port),
        ]),
    }

    supervisor = Supervisor(workers)
    supervisor.start_all()

    http_server = ThreadingHTTPServer(("127.0.0.1", supervisor_port), _make_handler(supervisor))
    http_thread = threading.Thread(target=http_server.serve_forever, daemon=True, name="supervisor-http")
    http_thread.start()
    log.info("control API on http://127.0.0.1:%d", supervisor_port)
    log.info("API on http://%s:%d  Web on http://%s:%d", host, api_port, host, web_port)

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
