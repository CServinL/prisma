"""Client helper for the supervisor's compute-pool leases (see
prisma.server.supervisor.ResourceManager and ADR-012).

Any code about to do LLM/embedding/AI work — the knowledge graph indexer's
extraction calls, ChromaDB's embedding calls, and eventually chat — should
acquire a lease before starting and release it when done. Pools are named and capacity-
limited (e.g. "local Ollama, 1 concurrent call" vs "remote Ollama, 12
concurrent calls") — the caller doesn't pick a pool, the supervisor grants
whichever has a free slot; the operator defines pools and their concurrency
in config (see prisma.server.supervisor._load_compute_pools).

Every acquire sends this process's own PID and gets back a request_id, so
the supervisor can actively detect an abandoned lease (dead PID, or a
configurable timeout elapsed) independent of whether the worker process
that made the call is still alive — see ResourceManager.reap().

Fails open if the supervisor's control API isn't reachable at all (e.g.
someone runs `uvicorn prisma.server.app:app` directly, bypassing the
supervisor, for local dev) — in that case there's nothing to arbitrate
against, so the caller proceeds unlocked rather than being blocked forever
waiting on a controller that was never started.
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager

import requests

from prisma.services import backoff

_log = logging.getLogger("prisma.resource_lock")


def default_port() -> int:
    """Supervisor control port — set by prisma.server.supervisor when it
    spawns a worker process, so callers inside that process talk to the same
    supervisor instance even if --supervisor-port was customized. Falls back
    to the supervisor's own default when unset (e.g. standalone CLI usage
    with no supervisor running at all — acquire() fails open regardless)."""
    try:
        return int(os.environ.get("PRISMA_SUPERVISOR_PORT", "8760"))
    except ValueError:
        return 8760


def acquire(
    host: str, port: int, holder: str, lease_timeout: float | None = None, timeout: float = 3.0,
    model: str | None = None, pool: str | None = None, priority: str = "background",
) -> tuple[bool, str | None, str | None]:
    """Returns (proceed, resource, request_id). `resource` + `request_id` are
    what release() needs later; both are None if there was nothing to
    release (denied, or the supervisor wasn't reachable and we're proceeding
    unlocked). `lease_timeout` bounds how long this lease may be held before
    the supervisor reaps it even if our PID is still alive (e.g. a wedged
    call) — pass the same ceiling the actual work is bounded by. `model` names
    which model this call will run — on a model_affinity pool (e.g. a single
    local GPU that holds one model's weights at a time), a different model
    than the one currently resident is denied rather than granted, since
    running it would evict the other and defeat the point of a "concurrent"
    lease; the caller's normal retry/backoff naturally waits for that pool to
    drain instead. `pool` requests a *specific* named pool (e.g. a cloud
    backend that must never share a lease with a model_affinity'd local GPU
    pool, even though the server would otherwise auto-select whichever pool
    has free capacity) — omit to let the supervisor pick. `priority`:
    "interactive" for a live user request (chat) that must never queue
    behind bulk background work, or "background" (the default) for
    automated/bulk work (kg extraction, chroma embedding) — see
    ResourceManager.acquire for what this actually changes."""
    try:
        resp = requests.post(
            f"http://{host}:{port}/supervisor/resources/acquire",
            json={
                "holder": holder, "pid": os.getpid(), "timeout": lease_timeout,
                "model": model, "resource": pool, "priority": priority,
            },
            timeout=timeout,
        )
    except requests.RequestException:
        _log.warning("supervisor unreachable at %s:%d — proceeding without a resource lease", host, port)
        return True, None, None
    if resp.status_code == 200:
        data = resp.json()
        return True, data.get("resource"), data.get("request_id")
    return False, None, None


def status(host: str, port: int, timeout: float = 3.0) -> dict:
    """Current compute-pool usage, straight from the supervisor's own
    ResourceManager.status() (capacity, in-use count, and each held lease's
    holder/pid/age) — for surfacing on the api process's /status endpoint so
    resource contention is visible without hitting the supervisor's own
    loopback-only control port directly. Returns {} if the supervisor isn't
    reachable, same fail-open spirit as acquire()."""
    try:
        resp = requests.get(f"http://{host}:{port}/supervisor/status", timeout=timeout)
        resp.raise_for_status()
        return resp.json().get("resources", {})
    except requests.RequestException:
        _log.warning("supervisor unreachable at %s:%d — resource status unavailable", host, port)
        return {}


def process_status(host: str, port: int, timeout: float = 3.0) -> dict:
    """Per-worker pid/alive/restart_count/memory_mb plus system-wide
    cpu_count/memory_total_mb/memory_available_mb, straight from the
    supervisor — same fail-open spirit as status()/acquire(): returns {} if
    the supervisor isn't reachable, for surfacing on the api process's
    /status endpoint without hitting the supervisor's loopback-only control
    port directly. Useful for capacity planning (compute_pools sizing,
    whether OLLAMA_NUM_PARALLEL has real headroom) alongside the resource
    contention stats status() already exposes."""
    try:
        resp = requests.get(f"http://{host}:{port}/supervisor/status", timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        return {k: v for k, v in data.items() if k != "resources"}
    except requests.RequestException:
        _log.warning("supervisor unreachable at %s:%d — process status unavailable", host, port)
        return {}


def restart_worker(host: str, port: int, name: str, timeout: float = 10.0) -> dict:
    """Restarts one supervisor-managed worker process (api/web/chroma/kg) —
    for surfacing on the api process's UI-facing reload control without the
    UI needing direct access to the supervisor's loopback-only control port.
    Same fail-open-ish spirit as status()/process_status(): returns
    {"error": ...} rather than raising if the supervisor isn't reachable or
    the worker name is unknown."""
    try:
        resp = requests.post(f"http://{host}:{port}/supervisor/restart/{name}", timeout=timeout)
        return resp.json()
    except requests.RequestException as exc:
        _log.warning("supervisor unreachable at %s:%d — could not restart %r: %s", host, port, name, exc)
        return {"error": str(exc)}


def release(host: str, port: int, resource: str | None, request_id: str | None, timeout: float = 3.0) -> None:
    if resource is None or request_id is None:
        return
    try:
        requests.post(
            f"http://{host}:{port}/supervisor/resources/release",
            json={"resource": resource, "request_id": request_id},
            timeout=timeout,
        )
    except requests.RequestException:
        _log.warning("supervisor unreachable at %s:%d — could not release %r", host, port, resource)


@contextmanager
def lease(
    host: str, port: int, holder: str, lease_timeout: float | None = None, max_wait: float = 10.0,
    model: str | None = None, pool: str | None = None, priority: str = "background",
):
    """Context manager wrapping acquire -> yield granted -> release, so
    callers don't hand-roll the same try/finally. A denied acquire (pool at
    capacity, or — on a model_affinity pool — busy with a different model) is
    retried with backoff.retry_with_backoff for up to `max_wait` seconds
    before giving up — a busy pool clearing up half a second later is the
    common case, not the exception, so a bare first-try failure would reject
    work that a moment's patience would have let through. Yields whether the
    lease was ultimately granted (or proceeding unlocked, supervisor
    unreachable) — callers should skip their GPU/LLM work entirely when this
    is False:

        with resource_lock.lease(host, port, holder="api", model="qwen2.5:7b") as granted:
            if not granted:
                return  # no free compute pool right now
            ... do the LLM/embedding call ...

    Always pass `model` when the call is going to a specific model — it's
    what lets the supervisor tell "3 concurrent calls to the same model"
    (fine, batch them) apart from "2 tasks that need different models"
    (must serialize, since only one model's weights fit at a time). Pass
    `pool` when the caller must land on one *specific* named pool rather
    than "whichever has free capacity" — e.g. a cloud backend that must
    never be auto-routed into a model_affinity'd local-GPU pool, which
    would otherwise misattribute the cloud model as that GPU's resident
    model and start denying real local Ollama calls for no hardware reason.
    Pass `priority="interactive"` for a live user request (chat) that must
    never queue behind bulk background work — leave the "background"
    default for automated/bulk callers (kg extraction, chroma embedding).
    """
    proceed, resource, request_id = backoff.retry_with_backoff(
        lambda: acquire(host, port, holder, lease_timeout, model=model, pool=pool, priority=priority),
        is_success=lambda result: result[0],
        max_wait=max_wait,
    )
    try:
        yield proceed
    finally:
        release(host, port, resource, request_id)
