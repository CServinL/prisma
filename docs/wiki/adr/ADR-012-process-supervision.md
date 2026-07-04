# ADR-012: Process Supervision — Independent, Crash-Isolated Components

**Date:** 2026-06-30
**Author:** CServinL
**Status:** Accepted

## Context

Prisma currently runs as a single process (`prisma serve`). Every component —
REST API, WebSocket, UI static serving, the Graphify indexer, and the ChromaDB
vector index — lives inside that one process, sharing its memory, its threads,
and its fate.

Two incidents during PWA/WebSocket testing exposed the cost of this:

1. **ChromaDB partial-init crash.** `_ensure_client()` could leave a client
   handle set but its collection `None` after a transient failure. The
   background indexer thread then hit `None.upsert()` on the next file
   change — an unhandled exception that silently killed the `chroma-indexer`
   thread for the rest of the process's life. No error surfaced anywhere a
   user would see it; the only symptom was search results going stale forever.
2. **Graphify subprocess killed by inherited signal.** The extraction
   subprocess wasn't in its own process group, so a terminal Ctrl+C (SIGINT
   to the whole foreground process group) killed it directly and abruptly,
   independent of whatever cleanup logic ran in the parent. Every interrupted
   run left the index in "stale" with no clean recovery path short of another
   full run.

Both were fixed at the code level (see the `chroma_service.py` and
`graphify_service.py` commits on `feat/pwa-websocket`), but the fixes only
patch symptoms of a deeper structural issue: **there is no supervisor.**
Nothing in this system observes "a component died" and does something about
it. Recovering requires a human to notice broken behavior, find the log line,
and restart the entire process — losing every other component's state and
in-flight work along the way. And even that only works if the human knows to
do it; the ChromaDB failure produced no crash, no restart, just silent staleness.

There's also a second, unrelated problem this surfaces: Python caches
imported modules in memory for the life of a process. Editing `chroma_service.py`
on disk has zero effect on an already-running `prisma serve` until the whole
process restarts. The existing `/reload/*` endpoints (`/reload/vault`,
`/reload/indexer`, etc.) only construct fresh *instances* of already-imported
classes — they cannot pick up code changes. A full process restart is the
only way to load new code today, and a full process restart currently means
losing everything, not just the one component that changed.

## Decision

Split Prisma's runtime into a minimal **supervisor process** plus several
independently-restartable **worker processes**:

```
prisma serve
  └── supervisor (new, tiny entrypoint — no fastapi/chromadb/graphify imports)
       ├── spawns: API process       (uvicorn + prisma.server.app — REST + WS, no UI mount)
       ├── spawns: Web process       (uvicorn + a minimal static-file app — serves ui/build/ at /app)
       ├── spawns: Chroma server     (`chroma run` — ChromaDB's own server, not embedded)
       └── (on demand) Graphify subprocess — spawned by the API process's indexer, as today
```

### Supervisor

A new, deliberately dependency-free entrypoint. It imports nothing beyond the
Python standard library — no `fastapi`, no `chromadb`, no `pydantic`. This is
the "most basic and safe" layer the whole system is asked to keep running: if
every other dependency in this codebase has a bug, the supervisor should still
be able to report that fact and attempt a restart.

Responsibilities:
- Spawn each worker as a `subprocess.Popen`, in its own session
  (`start_new_session=True`, same fix applied to Graphify in this PR) so a
  terminal signal to the supervisor doesn't propagate directly to workers.
- Poll each worker's liveness (`proc.poll()`) on an interval.
- On unexpected exit, restart with exponential backoff (capped) to avoid a
  crash-looping component consuming resources or flooding logs.
- Expose a minimal control surface using `http.server` (not FastAPI) on a
  loopback-only port:
  - `GET /supervisor/status` — which workers are up, their PID, restart count
  - `POST /supervisor/restart/{name}` — deliberate restart of one worker
    (this is what actually reloads new code, unlike `/reload/*`)

### ChromaDB becomes a real server

