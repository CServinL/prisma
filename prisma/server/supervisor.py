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
  POST /supervisor/resources/reload
       Re-reads compute_pools from config.yaml into the running
       ResourceManager — no restart, no lost in-flight leases. For tuning
       max_concurrent/per-model overrides against real observed GPU
       utilization without killing every worker to pick up one number.

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


def _ollama_base_url() -> str:
    try:
        import yaml
        cfg_path = Path.home() / ".config" / "prisma" / "config.yaml"
        cfg = yaml.safe_load(cfg_path.read_text()) or {}
        host = cfg.get("llm", {}).get("host", "localhost:11434")
        return f"http://{host}"
    except Exception:
        return "http://localhost:11434"


def _query_ollama_resident_mb(base_url: str, timeout: float = 2.0) -> dict[str, int] | None:
    """model name -> real size_vram in MB, straight from Ollama's own
    `/api/ps` — ground truth for what's actually loaded and its real cost
    right now, rather than tracking (and risking drift from) our own guess.
    Verified empirically 2026-07-02: Ollama's OLLAMA_MAX_LOADED_MODELS=0
    ("auto") already loads multiple different models concurrently when they
    fit — the assumption that a GPU can only ever hold one resident model
    at a time (baked into `model_affinity`) was never actually true for
    this setup, just untested. Returns None (not {}) on any failure to
    reach Ollama, so callers can fail safe (treat as "can't verify") rather
    than silently treating unreachable as "nothing's loaded.\""""
    import json
    import urllib.request
    try:
        with urllib.request.urlopen(f"{base_url}/api/ps", timeout=timeout) as resp:
            data = json.loads(resp.read())
        return {m["name"]: int(m.get("size_vram", 0)) // (1024 * 1024) for m in data.get("models", [])}
    except Exception:
        return None


def _model_vram_profile_path() -> Path:
    return Path.home() / ".config" / "prisma" / "model_vram_profiles.json"


def _load_vram_profiles() -> dict[str, int]:
    """Auto-learned model -> real resident VRAM MB, from past
    _probe_model_vram() runs. Distinct from compute_pools.*.models[].vram_mb
    in config.yaml: that's a manual, user-curated estimate and always wins
    when present (see _profile_missing_models) — this file only fills in
    models nobody ever measured by hand."""
    try:
        path = _model_vram_profile_path()
        return json.loads(path.read_text()) if path.exists() else {}
    except Exception:
        return {}


def _save_vram_profile(model: str, vram_mb: int) -> None:
    path = _model_vram_profile_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        profiles = _load_vram_profiles()
        profiles[model] = vram_mb
        path.write_text(json.dumps(profiles, indent=2))
    except Exception as exc:
        log.warning("failed to save vram profile for %s: %s", model, exc)


def _probe_model_vram(base_url: str, model: str, timeout: float = 300.0) -> int | None:
    """One-time empirical measurement: force `model` to load via a trivial
    generate call, then read its real resident cost back from Ollama's own
    `/api/ps` — the same manual process used throughout
    docs/qwen3-family-evaluation.md, automated. Returns None (not 0) if the
    probe itself fails (Ollama unreachable, model not pulled, etc.) — callers
    must not treat that as "this model uses 0MB.\""""
    import urllib.request
    try:
        req = urllib.request.Request(
            f"{base_url}/api/generate",
            data=json.dumps({
                "model": model, "prompt": "hi", "stream": False, "options": {"num_predict": 1},
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
    except Exception as exc:
        log.warning("vram profile: failed to load %s for probing: %s", model, exc)
        return None
    resident = _query_ollama_resident_mb(base_url)
    if resident is None or model not in resident:
        log.warning("vram profile: %s loaded but not found in /api/ps afterward", model)
        return None
    return resident[model]


def _check_pool_vram_fit(
    pool_models: dict[str, set[str]],
    pool_vram_budget: dict[str, int | None],
    affinity: set[str],
    model_vram: dict[str, dict[str, int]],
) -> dict[str, dict]:
    """Sum each VRAM-budget-aware pool's configured models' vram_mb (a
    config.yaml value, falling back to a saved auto-profile) against its
    vram_budget_mb — catches "these models don't fit together" at
    startup/config-load time instead of a human reasoning through the
    arithmetic after chat becomes unusable during a sync (the real incident
    in docs/qwen3-family-evaluation.md's Verdict section: qwen2.5:7b-32k +
    qwen3:14b-32k + nomic-embed-text summed to 20400MB against a 14000MB
    budget). Models with neither a config value nor a saved profile are
    skipped from the sum (unknown, not zero) and reported separately, since
    their absence makes this check optimistic rather than exact. Returns
    {pool: {total_mb, budget_mb, unknown_models}} only for pools whose
    already-known total exceeds budget — callers decide whether to just log
    or hard-fail on that."""
    saved_profiles = _load_vram_profiles()
    problems: dict[str, dict] = {}
    for pool_name in affinity:
        budget = pool_vram_budget.get(pool_name)
        if budget is None:
            continue
        configured = model_vram.get(pool_name, {})
        total = 0
        unknown: list[str] = []
        for model in pool_models.get(pool_name, set()):
            vram_mb = configured.get(model, saved_profiles.get(model))
            if vram_mb is None:
                unknown.append(model)
            else:
                total += vram_mb
        if total > budget:
            problems[pool_name] = {"total_mb": total, "budget_mb": budget, "unknown_models": unknown}
            log.warning(
                "vram fit: pool=%s configured models sum to %dMB, over its %dMB vram_budget_mb "
                "(models excluded from this sum for having no config/profile value yet: %s) — "
                "these models may not all coexist without an evict-and-reload cycle on every "
                "switch between them; see docs/qwen3-family-evaluation.md's Verdict for a real "
                "example of this failure mode",
                pool_name, total, budget, unknown or "none",
            )
    return problems


def _profile_missing_models(
    resources: "ResourceManager",
    pool_models: dict[str, set[str]],
    pool_vram_budget: dict[str, int | None],
    affinity: set[str],
    model_vram: dict[str, dict[str, int]],
    base_url: str,
) -> None:
    """Run once at supervisor startup, in its own daemon thread — for any
    model in a VRAM-budget-aware pool with neither a config.yaml `vram_mb`
    nor a previously saved profile, probe it for real and persist the
    result, updating the live ResourceManager immediately so it takes
    effect without a restart.

    Deliberately eager (runs right at startup, not lazily on first real
    acquire() and not gated behind an explicit admin command): trade-off
    accepted per cservinl's explicit choice — this can evict whatever's
    already resident and spends GPU time on a model that might not even get
    used this session, in exchange for every configured model having a real
    profile before anything production-shaped needs one. Motivated directly
    by the qwen3:14b-32k / qwen2.5:7b-32k VRAM-conflict incident (see
    docs/qwen3-family-evaluation.md's Verdict section) — once every
    configured model has a real profile, _check_pool_vram_fit() (called at
    the end of this function) can sum a pool's models against
    vram_budget_mb and flag "these don't fit together" before a config
    change ships, not just react to it after the fact.
    """
    saved_profiles = _load_vram_profiles()
    for pool_name in affinity:
        if pool_vram_budget.get(pool_name) is None:
            continue  # not vram-budget-aware — nothing here to inform
        configured = model_vram.get(pool_name, {})
        for model in pool_models.get(pool_name, set()):
            if model in configured or model in saved_profiles:
                continue
            log.info("vram profile: probing %s (pool=%s, no config or saved profile)", model, pool_name)
            vram_mb = _probe_model_vram(base_url, model)
            if vram_mb is None:
                continue
            _save_vram_profile(model, vram_mb)
            resources.note_model_vram(pool_name, model, vram_mb)
            log.info("vram profile: %s measured at %dMB, saved", model, vram_mb)
    # Re-check with the now-complete picture — a conflict previously
    # "unknown model, can't tell" may now be a known "doesn't fit," since
    # _check_pool_vram_fit re-reads the profile file fresh (includes
    # whatever was just probed and saved above).
    _check_pool_vram_fit(pool_models, pool_vram_budget, affinity, model_vram)


def _load_compute_pools() -> tuple[
    dict[str, int], set[str], dict[str, set[str]], dict[str, dict[str, int]],
    dict[str, int | None], dict[str, dict[str, int]], dict[str, dict[str, int]],
]:
    """Named compute pools and their concurrency limits, e.g.:

        compute_pools:
          - name: local-ollama       # a single GPU / single Ollama instance
            type: gpu                # models here can genuinely coexist in VRAM
            provider: ollama          # informational — for humans reading this file
            max_concurrent: 3         # fallback for any model below with no override
            vram_budget_mb: 14000     # total VRAM this pool may commit across ALL resident models
            models:
              - name: qwen2.5:7b-32k
                max_concurrent: 4      # matches this machine's OLLAMA_NUM_PARALLEL
                background_max_concurrent: 3  # reserve >=1 slot for interactive (chat)
                vram_mb: 7500          # estimate used only before it's ever been observed loaded
              - name: nomic-embed-text
                vram_mb: 1000
          - name: openrouter
            type: cloud               # auto-scaled/auto-routed — no swap penalty to model
            provider: openrouter
            max_concurrent: 8
            models: [anthropic/claude-3.5-sonnet]

    `type: gpu` pools model actual GPU VRAM sharing, which turned out to be
    richer than "one resident model at a time": verified empirically
    2026-07-01/02 that Ollama's `OLLAMA_MAX_LOADED_MODELS=0` ("auto") mode
    already loads *multiple* different models concurrently when they fit —
    the original `model_affinity` design (strict single-resident-model,
    still the default below when `vram_budget_mb` is omitted) was a
    conservative assumption, never actually verified against real behavior.
    When `vram_budget_mb` is set, `ResourceManager.acquire()` queries
    Ollama's own `/api/ps` live for what's *actually* resident and its real
    reported VRAM cost, and admits a not-yet-loaded model if the real
    current total plus its own `vram_mb` estimate fits under the budget —
    ground truth from Ollama beats a static guess for "what's loaded now,"
    but a new model's cost can only be estimated ahead of its first load.
    Falls back to the strict single-resident-model check if Ollama can't be
    reached (fail safe, not fail open — better to under-parallelize for one
    cycle than risk overcommitting VRAM on a guess). `type: cloud` = no
    such constraint at all (`model_affinity: false`'s old meaning). A pool
    with no `type` falls back to the legacy `model_affinity` key (default
    true) for configs written before `type` existed — `type` wins when
    both are present.

    Each `models` entry is either a plain string (uses the pool's own
    `max_concurrent`, no `vram_mb`/`background_max_concurrent`) or a
    `{name, max_concurrent?, vram_mb?, background_max_concurrent?}`
    mapping. `max_concurrent` still matters even with a VRAM budget: it
    bounds how many *simultaneous same-model* calls run at once, a
    separate concern from whether a second, different model may also load
    alongside it. `background_max_concurrent` reserves headroom for
    interactive traffic: `ResourceManager.acquire(..., priority=...)`
    callers tagged `"interactive"` (a live user request — chat) may use
    the model's full `max_concurrent`, while `"background"` callers (kg
    extraction, chroma embedding — the default) are capped at this smaller
    number, so interactive work never has to queue behind bulk background
    work filling every slot. Also used to auto-route a request to the
    right pool by model name (see ResourceManager.acquire) — e.g. so an
    OpenRouter model can never accidentally land in a `type: gpu` pool. A
    pool with `models` omitted (or empty) is untyped — a fallback candidate
    for any model no other pool explicitly claims, matching pre-`models`
    config files.

    If a machine has several GPUs, declare one `type: gpu` pool per GPU
    rather than one lump pool. Defaults to a single pool ("default",
    concurrency 1, type gpu, no VRAM budget — i.e. strict single-model
    behavior) if this section is omitted entirely — the safest possible
    assumption when nothing is configured.
    """
    try:
        import yaml
        cfg_path = Path.home() / ".config" / "prisma" / "config.yaml"
        cfg = yaml.safe_load(cfg_path.read_text()) or {}
        pools = cfg.get("compute_pools")
        if pools:
            capacity = {p["name"]: int(p.get("max_concurrent", 1)) for p in pools}
            affinity = {
                p["name"] for p in pools
                if (p.get("type") == "gpu") or (p.get("type") is None and p.get("model_affinity", True))
            }
            pool_models: dict[str, set[str]] = {}
            model_concurrency: dict[str, dict[str, int]] = {}
            pool_vram_budget: dict[str, int | None] = {}
            model_vram: dict[str, dict[str, int]] = {}
            model_background_limit: dict[str, dict[str, int]] = {}
            for p in pools:
                names: set[str] = set()
                overrides: dict[str, int] = {}
                vram: dict[str, int] = {}
                background: dict[str, int] = {}
                for entry in p.get("models", []):
                    if isinstance(entry, dict):
                        names.add(entry["name"])
                        if "max_concurrent" in entry:
                            overrides[entry["name"]] = int(entry["max_concurrent"])
                        if "vram_mb" in entry:
                            vram[entry["name"]] = int(entry["vram_mb"])
                        if "background_max_concurrent" in entry:
                            background[entry["name"]] = int(entry["background_max_concurrent"])
                    else:
                        names.add(entry)
                pool_models[p["name"]] = names
                model_concurrency[p["name"]] = overrides
                pool_vram_budget[p["name"]] = int(p["vram_budget_mb"]) if "vram_budget_mb" in p else None
                model_vram[p["name"]] = vram
                model_background_limit[p["name"]] = background
            return capacity, affinity, pool_models, model_concurrency, pool_vram_budget, model_vram, model_background_limit
    except Exception:
        pass
    return {"default": 1}, {"default"}, {"default": set()}, {"default": {}}, {"default": None}, {"default": {}}, {"default": {}}


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


def _process_memory_mb(pid: int) -> float | None:
    """Resident set size for a worker, in MB. Reads /proc directly (Linux
    only, stdlib-only) rather than adding psutil as a dependency — matches
    this module's "stdlib + yaml only" constraint (see module docstring).
    Returns None if unreadable (process gone, no /proc, permission denied)."""
    try:
        with open(f"/proc/{pid}/status", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    kb = int(line.split()[1])
                    return round(kb / 1024, 1)
    except (OSError, ValueError, IndexError):
        pass
    return None


def _system_info() -> dict:
    """CPU core count and total/available system memory, for capacity
    planning alongside per-worker memory_mb — e.g. deciding compute_pools
    sizing or whether OLLAMA_NUM_PARALLEL has real headroom. /proc/meminfo
    only (Linux), same stdlib-only reasoning as _process_memory_mb."""
    info: dict = {"cpu_count": os.cpu_count()}
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            fields = {}
            for line in f:
                if line.startswith(("MemTotal:", "MemAvailable:")):
                    key, val = line.split(":", 1)
                    fields[key] = round(int(val.split()[0]) / 1024, 1)
            info["memory_total_mb"] = fields.get("MemTotal")
            info["memory_available_mb"] = fields.get("MemAvailable")
    except (OSError, ValueError, IndexError):
        info["memory_total_mb"] = None
        info["memory_available_mb"] = None
    return info


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

    def __init__(
        self, pools: dict[str, int], model_affinity: set[str] = frozenset(),
        pool_models: dict[str, set[str]] | None = None,
        model_concurrency: dict[str, dict[str, int]] | None = None,
        vram_budget: dict[str, int | None] | None = None,
        model_vram: dict[str, dict[str, int]] | None = None,
        model_background_limit: dict[str, dict[str, int]] | None = None,
        ollama_base_url: str = "http://localhost:11434",
    ) -> None:
        self._lock = threading.Lock()
        self._capacity = dict(pools)
        self._model_affinity = set(model_affinity)
        self._pool_models = {name: set(models) for name, models in (pool_models or {}).items()}
        # pool -> {model: max_concurrent override} — different models resident
        # on the same GPU can have different safe concurrency ceilings (a
        # bigger num_ctx eats more VRAM per concurrent call). Falls back to
        # the pool's own max_concurrent for any model with no override.
        self._model_concurrency = {name: dict(m) for name, m in (model_concurrency or {}).items()}
        # pool -> total VRAM (MB) it may commit across ALL resident models at
        # once. None means "no budget configured" — falls back to the
        # strict single-resident-model rule for that pool (see acquire()).
        self._vram_budget = dict(vram_budget or {})
        # pool -> {model: estimated VRAM MB} — only used for a model that
        # isn't ALREADY resident (Ollama's own /api/ps gives the real cost
        # for anything already loaded; this estimate is only needed to
        # answer "would loading it push us over budget" ahead of time).
        self._model_vram = {name: dict(m) for name, m in (model_vram or {}).items()}
        # pool -> {model: max concurrent *background*-priority leases} — a
        # reservation, not a separate pool: interactive (chat) leases still
        # count against the same shared total, but background (kg
        # extraction, chroma embedding) leases alone are capped below the
        # model's full concurrency, guaranteeing interactive traffic always
        # has at least one free slot rather than queueing behind bulk work.
        self._model_background_limit = {name: dict(m) for name, m in (model_background_limit or {}).items()}
        self._ollama_base_url = ollama_base_url
        # pool -> {request_id: {holder, pid, model, acquired_at, timeout, priority}}
        self._leases: dict[str, dict[str, dict]] = {name: {} for name in pools}
        self._active_model: dict[str, str | None] = {name: None for name in pools}
        # Cumulative since supervisor start — answers "why is the server
        # busy" without grepping logs for 409s: how often has this pool
        # actually granted vs. turned work away, and why (full, busy with a
        # different model under strict affinity, or over the VRAM budget).
        # See status().
        self._stats: dict[str, dict[str, int]] = {
            name: {"granted": 0, "denied_capacity": 0, "denied_model_busy": 0, "denied_vram_budget": 0}
            for name in pools
        }

    def note_model_vram(self, pool: str, model: str, vram_mb: int) -> None:
        """Record a freshly-measured VRAM estimate for `model` in `pool`
        without a full reload_config() — used by the startup auto-profiling
        probe (_profile_missing_models) so a newly-learned profile takes
        effect immediately, without needing a supervisor restart."""
        with self._lock:
            self._model_vram.setdefault(pool, {})[model] = vram_mb

    def _candidate_pools(self, pool: str | None, model: str | None) -> list[str]:
        if pool:
            return [pool]
        if model:
            # Prefer pools that explicitly declare this model, so e.g. an
            # OpenRouter model auto-routes to a cloud pool and never lands in
            # a `type: gpu` pool by accident of dict iteration order. Pools
            # with no `models` declared at all are untyped — a fallback for
            # any model no other pool explicitly claims (matches config
            # files written before `models` existed).
            declared = [name for name, models in self._pool_models.items() if model in models]
            if declared:
                return declared
            untyped = [name for name, models in self._pool_models.items() if not models]
            if untyped:
                return untyped
        return list(self._capacity)

    def _effective_capacity(self, pool: str, model: str | None) -> int:
        """The concurrency ceiling that actually applies right now: a
        per-model override if this pool declares one for `model`, else the
        pool's own max_concurrent. On a `type: gpu` pool only one model is
        ever resident at a time, so "the incoming/active model's own limit"
        is always well-defined — no ambiguity about whose limit should win."""
        if model is not None:
            override = self._model_concurrency.get(pool, {}).get(model)
            if override is not None:
                return override
        return self._capacity[pool]

    def acquire(
        self, holder: str, pid: int, pool: str | None = None, timeout: float | None = None,
        model: str | None = None, priority: str = "background",
    ) -> tuple[str | None, str | None]:
        """Acquire a slot in `pool`, or auto-route by `model` against each
        pool's declared `models` allowlist, or the first pool with free
        capacity if neither narrows it down. Returns (pool_name, request_id),
        both None if no capacity is available anywhere (including: a
        `type: gpu` pool is busy with a different model and has no VRAM
        budget configured to admit it alongside, or is over budget).

        `priority`: "interactive" (a live user request — chat) or
        "background" (bulk/automated work — kg extraction, chroma
        embedding). Interactive callers may use a model's full configured
        concurrency; background callers are capped at that model's
        `background_max_concurrent` (if set), guaranteeing interactive
        traffic never has to queue behind bulk background work filling
        every slot."""
        with self._lock:
            candidates = self._candidate_pools(pool, model)
            for name in candidates:
                if name not in self._capacity:
                    continue
                vram_aware = name in self._model_affinity and self._vram_budget.get(name) is not None
                if name in self._model_affinity and not vram_aware:
                    active = self._active_model[name]
                    if active is not None and active != model:
                        self._stats[name]["denied_model_busy"] += 1
                        log.info(
                            "acquire denied: pool=%s holder=%s pid=%d model=%s priority=%s "
                            "reason=model_busy active=%s",
                            name, holder, pid, model, priority, active,
                        )
                        continue  # busy with a different model — must drain first
                elif vram_aware and model is not None:
                    resident = _query_ollama_resident_mb(self._ollama_base_url)
                    if resident is None:
                        # Can't verify Ollama's real state — fail safe to the
                        # strict single-resident-model rule rather than guess.
                        # vram-aware pools don't maintain _active_model (it'd
                        # be ambiguous with several models resident at once),
                        # so derive "busy with a different model" from actual
                        # lease data instead.
                        other_models = {l["model"] for l in self._leases[name].values() if l["model"] != model}
                        if other_models:
                            self._stats[name]["denied_model_busy"] += 1
                            log.info(
                                "acquire denied: pool=%s holder=%s pid=%d model=%s priority=%s "
                                "reason=model_busy (ollama unreachable, other resident models=%s)",
                                name, holder, pid, model, priority, sorted(other_models),
                            )
                            continue
                    elif model not in resident:
                        estimated_mb = self._model_vram.get(name, {}).get(model, 0)
                        current_mb = sum(resident.values())
                        if current_mb + estimated_mb > self._vram_budget[name]:
                            self._stats[name]["denied_vram_budget"] += 1
                            log.info(
                                "acquire denied: pool=%s holder=%s pid=%d model=%s priority=%s "
                                "reason=vram_budget current_mb=%d estimated_mb=%d budget_mb=%d resident=%s",
                                name, holder, pid, model, priority, current_mb, estimated_mb,
                                self._vram_budget[name], resident,
                            )
                            continue
                elif vram_aware and model is None:
                    # A vram-aware pool can't check budget/model-busy without
                    # knowing which model this is for — this endpoint is a
                    # real network boundary (supervisor.py's HTTP handler
                    # passes body.get("model") straight through, `None` if a
                    # request simply omits it), not just an internal
                    # in-process call every real client happens to populate
                    # correctly today. Fail safe (deny) rather than silently
                    # skip the check and let an unidentified model's lease
                    # through uncounted against the VRAM budget.
                    self._stats[name]["denied_vram_budget"] += 1
                    log.info(
                        "acquire denied: pool=%s holder=%s pid=%d priority=%s "
                        "reason=vram_budget (no model given, cannot verify VRAM headroom)",
                        name, holder, pid, priority,
                    )
                    continue
                # Per-model overrides apply on any model_affinity pool. On a
                # VRAM-budget pool several different models can hold leases
                # at once, so the count must be scoped to just this model's
                # own leases — on a strict (non-budget) pool every lease is
                # already guaranteed to be for the same resident model, so
                # the plain total is equivalent and cheaper.
                full_limit = self._effective_capacity(name, model if name in self._model_affinity else None)
                total_in_use = (
                    sum(1 for l in self._leases[name].values() if l["model"] == model)
                    if vram_aware else len(self._leases[name])
                )
                # Interactive traffic (chat) must never queue behind bulk
                # background work (kg extraction, chroma embedding) filling
                # every slot. Background requests are capped below the
                # model's full concurrency limit when a reservation is
                # configured, guaranteeing at least (full_limit -
                # background_limit) slots stay free for interactive callers
                # at all times — no live preemption needed, just a smaller
                # ceiling for the lower-priority tier.
                if priority == "background":
                    background_limit = self._model_background_limit.get(name, {}).get(model)
                    limit = min(full_limit, background_limit) if background_limit is not None else full_limit
                    # Two independent ceilings, both must hold:
                    # 1. background-scoped in_use < limit — protects
                    #    interactive's reservation. Must count only *other
                    #    background* leases, not interactive ones — counting
                    #    interactive against this reduced limit let a single
                    #    active chat silently steal from background's own
                    #    quota (observed: background denied at in_use=3/
                    #    limit=3 with only 2 of those 3 leases actually being
                    #    background).
                    # 2. total_in_use < full_limit — without this, once
                    #    interactive alone has already filled the pool to
                    #    its real max_concurrent, background_in_use is still
                    #    0 (zero *background* leases so far) and would be
                    #    granted anyway, pushing the pool past its
                    #    configured ceiling entirely (found live: fixing #1
                    #    alone, in an earlier pass, introduced this — the
                    #    background-only count was never checked against
                    #    real total capacity at all).
                    in_use = sum(
                        1 for l in self._leases[name].values()
                        if l["priority"] == "background" and (not vram_aware or l["model"] == model)
                    )
                    admitted = in_use < limit and total_in_use < full_limit
                else:
                    limit = full_limit
                    in_use = total_in_use
                    admitted = in_use < limit
                if admitted:
                    request_id = f"{holder}-{pid}-{uuid.uuid4().hex[:8]}"
                    self._leases[name][request_id] = {
                        "holder": holder, "pid": pid, "model": model,
                        "acquired_at": time.monotonic(), "timeout": timeout, "priority": priority,
                    }
                    if name in self._model_affinity and not vram_aware:
                        self._active_model[name] = model
                    self._stats[name]["granted"] += 1
                    return name, request_id
                self._stats[name]["denied_capacity"] += 1
                holders = ", ".join(
                    f"{l['holder']}:{l['model']}({l['priority']})" for l in self._leases[name].values()
                )
                log.info(
                    "acquire denied: pool=%s holder=%s pid=%d model=%s priority=%s reason=capacity "
                    "in_use=%d limit=%d total_in_use=%d full_limit=%d current_leases=[%s]",
                    name, holder, pid, model, priority, in_use, limit, total_in_use, full_limit, holders,
                )
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

    def reload_config(
        self, pools: dict[str, int], model_affinity: set[str] = frozenset(),
        pool_models: dict[str, set[str]] | None = None,
        model_concurrency: dict[str, dict[str, int]] | None = None,
        vram_budget: dict[str, int | None] | None = None,
        model_vram: dict[str, dict[str, int]] | None = None,
        model_background_limit: dict[str, dict[str, int]] | None = None,
    ) -> None:
        """Re-read compute_pools from config.yaml into a *running*
        ResourceManager, without restarting the supervisor or touching
        in-flight leases. Motivated by tuning `max_concurrent`/per-model
        overrides against real observed GPU utilization (e.g. a model turns
        out to have more VRAM headroom than its configured concurrency
        assumed) — that shouldn't require killing every worker and losing
        whatever they were mid-doing just to pick up one changed number.
        Existing leases for a pool that still exists are left alone even if
        its capacity shrank below the current lease count (no forced
        eviction — they'll simply block new acquires until they drain); a
        pool removed from config entirely keeps its existing leases
        releasable but stops accepting new ones (acquire() already skips
        any name not in the fresh self._capacity)."""
        with self._lock:
            self._capacity = dict(pools)
            self._model_affinity = set(model_affinity)
            self._pool_models = {name: set(models) for name, models in (pool_models or {}).items()}
            self._model_concurrency = {name: dict(m) for name, m in (model_concurrency or {}).items()}
            self._vram_budget = dict(vram_budget or {})
            self._model_vram = {name: dict(m) for name, m in (model_vram or {}).items()}
            self._model_background_limit = {name: dict(m) for name, m in (model_background_limit or {}).items()}
            for name in pools:
                self._leases.setdefault(name, {})
                self._active_model.setdefault(name, None)
                self._stats.setdefault(
                    name, {"granted": 0, "denied_capacity": 0, "denied_model_busy": 0, "denied_vram_budget": 0},
                )

    def status(self) -> dict:
        with self._lock:
            now = time.monotonic()
            return {
                name: {
                    "type": "gpu" if name in self._model_affinity else "cloud",
                    "capacity": self._capacity[name],
                    "in_use": len(leases),
                    "active_model": self._active_model[name] if name in self._model_affinity else None,
                    "resident_models": sorted({l["model"] for l in leases.values() if l["model"]}),
                    "vram_budget_mb": self._vram_budget.get(name),
                    "models": sorted(self._pool_models.get(name, set())),
                    # Per-model effective capacity — the flat "capacity" above
                    # is only the pool-wide *fallback*; a model with its own
                    # override (common on a VRAM-budget pool with several
                    # models) has a different real ceiling, and showing the
                    # fallback instead was a genuinely confusing display bug
                    # (looked like "1/3" when the real limit for the
                    # resident model was actually 4).
                    "model_capacity": {
                        model: {
                            "in_use": sum(1 for l in leases.values() if l["model"] == model),
                            "limit": self._effective_capacity(name, model),
                            "background_limit": self._model_background_limit.get(name, {}).get(model),
                        }
                        for model in sorted({l["model"] for l in leases.values() if l["model"]}
                                             | set(self._model_concurrency.get(name, {})))
                    },
                    "stats": dict(self._stats[name]),
                    "leases": [
                        {
                            "request_id": rid,
                            "holder": l["holder"],
                            "pid": l["pid"],
                            "model": l["model"],
                            "held_for_s": round(now - l["acquired_at"], 1),
                            "timeout": l["timeout"],
                            "priority": l.get("priority", "background"),
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
        # down every worker (and, transitively, anything they spawned) instead
        # of leaving them orphaned — see main()'s signal handling, which
        # routes both SIGINT and SIGTERM through this method.
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
                        "memory_mb": _process_memory_mb(w.proc.pid) if w.proc and w.is_alive() else None,
                    }
                    for name, w in supervisor.workers.items()
                }
                status["resources"] = supervisor.resources.status()
                status["system"] = _system_info()
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
                    priority=body.get("priority", "background"),
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
            elif self.path == "/supervisor/resources/reload":
                (capacity, affinity, pool_models, model_concurrency,
                 vram_budget, model_vram, model_background_limit) = _load_compute_pools()
                supervisor.resources.reload_config(
                    capacity, affinity, pool_models, model_concurrency,
                    vram_budget, model_vram, model_background_limit,
                )
                self._json(200, {"status": "reloaded", "pools": list(capacity)})
            else:
                self._json(404, {"error": "not found"})

    return Handler


def main(
    host: str = "127.0.0.1",
    api_port: int = 8765,
    web_port: int = 8766,
    chroma_port: int = 8767,
    kg_port: int = 8768,
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
        # through several steps (stream scheduler, chroma indexer) before
        # uvicorn actually exits. A short outer timeout here would SIGKILL it
        # before that finishes, orphaning whatever it was still cleaning up.
        "api": Worker("api", api_cmd, stop_timeout=10.0,
                      env={"PRISMA_SUPERVISOR_PORT": str(supervisor_port), "PRISMA_KG_PORT": str(kg_port)}),
        "web": Worker("web", [_venv_bin("uvicorn"), "prisma.server.web_app:app", "--host", host, "--port", str(web_port)]),
        "chroma": Worker("chroma", [
            _venv_bin("chroma"), "run",
            "--path", str(chroma_dir),
            "--host", "127.0.0.1",  # loopback only, regardless of the API/Web bind host
            "--port", str(chroma_port),
        ]),
        # Owns the sole Kùzu connection (see knowledge_graph_service.py's
        # module docstring — only one process may ever hold that database
        # open) and does all LLM extraction itself, isolated from the api
        # process: a native-extension crash here doesn't take REST/WebSocket
        # down with it, it can be restarted independently, and its CPU work
        # (semchunk splitting, JSON parsing, Cypher upserts) runs on its own
        # core instead of competing with api's event loop. Longer stop_timeout
        # since a single extraction call can run up to 120s.
        "kg": Worker("kg", [_venv_bin("uvicorn"), "prisma.server.kg_app:app", "--host", host, "--port", str(kg_port)],
                     stop_timeout=15.0, env={"PRISMA_SUPERVISOR_PORT": str(supervisor_port)}),
    }
    capacity, affinity, pool_models, model_concurrency, pool_vram_budget, model_vram, model_background_limit = (
        _load_compute_pools()
    )
    resources = ResourceManager(
        capacity, affinity, pool_models, model_concurrency, pool_vram_budget, model_vram,
        model_background_limit, ollama_base_url=_ollama_base_url(),
    )
    # Best-effort check with whatever's already known (config + previously
    # saved profiles) — don't wait for the profiling thread below, which can
    # take minutes if several models need a fresh probe. Re-checked with the
    # complete picture at the end of that thread too.
    _check_pool_vram_fit(pool_models, pool_vram_budget, affinity, model_vram)
    threading.Thread(
        target=_profile_missing_models,
        args=(resources, pool_models, pool_vram_budget, affinity, model_vram, _ollama_base_url()),
        daemon=True, name="vram-profiler",
    ).start()

    supervisor = Supervisor(workers, resources)
    supervisor.start_all()

    http_server = ThreadingHTTPServer(("127.0.0.1", supervisor_port), _make_handler(supervisor))
    http_thread = threading.Thread(target=http_server.serve_forever, daemon=True, name="supervisor-http")
    http_thread.start()
    log.info("control API on http://127.0.0.1:%d", supervisor_port)
    log.info("API on http://%s:%d  Web on http://%s:%d  KG on http://%s:%d", host, api_port, host, web_port, host, kg_port)

    # A plain `kill <pid>` sends SIGTERM, which Python does not turn into a
    # catchable KeyboardInterrupt by default — without this handler, only
    # Ctrl+C would trigger stop_all(), and SIGTERM would skip cleanup entirely,
    # orphaning every worker (and transitively their own children). preexec_fn's
    # PR_SET_PDEATHSIG is the last-resort backstop for the even-more-abrupt
    # SIGKILL case, which no signal handler can catch.
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