Today `ChromaIndexer` embeds ChromaDB via `chromadb.PersistentClient(path=...)`
directly in the API process's background thread. That's why the partial-init
bug took down a thread inside the API process rather than being an isolated,
independently-recoverable failure.

Moving to `chroma run --path {vault}/chromadb --port {chroma_port}` as its own
supervised process, with the API process's `ChromaIndexer` using
`chromadb.HttpClient(host="127.0.0.1", port={chroma_port})` instead, means:
- A ChromaDB crash doesn't touch the API process's threads at all
- The supervisor can restart just the Chroma server without restarting the
  API, losing in-flight note edits, or dropping active WebSocket connections
- The persisted vector data's lifecycle is fully decoupled from the API
  process's lifecycle

The watchdog + incremental-embedding logic (`ChromaIndexer._loop`, the mtime
guard fixed in this PR) stays where it is, inside the API process — only the
storage backend moves out-of-process.

### API and Web as separate processes

Per discussion: the API (REST + WS) and the UI static file serving become
independent processes, each independently restartable. The API process no
longer mounts `/app`; a new minimal web-serving module (reusing the
`_CleanUrlStaticFiles` clean-URL resolution built in this PR) does that job
alone.

**Open question this creates:** browsers now see two different origins/ports
for one logical application — the API's port for `fetch()`/WebSocket calls,
the Web process's port for the page itself. This has real consequences:
- CORS must allow the Web process's origin to call the API
- The WebSocket connection (`new WebSocket(...)`) must point at the API's
  origin, not the page's own origin — `apiBase`-style configuration, already
  partially in place for Tauri, needs to also cover the browser/PWA case
- The PWA manifest's `scope`/`start_url` and the service worker's registration
  scope are tied to the origin the page loads from (the Web process), which
  is fine, but any same-origin assumptions elsewhere need auditing

For LAN/WAN deployments (ADR-011, deployment-models.md), a user-operated
reverse proxy in front of both processes — whatever the operator chooses to
run — can unify them into one public origin by routing `/app/*` to the Web
process and everything else to the API process. That reverse proxy is outside
Prisma's own scope; deployment-models.md documents it as operator-managed
infrastructure, not something the project depends on or ships. For local
dev/Tauri use, the client already supports an explicit, configurable
`apiBase`, so pointing it at a different port than the page's own origin is
not new. This ADR does not fully resolve the browser/PWA same-origin case for
LAN access without a proxy in front — that's a follow-up decision, not
blocking this ADR.

### Graphify stays request-scoped, not supervisor-managed

Graphify's subprocess is spawned on demand by the API process's
`GraphifyIndexer` (already fixed for graceful shutdown via `start_new_session`
+ `stop()` terminating it deliberately). It is not a long-running supervised
worker like the other three — it only exists for the duration of an indexing
run. No change from its current design beyond what's already shipped in this
PR.

### Addendum — GPU/LLM compute-pool leasing

Live testing surfaced a real incident this design didn't originally cover:
three `graphify` subprocesses ended up running **simultaneously**, all
hammering the same local Ollama instance, driving GPU utilization to ~100%
for over half an hour with no single component able to see or explain why.

Root cause was a race in `GraphifyIndexer._run_graphify`: `subprocess.Popen()`
returned before `self._current_proc` was assigned, so a concurrent `stop()`
(e.g. from a reload triggered while a run was already in flight) could read a
stale/`None` value, terminate nothing, and silently orphan the subprocess it
should have stopped. That race is fixed at the `GraphifyIndexer` level (the
lock now spans the whole check-spawn-register step), but the deeper issue is
architectural: **the supervisor had no visibility into this at all.** Graphify
is a grandchild — spawned by the API process, not the supervisor — so even
a perfectly correct `GraphifyIndexer` still can't, by itself, guarantee that
some *other* GPU/LLM-using component (ChromaDB's embeddings today, chat
later) doesn't run concurrently against the same constrained backend.

**Decision:** the supervisor gains a second responsibility beyond crash
isolation — arbitrating a small set of **named, capacity-limited compute
pools** (`ResourceManager` in `supervisor.py`). A pool models whatever "the
LLM" actually is for a given deployment — a single local GPU, a beefier
remote multi-GPU box, a rate-limited cloud API — each with its own
concurrency ceiling, configured via `compute_pools` in `config.yaml`
(defaults to one pool, `"default"`, concurrency 1, if unconfigured). Any
code about to do LLM/embedding/AI work follows the same protocol: **look for
a free pool, acquire a lease, do the work, release it.** The supervisor
doesn't know or care what a pool is actually backed by — only whether it's
currently full.

Each lease is tied to the requester's actual OS PID and carries an optional
timeout, not just a worker name. Two independent mechanisms prevent an
abandoned lease from wedging a pool forever:
- `release_all_held_by(name)` — the fast path: fires the instant a
  *supervised* worker (api/web/chroma) dies or is restarted.
- `ResourceManager.reap()` — the general path: runs every monitor-loop tick,
  checks every held lease's PID (`os.kill(pid, 0)`) and configured timeout
  independent of which worker (if any) is still alive. This is what actually
  catches the graphify incident's failure mode: a single task dying or
  wedging without its parent worker process crashing at all.

Graphify is the first integrated caller (`prisma.services.resource_lock`,
holder `"api"`, lease timeout matched to its own `7200`s hard ceiling).
ChromaDB's embeddings and the analysis agent's Ollama calls are wired the
same way as a later follow-up (both go through the same `resource_lock.lease`
choke point, so this only needed one place to change).

#### Follow-up — retry/backoff, model affinity, and contention stats

Three refinements landed after the initial addendum above, driven by real
usage rather than being designed up front:

- **Retry with backoff** (`prisma.services.backoff`): a denied `acquire()` is
  retried with exponential backoff + jitter for up to `max_wait` (default
  10s) before `lease()` gives up — a pool clearing up a fraction of a second
  later is the common case, not the exception, so a bare first-try failure
  was rejecting work a moment's patience would have let through.
- **`model_affinity`** (default: **true**): a compute pool models one
  hardware unit that can hold exactly one resident model's weights at a time
  (one GPU, or one Ollama instance bound to one GPU) — confirmed by
  benchmark in `docs/ollama-concurrency.md`: 3 concurrent calls to the
  *same* model batch for a real ~2x speedup, but alternating between two
  models costs ~4-9s of reload per switch regardless of concurrency. A
  `model_affinity` pool tracks which model is currently resident and only
  grants concurrent leases for that same model; a request for a different
  model is denied (same as "pool full") until the pool drains. Only pools
  with no such constraint at all — an auto-scaled/auto-routed cloud API —
  should set `model_affinity: false`. Multiple GPUs are modeled as multiple
  pools (one per GPU), not one pool with a bigger capacity; `acquire()`
  already tries every pool when the caller doesn't pin one, so same-model
  demand naturally spills across GPUs and different models can sit pinned to
  different GPUs at once.
- **Contention stats** (`ResourceManager._stats`, surfaced in `status()` as
  `resources.<pool>.stats`): cumulative `granted` / `denied_capacity` /
  `denied_model_busy` counts per pool since the supervisor started. Motivated
  by exactly the scenario this ADR describes — three components silently
  fighting over one GPU with no way to see it — but this time for the
  *within-design-limits* case: a long Graphify run legitimately holding the
  pool for its whole extraction pass (which can take a long time on a slow
  chunk) silently starves ChromaDB's embeddings and the analysis agent's
  relevance/identity checks for that entire window, each falling back to its
  own "LLM unavailable" default. That's the correct trade-off for one shared
  GPU, but previously the only way to see it happening was grepping
  `supervisor.log` for 409s. The stats counter answers "why is the server
  busy" directly from `/status` instead.

#### Follow-up — Graphify replaced with a native module, running as a 4th worker

The `graphify` pip dependency mentioned throughout this ADR ("Graphify is
the first integrated caller," "the graphify incident's failure mode," etc.)
has been removed as of 2026-07-01. `prisma/services/knowledge_graph_service.py`
(`KnowledgeGraphService`) replaces it, with native storage (embedded Kùzu
graph DB, not a flat `graph.json`) and per-*section* extraction chunking
(not per-file), which closes the token-budget cliff a single oversized
document used to hit with no recovery path. Full rationale, alternatives
considered, and consequences are in their own ADR: **ADR-013**. (Also see
ADR-009's follow-up section and `TODO.md`.)

Kùzu's concurrency model was verified empirically before adopting it: only
one process may hold the database open at all (a `READ_WRITE` connection
locks out every other Database object, even `READ_ONLY` ones, in any other
process). Not a blocker — only one process needs graph access, ever — but
worth remembering: no external tool/script can open the graph DB file
directly (even read-only) while that process is running.

That single-process-only constraint, plus the same crash-isolation
reasoning that made ChromaDB its own server in this ADR's original
decision, is why **`KnowledgeGraphService` runs as a 4th supervised worker
process** (`kg_app.py`, a small FastAPI app, `:8768` by default) rather than
embedded inside `api` — a native-extension crash or a wedged extraction
call no longer takes REST/WebSocket traffic down with it, it can be
restarted independently, and its CPU work (semchunk splitting, Cypher
upserts) runs on its own core instead of competing with api's event loop.
Unlike ChromaDB, there's no ready-made server binary for Kùzu (`chroma run`
already existed; `kuzu serve` doesn't) — `kg_app.py` *is* that server, built
for this purpose. `app.py` talks to it through `KnowledgeGraphClient`
(`prisma/services/knowledge_graph_client.py`), a thin HTTP client matching
`KnowledgeGraphService`'s exact method names, so no call-site changes were
needed beyond construction. Resource-lock holder is `"kg"`, matching the
worker name — same `local-ollama` pool, same `model_affinity` behavior as
before, just attributed to the correct worker for `release_all_held_by()`
to fire on crash/restart. Gets its own log file (`kg.log`, `/logs?concern=kg`),
same pattern as `chroma`/`ollama`/`activity`/`maintenance`.

#### Follow-up — model-aware pools, live config reload, and named-pool routing (2026-07-02)

Three refinements to the compute-pool model, driven by real usage rather
than designed up front:

- **`compute_pools` schema gained `type: gpu|cloud` and per-model
  `max_concurrent` overrides.** The original `model_affinity` boolean
  still works (read as a fallback when `type` is absent), but `type` is
  now the primary way to declare a pool's behavior, and each pool's
  `models` list can assign a *specific* model its own concurrency ceiling
  (`{name, max_concurrent}`, or a plain string to just use the pool's
  default) — motivated by kg extraction and chat running genuinely
  different-sized workloads on the same physical GPU (see ADR-013's
  follow-up: they later turned out to be the same model anyway, but the
  mechanism itself is real and still used — analysis_agent's `llama3.1:8b`
  and the embedding model share the pool with different implicit costs).
  `models` doubles as an auto-routing table: `ResourceManager.acquire()`
  now prefers whichever pool explicitly declares the requested model
  before falling back to "any pool with room," so a cloud model can never
  accidentally land in a `type: gpu` pool and get misattributed as its
  resident model — a real gap this closes, not a hypothetical one: chat
  needed exactly this once a `openrouter` pool was added
  alongside `local-ollama`.
- **`resource_lock.acquire()`/`lease()` gained a real `pool` parameter.**
  Previously the *client* side had no way to request a specific pool at
  all — the server-side `ResourceManager.acquire()` always supported it,
  but nothing ever sent it over the wire (this exact gap was found and
  the corresponding `ChatConfig.pool` field deliberately dropped earlier,
  rather than shipping a config option that silently did nothing). Now
  wired end-to-end: `ChatLLM` passes `chat.pool` from config, so cloud
  calls stay correctly isolated from the local GPU pool's model_affinity
  serialization instead of relying on auto-routing alone.
- **`POST /supervisor/resources/reload`** (+ `prisma reload-resources` CLI)
  re-reads `compute_pools` into a *running* `ResourceManager` — no
  restart, no lost in-flight leases. Built after discovering, live, that
  `local-ollama`'s GPU was sitting at ~20-40% utilization during
  extraction — tuning `max_concurrent` to actually use that headroom
  shouldn't require killing every worker just to pick up one changed
  number. `ResourceManager.reload_config()` swaps the capacity/affinity/
  model-routing dicts under the lock; existing leases for a pool that
  still exists are left untouched even if its capacity shrank below the
  current lease count (no forced eviction).

#### Future consideration: transport for the lease protocol

Acquire/release currently go over plain HTTP to the supervisor's control
port (`requests.post`, localhost). For graphify's usage pattern — one
acquire and one release per run, each run lasting minutes — this overhead is
immaterial; it's not on any hot path.

That stops being true if the same protocol is extended to ChromaDB's
embedding calls, which are frequent and individually fast (triggered on
every vault file change). Per-embed HTTP round-trips would add real,
avoidable latency to a hot path. Two mitigations, in order of preference
when that integration happens:
1. **Batch the lease, not the call** — acquire once per indexing pass
   (however many chunks it embeds), not once per chunk. Keeps HTTP, keeps
   the pattern consistent with graphify, and the per-pass overhead stays
   negligible regardless of chunk count.
2. **If per-call granularity turns out to be unavoidable**, reconsider the
   transport itself. A Unix domain socket removes the TCP/IP stack overhead
   but keeps HTTP/JSON parsing cost and loses ad-hoc `curl` debuggability.
   A more structural alternative: model each pool slot as a lock file and use
   `fcntl.flock()` — the kernel releases the lock automatically the instant
   the holding process dies, for *any* reason including `SIGKILL`, which
   would replace PID-tracking and `reap()` for the crash case entirely (a
   hung-but-alive process would still need the timeout mechanism on top).
   Trade-off: loses the single `GET /supervisor/status` view of who holds
   what without extra scanning code, and loses centralized arbitration (it
   becomes a race between processes for lock files rather than an explicit
   grant/deny). Not adopted now — HTTP is not costing us anything at
   graphify's usage frequency — but the right thing to revisit if/when a
   high-frequency caller is added.

### Ensuring nothing survives the supervisor itself

Every worker (and Graphify's own subprocess) runs in its own session
(`start_new_session=True`) specifically so a signal sent to the supervisor's
terminal doesn't propagate to them directly — `stop_all()` is meant to be
the only thing that stops them, deliberately and gracefully. That design
has a sharp edge: if the supervisor itself is killed abruptly and
`stop_all()` never runs, nothing else does either. This wasn't hypothetical —
it happened during testing, when a `timeout N prisma serve &` wrapper used
for smoke-testing killed the supervisor process after its timeout without
ever giving it a chance to clean up, leaving nine worker processes (and
three more graphify subprocesses from a separate incident) running
untouched, hours later, still consuming GPU.

Two fixes, addressing different failure modes:
- **`SIGTERM` handling.** Python does not turn `SIGTERM` into a catchable
  `KeyboardInterrupt` by default — only Ctrl+C (`SIGINT`) went through
  `stop_all()` before this fix. A plain `kill <supervisor-pid>` bypassed
  cleanup entirely. `main()` now installs a `SIGTERM` handler that raises
  `KeyboardInterrupt`, routing both signals through the same graceful path.
- **`PR_SET_PDEATHSIG` (Linux, best-effort) as the backstop for everything a
  signal handler can't catch** — `SIGKILL`, an unhandled crash, or a wrapper
  that force-kills the supervisor outright. Every worker (and Graphify's
  subprocess) is spawned with a `preexec_fn` that asks the kernel to send it
  `SIGTERM` the moment its direct parent dies, for any reason. This doesn't
  depend on any Python cleanup code running at all — even if `stop_all()`
  never executes, the OS still tears down the tree.
- The `api` worker's own `stop_timeout` was also bumped from 5s to 10s: its
  internal graceful shutdown cascades through several steps (stream
  scheduler, ChromaDB indexer, Graphify indexer — which itself waits up to
  5s to terminate a subprocess) before uvicorn actually exits. The previous
  5s outer timeout could have `SIGKILL`'d the api process mid-cascade,
  orphaning whatever it was still in the middle of cleaning up.

Verified live: `SIGTERM` to the supervisor now cleanly stops all three
workers (each logging its own graceful shutdown) with zero processes left
behind, confirmed via `ps aux` immediately after.

### Relationship to existing `/reload/*` endpoints

The existing endpoints (`/reload/vault`, `/reload/zotero`, `/reload/indexer`,
`/reload/chroma`) remain — they're for lightweight, in-process state resets
(config changed, re-authenticate Zotero, etc.) that don't require new code.
`POST /supervisor/restart/{name}` is a different, heavier operation: a full
process restart that picks up code changes on disk. Both have a place; they
solve different problems.

## Alternatives Considered

### Status quo — single process, in-process reload only

Rejected. This is precisely what produced an undetectable silent failure
(ChromaDB) and an ungraceful, unrecoverable-without-full-restart failure
(Graphify). No amount of individual bug-fixing changes the fact that any
future bug in any component can still take down or silently wedge the whole
system, indefinitely, with no automated recovery.

### External process supervisor (systemd, supervisord)

Rejected for now. Standard, well-tested tooling, but: adds a deployment
dependency not available identically across the target platforms (Linux
systemd vs WSL2 vs eventual Windows-native support per the multi-platform
roadmap), and doesn't integrate with the existing `/reload/*` API-driven
control surface the UI's Settings panel already uses. A hand-rolled
supervisor keeps the control plane consistent (HTTP endpoints, one place to
look) and keeps deployment identical to today (`prisma serve`, nothing else
to install). Revisit if the hand-rolled version grows unwieldy.

### Keep ChromaDB embedded, isolate it into our own subprocess with custom IPC

Considered. Would still achieve crash isolation, but requires designing and
maintaining a bespoke IPC protocol for something ChromaDB already solves via
its own client/server mode. Using `chroma run` + `HttpClient` gets the same
isolation using the tool's own supported server mode — no custom protocol to
maintain.

## Consequences

### Positive
- A crash in ChromaDB, the API, or the Web server no longer takes down the
  other two, or the whole system
- The supervisor can detect and recover from failures automatically, without
  a human noticing broken behavior first
- `POST /supervisor/restart/{name}` gives an actual code-reload path, which
  `/reload/*` never could
- ChromaDB's data lifecycle is fully decoupled from the API process

### Negative
- More moving parts: 3 long-running processes instead of 1, plus the
  supervisor itself — more to reason about, more ports to manage
- ChromaDB calls go over loopback HTTP instead of an in-process call — small
  latency cost, acceptable given ChromaDB calls aren't on any hot path that's
  latency-sensitive at the scale this runs at
- Browser/PWA same-origin story needs a follow-up decision (an operator-run
  reverse proxy in front, or another unification strategy) for clean LAN
  access without a proxy
- Restart-storm handling (backoff, giving up after N attempts and surfacing
  a persistent failure rather than looping forever) needs to be right, or a
  broken component becomes a resource-burning loop instead of a silent one

## Related ADRs

- ADR-010: Transport Layer Strategy (the WebSocket broadcast mechanism this
  ADR's API process hosts)
- ADR-011: Authentication Strategy (zone-based auth; supervisor and Chroma
  server should bind loopback-only regardless of zone, only API/Web cross
  network boundaries)
- ADR-013: Native Knowledge Graph (the `kg` worker's own crash-isolation
  and storage-backend rationale, extending this ADR's supervised-worker
  pattern to a 4th process)
